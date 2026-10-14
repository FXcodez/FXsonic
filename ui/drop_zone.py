"""
Folder drag & drop zones for the FXsonic workbench.

Two surfaces accept a folder dragged out of the OS file manager:

  1. the source directory field in the top navigation bar ("the input folder"),
  2. the Inspector / track info panel on the right ("the track info zone").

Why this is not just a NiceGUI event handler
--------------------------------------------
In native mode NiceGUI does **not** host the window itself::

    MainProcess   -> uvicorn + NiceGUI (pages, state, every event handler)
    SpawnProcess-1 -> pywebview -> WebView2 -> the native window

Both processes import ``main.py``, so both get their own copy of
``webview.dom._dnd_state``.  WebView2 deliberately hides real filesystem paths
from page JavaScript (``DataTransfer.files[*].path`` is not available), so the
host hands them to pywebview in the **window** process, which stores them in
*its* ``_dnd_state['paths']``.  The page can only call
``chrome.webview.postMessageWithAdditionalObjects('FilesDropped', files)`` and
then emit a pathless payload to the server.

That is why a naive implementation never works: the NiceGUI ``drop`` handler runs
in MainProcess, whose ``_dnd_state`` is a *different, permanently empty* dict.

The bridge implemented here:

  window process : :func:`harvest_native_entries` pops the ``(name, path)`` pairs
                   pywebview published and POSTs them to the server
                   (:func:`start_native_drop_forwarder`),
  server process : ``POST /fxsonic/native-drop`` (:func:`install_native_drop_endpoint`)
                   resolves the first real directory and applies it to the live
                   workbench (:func:`apply_native_entries` -> ``intake_directory``).

Finding the server from the window process is its own subtlety: NiceGUI spawns the
window subprocess inside ``native.activate()``, i.e. *before* it exports
``NICEGUI_*``, and ``pywebview.Window`` exposes ``real_url`` (not ``url``).  The
environment alone is therefore not trustworthy, so ``main.py`` hands the port over
explicitly (:func:`set_server_port`) and also exports ``FXSONIC_PORT``.  Without
that, every native drop fails with "no server address to forward to".

When the app is served to a plain browser (``FXSONIC_HEADLESS=1``) there is no
WebView2 host, no forwarder and no real path; the page then reports whatever hint
it has (``path`` / ``webkitRelativePath``) and the server resolves it directly via
:func:`resolve_dropped_folder`.
"""

import asyncio
import json
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence
from urllib.parse import unquote, urlsplit

from core.diagnostics import diag, log_file_path

# Class toggled on the drop target while a folder is hovering it (see ui/theme.py).
DROP_ACTIVE_CLASS = "fx-drop-active"

# Endpoint the window process posts resolved drops to (see the module docstring).
NATIVE_DROP_ROUTE = "/fxsonic/native-drop"

# Window-process forwarder tuning.
FORWARD_POLL_SECONDS = 0.05
WINDOW_WAIT_SECONDS = 120.0
POST_TIMEOUT_SECONDS = 5.0
DEDUPE_WINDOW_SECONDS = 5.0

# Port NiceGUI binds to when the user does not override it (see FXSONIC_PORT).
DEFAULT_SERVER_PORT = 8080

# Port handed over explicitly by main.py; see set_server_port().
_server_port: Optional[int] = None

# ---------------------------------------------------------------------------
# Client-side handlers.  These are evaluated by the browser/NiceGUI client, so
# they must stay dependency free and defensive (any throw would break the drop).
# ---------------------------------------------------------------------------
_JS_DRAG_OVER = """(e) => {
    const dt = e.dataTransfer;
    if (!dt) { return; }
    const types = dt.types ? Array.prototype.slice.call(dt.types) : [];
    const fileItems = dt.items
        ? Array.prototype.filter.call(dt.items, (i) => i && i.kind === 'file')
        : [];
    const isFileDrag = types.indexOf('Files') !== -1
        || (dt.files && dt.files.length > 0)
        || fileItems.length > 0;
    if (!isFileDrag) { return; }
    e.preventDefault();
    if (e.stopPropagation) { e.stopPropagation(); }
    try { dt.dropEffect = 'copy'; } catch (err) {}
    if (e.currentTarget && e.currentTarget.classList) {
        e.currentTarget.classList.add('%s');
    }
}""" % DROP_ACTIVE_CLASS

_JS_DRAG_LEAVE = """(e) => {
    e.preventDefault();
    if (e.relatedTarget && e.currentTarget && e.currentTarget.contains(e.relatedTarget)) {
        return;
    }
    if (e.currentTarget && e.currentTarget.classList) {
        e.currentTarget.classList.remove('%s');
    }
}""" % DROP_ACTIVE_CLASS

_JS_DROP = """(e) => {
    e.preventDefault();
    if (e.stopPropagation) { e.stopPropagation(); }
    if (e.currentTarget && e.currentTarget.classList) {
        e.currentTarget.classList.remove('%s');
    }
    const dt = e.dataTransfer;
    const files = (dt && dt.files) ? dt.files : null;
    let hint = '';
    let hasHostBridge = false;
    if (files && files.length > 0) {
        const first = files[0];
        hint = first.path || first.webkitRelativePath || first.name || '';
        try {
            const wv = window.chrome && window.chrome.webview;
            if (wv && typeof wv.postMessageWithAdditionalObjects === 'function') {
                // Hands the real File objects to the WebView2 host, which is the
                // only way to learn their absolute paths. pywebview stores them in
                // the *window* process and ui.drop_zone forwards them to the server.
                wv.postMessageWithAdditionalObjects('FilesDropped', files);
                hasHostBridge = true;
            }
        } catch (err) {
            console.error('FXsonic: failed to forward dropped files to the host', err);
        }
    }
    if (hasHostBridge) {
        // A real path is on its way through the native bridge; the page hint is
        // only a folder name, so sending it would just add noise.
        emit(JSON.stringify({ path: '', native: true }));
    } else {
        emit(JSON.stringify({ path: hint, native: false }));
    }
}""" % DROP_ACTIVE_CLASS

_native_bridge_ready = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _native_state() -> Optional[dict]:
    """Return pywebview's drag & drop state dict, or ``None`` outside pywebview."""
    try:
        from webview.dom import _dnd_state  # type: ignore[import-not-found]
        return _dnd_state
    except Exception:
        return None


def _native_window() -> Any:
    """Return the pywebview window when this process owns it, else ``None``."""
    try:
        import webview  # type: ignore[import-not-found]
        windows = getattr(webview, "windows", None)
        return windows[0] if windows else None
    except Exception:
        return None


def ensure_native_bridge() -> None:
    """Keep pywebview's WebView2 drop bridge armed (idempotent).

    pywebview only records native paths while at least one pywebview DOM ``drop``
    listener is registered; NiceGUI owns its listeners instead, so the counter is
    kept permanently positive.  Must run in the process that hosts the window.
    """
    global _native_bridge_ready
    if _native_bridge_ready:
        return
    _native_bridge_ready = True
    state = _native_state()
    if state is None:
        return
    try:
        if int(state.get("num_listeners") or 0) < 1:
            state["num_listeners"] = 999
    except Exception:
        pass


def _as_directory(candidate: Any) -> Optional[str]:
    """Normalise ``candidate`` to an absolute existing directory.

    Files resolve to the directory that contains them (dropping a single track is
    a natural way of saying "load the folder it lives in").
    """
    if not candidate or not isinstance(candidate, str):
        return None

    raw = unquote(candidate).strip().strip('"').strip()
    if not raw:
        return None

    try:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
    except Exception:
        return None

    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        if path.is_dir():
            return str(path)
        if path.is_file():
            return str(path.parent)
    except OSError:
        return None
    return None


def payload_reports_host_bridge(payload: str) -> bool:
    """True when the page says it handed the drop to the WebView2 host."""
    stripped = (payload or "").strip()
    if not stripped.startswith("{"):
        return False
    try:
        data = json.loads(stripped)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("native"))


def resolve_dropped_folder(payload: str = "") -> Optional[str]:
    """Resolve a *page-supplied* drop payload into an absolute folder path.

    Only used when the page has no WebView2 host bridge (i.e. a plain browser):
    with a host bridge the page reports ``native: true`` and no path at all,
    because the real one travels through :func:`apply_native_entries` instead.

    :param payload: the JSON (or bare path) string emitted by the drop handler
    :return: absolute directory path, or ``None`` when the drop is not usable
    """
    if payload_reports_host_bridge(payload):
        return None

    hint = payload or ""
    stripped = hint.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            hint = str(data.get("path") or "")

    return _as_directory(hint)


def resolve_native_entries(entries: Sequence[Any]) -> Optional[str]:
    """Return the first entry that resolves to an existing directory."""
    for entry in entries or []:
        candidate: Any = None
        if isinstance(entry, dict):
            candidate = entry.get("path")
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            candidate = entry[1]
        elif isinstance(entry, str):
            candidate = entry

        folder = _as_directory(candidate)
        if folder:
            return folder
    return None


def harvest_native_entries(state: Optional[dict]) -> List[dict]:
    """Pop the ``(basename, absolute_path)`` pairs pywebview published.

    Runs in the *window* process, where ``webview.dom._dnd_state['paths']`` is
    actually filled by the WebView2 host.
    """
    entries: List[dict] = []
    if state is None:
        return entries
    while True:
        try:
            item = state["paths"].pop(0)
        except (IndexError, KeyError):
            break
        except Exception:
            break
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
            entries.append({"name": str(item[0] or ""), "path": str(item[1])})
    return entries


# ---------------------------------------------------------------------------
# Server-process side: the live workbenches + the drop endpoint
# ---------------------------------------------------------------------------
_workbenches: List[dict] = []
_workbenches_lock = threading.Lock()


def register_workbench(client: Any, state: Any, on_folder_drop: Callable[[str], Any]) -> None:
    """Remember a live workbench so native drops can be applied to it."""
    unregister_workbench(state)
    with _workbenches_lock:
        _workbenches.append({"client": client, "state": state, "on_folder_drop": on_folder_drop})


def unregister_workbench(state: Any) -> None:
    """Forget a workbench (called when its client disconnects)."""
    with _workbenches_lock:
        _workbenches[:] = [wb for wb in _workbenches if wb["state"] is not state]


def _live_workbenches() -> List[dict]:
    with _workbenches_lock:
        snapshot = list(_workbenches)
    live = []
    for wb in snapshot:
        client = wb.get("client")
        try:
            if client is not None and getattr(client, "is_deleted", False):
                continue
        except Exception:
            pass
        live.append(wb)
    return live


async def _invoke(callback: Callable[[str], Any], folder: str) -> None:
    result = callback(folder)
    if asyncio.iscoroutine(result):
        await result


async def apply_dropped_folder(folder: str) -> int:
    """Load ``folder`` into every live workbench; returns how many were updated."""
    applied = 0
    for wb in _live_workbenches():
        await _invoke(wb["on_folder_drop"], folder)
        applied += 1
    return applied


async def apply_native_entries(entries: Sequence[Any]) -> Optional[str]:
    """Resolve forwarded native entries and stage the first real folder."""
    folder = resolve_native_entries(entries)
    if not folder:
        for wb in _live_workbenches():
            try:
                wb["state"].log(f"DROP IGNORED • no folder found in {list(entries)!r}")
            except Exception:
                pass
        return None
    await apply_dropped_folder(folder)
    return folder


_endpoint_installed = False


def install_native_drop_endpoint(app_instance: Any, route: str = NATIVE_DROP_ROUTE) -> None:
    """Expose ``route`` so the window process can hand over a dropped folder.

    Registered in both processes (only the server's instance is reachable), and
    only once per process.
    """
    global _endpoint_installed
    if _endpoint_installed:
        return
    _endpoint_installed = True

    from fastapi import Request  # local import: keeps this module import-light

    @app_instance.post(route)
    async def _fxsonic_native_drop(request: Request):  # pragma: no cover - wired in main
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        entries = (payload or {}).get("paths") or []
        folder = await apply_native_entries(entries)
        return {"ok": bool(folder), "folder": folder}


# ---------------------------------------------------------------------------
# Window-process side: forward harvested drops to the server
# ---------------------------------------------------------------------------
_resolved_base_url: Optional[str] = None
_forwarder_started = False


def set_server_port(port: Optional[int]) -> None:
    """Remember the port the NiceGUI server listens on.

    ``main.py`` calls this before ``ui.run()`` so the window process (spawned by
    NiceGUI *before* it exports ``NICEGUI_*``) can always reach the server.
    """
    global _server_port
    try:
        if port:
            _server_port = int(port)
    except (TypeError, ValueError):
        pass


def _env_port() -> Optional[str]:
    for name in ("NICEGUI_PORT", "FXSONIC_PORT"):
        value = (os.environ.get(name) or "").strip()
        if value and value != "0":  # 0 means "let NiceGUI pick a free port"
            return value
    return None


def _loopback_base_from_url(url: Any) -> Optional[str]:
    """Turn a window URL into an http://127.0.0.1:port base, else ``None``."""
    if not url:
        return None
    try:
        parsed = urlsplit(str(url))
    except (TypeError, ValueError):
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    host = parsed.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"{parsed.scheme}://{host}:{parsed.port or DEFAULT_SERVER_PORT}"


def server_base_url_candidates() -> List[str]:
    """Candidate URLs of the NiceGUI server, as seen from the window process.

    The environment is *not* a reliable source here: NiceGUI spawns the window
    subprocess inside ``native.activate()``, which runs before it exports
    ``NICEGUI_*``, and ``pywebview.Window`` exposes ``real_url`` (not ``url``).
    ``main.py`` therefore hands the port over explicitly via
    :func:`start_native_drop_forwarder`.
    """
    candidates: List[str] = []

    def _add(url: Optional[str]) -> None:
        if url and url not in candidates:
            candidates.append(url)

    host = os.environ.get("NICEGUI_HOST") or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"

    for port in (_server_port, _env_port()):
        if port:
            _add(f"http://{host}:{port}")

    window = _native_window()
    for attribute in ("real_url", "original_url", "url"):
        _add(_loopback_base_from_url(getattr(window, attribute, None)))

    if not candidates:
        _add(f"http://127.0.0.1:{DEFAULT_SERVER_PORT}")
    return candidates


def post_native_entries(entries: Sequence[dict]) -> bool:
    """POST harvested entries to the server's drop endpoint (window process)."""
    global _resolved_base_url
    bases = ([_resolved_base_url] if _resolved_base_url else []) + [
        base for base in server_base_url_candidates() if base != _resolved_base_url
    ]
    if not bases:
        diag("[FXsonic] native drop: no server address to forward to")
        return False

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        diag(f"[FXsonic] native drop: httpx unavailable ({exc})")
        return False

    for base in bases:
        try:
            response = httpx.post(
                base + NATIVE_DROP_ROUTE,
                json={"paths": list(entries)},
                timeout=POST_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            diag(f"[FXsonic] native drop: {base} unreachable ({type(exc).__name__}: {exc})")
            continue
        if response.status_code != 200:
            diag(f"[FXsonic] native drop: {base} answered {response.status_code}")
            continue
        _resolved_base_url = base
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {}
        return bool(body.get("ok"))
    return False


def collect_new_entries(
    recently: dict,
    state: Optional[dict] = None,
    now: Optional[float] = None,
) -> List[dict]:
    """Harvest pywebview's paths and drop anything already forwarded recently.

    ``recently`` maps ``(name, path)`` -> monotonic timestamp and is pruned in
    place, so a path pywebview re-publishes while we were reading cannot be applied
    twice.
    """
    entries = harvest_native_entries(state if state is not None else _native_state())
    timestamp = time.monotonic() if now is None else now

    fresh: List[dict] = []
    for entry in entries:
        key = (entry["name"], entry["path"])
        if timestamp - recently.get(key, 0.0) < DEDUPE_WINDOW_SECONDS:
            continue
        recently[key] = timestamp
        fresh.append(entry)

    for key, stamp in list(recently.items()):
        if timestamp - stamp > DEDUPE_WINDOW_SECONDS:
            del recently[key]
    return fresh


def will_host_native_window() -> bool:
    """True in the process that will own the pywebview window.

    In a source run that is the spawned child, which does *not* report
    ``MainProcess``.  Frozen into an executable it is different: ``spawn`` skips
    ``init_main_from_path`` when ``sys.frozen`` is set, so the window child never
    re-imports ``main.py`` and instead *is* the process the bootloader started as
    ``__main__`` - where ``current_process().name`` still says ``MainProcess``.
    Its ``--multiprocessing-fork`` argv is what gives it away.
    """
    for argument in sys.argv[1:]:
        if str(argument).startswith("--multiprocessing-fork"):
            return True
    return multiprocessing.current_process().name != "MainProcess"


def start_native_drop_forwarder(enabled: bool = True, port: Optional[int] = None) -> None:
    """Bridge harvested WebView2 drop paths from the window process to the server.

    Only the process that owns the native window can reach pywebview's
    ``_dnd_state``, so this starts a daemon thread there which polls for harvested
    paths and forwards them over localhost HTTP.  No-op in the server process and
    when the app is not running natively.

    :param enabled: set to ``False`` when the app is not running natively
    :param port: the server port, handed over explicitly because NiceGUI spawns the
        window subprocess before it exports ``NICEGUI_*``
    """
    global _forwarder_started
    set_server_port(port)
    if _forwarder_started or not enabled:
        return
    if not will_host_native_window():
        return
    _forwarder_started = True

    def _loop() -> None:
        deadline = time.monotonic() + WINDOW_WAIT_SECONDS
        while _native_window() is None:
            if time.monotonic() >= deadline:
                diag("[FXsonic] native folder bridge gave up waiting for the window")
                return
            time.sleep(0.25)

        ensure_native_bridge()
        bases = server_base_url_candidates()
        diag(
            "[FXsonic] native folder bridge ready (server: "
            + (bases[0] if bases else "unknown")
            + ", log: "
            + str(log_file_path())
            + ")"
        )
        recently: dict = {}

        while True:
            fresh = collect_new_entries(recently)
            if fresh:
                diag(
                    "[FXsonic] folder dropped natively -> "
                    + str([entry["path"] for entry in fresh])
                )
                post_native_entries(fresh)
            time.sleep(FORWARD_POLL_SECONDS)

    threading.Thread(target=_loop, name="fxsonic-native-drop-forwarder", daemon=True).start()


# ---------------------------------------------------------------------------
# Public wiring helper
# ---------------------------------------------------------------------------
def attach_folder_drop_zone(
    element,
    on_drop: Callable[[str], Any],
    *,
    active_class: str = DROP_ACTIVE_CLASS,
) -> Any:
    """Make ``element`` accept a folder dragged out of the OS file manager.

    Drag-over / drag-leave are handled entirely on the client (so hovering feels
    instant and the browser's "open the dropped file" default is suppressed).
    ``drop`` also round-trips to the server, which resolves the folder and hands it
    to ``on_drop`` as an absolute path.  Nothing is invoked when the drop cannot be
    resolved to a real directory.

    :param element: any NiceGUI element; handlers attach to its root DOM node
    :param on_drop: sync or async callback receiving the resolved folder path
    :param active_class: CSS class toggled while a folder hovers the element
    :return: the element, for chaining
    """
    ensure_native_bridge()

    drag_over = _JS_DRAG_OVER
    drag_leave = _JS_DRAG_LEAVE
    drop_js = _JS_DROP
    if active_class != DROP_ACTIVE_CLASS:
        drag_over = drag_over.replace(DROP_ACTIVE_CLASS, active_class)
        drag_leave = drag_leave.replace(DROP_ACTIVE_CLASS, active_class)
        drop_js = drop_js.replace(DROP_ACTIVE_CLASS, active_class)

    async def _on_drop_event(e) -> None:
        args = getattr(e, "args", None)
        payload = ""
        if isinstance(args, (list, tuple)) and args:
            payload = args[0] if isinstance(args[0], str) else ""
        elif isinstance(args, str):
            payload = args

        if payload_reports_host_bridge(payload):
            # The page handed the files to WebView2; the window process owns the
            # real paths and forwards them (see start_native_drop_forwarder).
            diag("[FXsonic] drop received in the page -> waiting for the native "
                 "folder bridge")
            return

        folder = resolve_dropped_folder(payload)
        if folder:
            await _invoke(on_drop, folder)

    element.on("dragenter", js_handler=drag_over)
    element.on("dragover", js_handler=drag_over)
    element.on("dragleave", js_handler=drag_leave)
    element.on("drop", handler=_on_drop_event, js_handler=drop_js)
    return element


__all__ = [
    "DEFAULT_SERVER_PORT",
    "DROP_ACTIVE_CLASS",
    "NATIVE_DROP_ROUTE",
    "apply_dropped_folder",
    "apply_native_entries",
    "attach_folder_drop_zone",
    "collect_new_entries",
    "ensure_native_bridge",
    "harvest_native_entries",
    "install_native_drop_endpoint",
    "payload_reports_host_bridge",
    "post_native_entries",
    "register_workbench",
    "resolve_dropped_folder",
    "resolve_native_entries",
    "server_base_url_candidates",
    "set_server_port",
    "start_native_drop_forwarder",
    "unregister_workbench",
    "will_host_native_window",
]
