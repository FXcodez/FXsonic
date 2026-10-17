"""
Acoustic Fingerprinting & fpcalc Resolver

``fpcalc`` is CPU/decoder bound and used to run one track at a time, which left every
core but one idle.  FXsonic now runs it through a worker pool
(:func:`fingerprint_tracks_parallel`, ``min(os.cpu_count() or 4, 32)`` workers) and
only decodes the first :data:`FPCALC_ANALYSIS_LENGTH_SECONDS` seconds of each file:
Chromaprint is designed around a short leading window, so the AcoustID match rate is
unchanged while the decode cost drops by roughly 6x on full-length albums.

Every call accepts an :class:`~core.control.AbortController` so CANCEL / ABORT kills a
running ``fpcalc`` subprocess immediately instead of waiting for it to finish.
"""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import acoustid

from .control import AbortController, OperationAborted, resolve as resolve_abort
from .hidden_process import run_hidden
from .cache import get_cached_fingerprint, store_cached_fingerprint

#: Give up on a single fpcalc invocation after this many seconds.
FPCALC_TIMEOUT_SECONDS = 120.0

#: Audio window fed to Chromaprint.  AcoustID's own client defaults to 120 s, which
#: decodes entire files for no accuracy benefit; 20 s is the documented sweet spot and
#: produces the same fingerprint prefix AcoustID matches on.
FPCALC_ANALYSIS_LENGTH_SECONDS = 20

#: Upper bound on parallel fpcalc processes (a pool of 32 already saturates a consumer
#: CPU and its disk; beyond that we would only add swap thrash).
MAX_FPCALC_WORKERS = 32

#: Signature of the optional log sink (``FXsonicState.log``).
LogFn = Optional[Callable[[str], None]]


class FingerprintError(RuntimeError):
    """Raised when fpcalc cannot produce a fingerprint for a file."""


def resolve_fpcalc_binary() -> Path:
    """
    Automated resolver for fpcalc binary:
    1. If running under PyInstaller bundle, check sys._MEIPASS / 'bin' / 'fpcalc.exe'
    2. Check local bundled bin/fpcalc.exe in development
    3. Check system PATH
    """
    # 1. PyInstaller MEIPASS
    if hasattr(sys, "_MEIPASS"):
        meipass_bin = Path(sys._MEIPASS) / "bin" / "fpcalc.exe"
        if meipass_bin.exists():
            return meipass_bin

    # 2. Local development directory
    dev_bin = Path(__file__).resolve().parent.parent / "bin" / "fpcalc.exe"
    if dev_bin.exists():
        return dev_bin

    # 3. System PATH
    which_bin = shutil.which("fpcalc")
    if which_bin:
        return Path(which_bin)

    # Fallback to dev_bin even if not found yet
    return dev_bin


def setup_fpcalc_environment() -> Path:
    """
    Configures acoustid module and environment to use the resolved fpcalc binary.
    """
    fpcalc_path = resolve_fpcalc_binary()
    if fpcalc_path.exists():
        str_path = str(fpcalc_path)
        try:
            acoustid.FPCALC_COMMAND = str_path
        except Exception:
            pass
        os.environ["FPCALC"] = str_path
    return fpcalc_path


def recommended_fpcalc_workers(task_count: int) -> int:
    """How many fpcalc processes to run at once for ``task_count`` files.

    ``min(os.cpu_count() or 4, 32)`` workers, never more than there is work for.
    """
    if task_count <= 0:
        return 1
    return max(1, min(os.cpu_count() or 4, MAX_FPCALC_WORKERS, task_count))


def parse_fpcalc_output(output: str) -> Tuple[float, str]:
    """
    Parse fpcalc's output into ``(duration, fingerprint)``.

    Accepts both the JSON form (``-json``) and the legacy line form
    (``DURATION=..`` / ``FINGERPRINT=..``) so any bundled fpcalc build works.
    """
    text = (output or "").strip()
    if not text:
        raise FingerprintError("fpcalc produced no output")

    if text.startswith("{"):
        try:
            payload: Dict[str, object] = json.loads(text)
        except ValueError as exc:
            raise FingerprintError(f"malformed fpcalc JSON output: {exc}") from exc
        fingerprint = str(payload.get("fingerprint") or "")
        if not fingerprint:
            raise FingerprintError("fpcalc JSON output has no fingerprint")
        try:
            duration = float(payload.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return duration, fingerprint

    fields: Dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip().lower()] = value.strip()

    fingerprint = fields.get("fingerprint", "")
    if not fingerprint:
        raise FingerprintError("malformed fpcalc output (no fingerprint field)")
    try:
        duration = float(fields.get("duration", "0") or 0.0)
    except ValueError:
        duration = 0.0
    return duration, fingerprint


def compute_audio_fingerprint(
    file_path: str,
    max_length: int = FPCALC_ANALYSIS_LENGTH_SECONDS,
    abort: Optional[AbortController] = None,
) -> Tuple[float, str]:
    """
    Computes the Chromaprint fingerprint and duration of ``file_path`` with fpcalc.

    Called directly rather than through ``acoustid.fingerprint_file``: pyacoustid
    spawns fpcalc without ``CREATE_NO_WINDOW``, which pops a console window for every
    fingerprinted track (a visible flash in a windowed desktop build).

    ``max_length`` limits the analysed window to the first ``max_length`` seconds
    (20 s by default instead of AcoustID's 120 s): the prefix fingerprint is what
    AcoustID matches on, so this buys back decode time on long files for free.

    When ``abort`` (or the run-scoped token, see :mod:`core.control`) is signalled the
    fpcalc child is killed instantly and
    :class:`~core.control.OperationAborted` is raised.
    """
    if not file_path:
        raise FingerprintError("no file path given")

    fpcalc = resolve_fpcalc_binary()
    if not fpcalc.exists():
        raise FingerprintError(f"fpcalc binary not found at {fpcalc}")

    token = resolve_abort(abort)
    if token is not None:
        token.check()

    # Check persistent cache first
    path_obj = Path(file_path)
    file_stat = None
    try:
        if path_obj.exists():
            file_stat = path_obj.stat()
            cached = get_cached_fingerprint(str(path_obj.resolve()), file_stat.st_mtime, file_stat.st_size)
            if cached:
                return cached
    except Exception:
        pass

    command = [str(fpcalc), "-json", "-length", str(int(max_length)), str(file_path)]
    run_kwargs: Dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": FPCALC_TIMEOUT_SECONDS,
    }
    # Only handed to run_hidden when a token exists, so the plain call stays exactly
    # the call this used to make.
    if token is not None:
        run_kwargs["abort"] = token

    try:
        completed = run_hidden(command, **run_kwargs)
    except OperationAborted:
        raise
    except subprocess.TimeoutExpired as exc:
        raise FingerprintError(
            f"fpcalc timed out after {FPCALC_TIMEOUT_SECONDS:.0f}s") from exc
    except OSError as exc:
        raise FingerprintError(f"could not start fpcalc: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
        raise FingerprintError(
            f"fpcalc exited with status {completed.returncode}"
            + (f": {detail.splitlines()[0][:200]}" if detail else "")
        )

    duration, fingerprint = parse_fpcalc_output(completed.stdout or "")
    if isinstance(fingerprint, bytes):  # defensive: older tooling returned bytes
        fingerprint = fingerprint.decode("utf-8", errors="replace")

    if file_stat is not None and fingerprint:
        try:
            store_cached_fingerprint(str(path_obj.resolve()), file_stat.st_mtime, file_stat.st_size, duration, fingerprint)
        except Exception:
            pass

    return duration, fingerprint


def fingerprint_tracks_parallel(
    tracks: Iterable[object],
    *,
    max_workers: Optional[int] = None,
    max_length: int = FPCALC_ANALYSIS_LENGTH_SECONDS,
    abort: Optional[AbortController] = None,
    log: LogFn = None,
    on_complete: Optional[Callable[[object], None]] = None,
) -> Dict[str, Optional[Tuple[float, str]]]:
    """Fingerprint many tracks at once with a ``ThreadPoolExecutor``.

    fpcalc runs as a *subprocess*, so a thread pool is the right primitive here: the
    threads only wait on I/O while the OS schedules the decoders across every core.

    Returns ``{track.id: (duration, fingerprint) | None}`` (``None`` = the track could
    not be fingerprinted).  Each success is also stored on the track
    (``track.duration`` / ``track.fingerprint``) so the AcoustID stage can reuse it
    instead of decoding the file a second time.

    ``on_complete(track)`` fires exactly once per track - including tracks whose
    fingerprint was already known - so the caller can drive the progress bar from real
    worker completions.  Workers re-check ``abort`` between tasks and the pool is torn
    down immediately when the user cancels.
    """
    pending: List[object] = [t for t in tracks if getattr(t, "file_path", "")]
    results: Dict[str, Optional[Tuple[float, str]]] = {}
    if not pending:
        return results

    token = resolve_abort(abort)

    # Reuse fingerprints that are already known (a previous scan, or a retry).
    todo: List[object] = []
    for track in pending:
        existing = getattr(track, "fingerprint", None)
        if existing:
            results[getattr(track, "id", "")] = (
                float(getattr(track, "duration", 0.0) or 0.0),
                existing,
            )
            if on_complete is not None:
                on_complete(track)
        else:
            todo.append(track)

    if not todo:
        return results

    def _worker(track: object) -> Optional[Tuple[float, str]]:
        try:
            return compute_audio_fingerprint(
                getattr(track, "file_path", ""), max_length=max_length, abort=token
            )
        except OperationAborted:
            raise
        except Exception as exc:  # one bad file must never stop the batch
            _log(log, f"[Fingerprint] fpcalc failed for {getattr(track, 'file_name', '?')}: {exc}")
            return None

    workers = max_workers or recommended_fpcalc_workers(len(todo))
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fxsonic-fpcalc")
    futures: Dict[Future, object] = {executor.submit(_worker, track): track for track in todo}
    aborted = False
    try:
        outstanding = set(futures)
        while outstanding:
            done, outstanding = wait(outstanding, timeout=0.2, return_when=FIRST_COMPLETED)
            if token is not None and token.is_aborted:
                aborted = True
                break
            for future in done:
                track = futures[future]
                try:
                    outcome = future.result()
                except OperationAborted:
                    aborted = True
                    continue
                except Exception as exc:
                    _log(log, f"[Fingerprint] fpcalc failed for "
                              f"{getattr(track, 'file_name', '?')}: {exc}")
                    outcome = None
                if outcome is not None:
                    duration, fingerprint = outcome
                    try:
                        track.duration = duration
                        track.fingerprint = fingerprint
                    except Exception:
                        pass
                results[getattr(track, "id", "")] = outcome
                if on_complete is not None:
                    on_complete(track)
            if aborted:
                break
    finally:
        if aborted and token is not None:
            # Kill any fpcalc still mid-decode so the worker threads return at once.
            token.kill_processes()
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=True, cancel_futures=aborted)

    if aborted:
        raise OperationAborted("fingerprinting aborted by user")

    return results


def _log(log: LogFn, message: str) -> None:
    """Mirror a batch message to the caller's sink, falling back to stdout."""
    if log is not None:
        try:
            log(message)
            return
        except Exception:
            pass
    print(message, flush=True)
