"""
Spawning external tools without flashing a console window.

FXsonic is a windowed desktop app (and, when frozen, has no console at all).  Every
child process that is console-subsystem - such as the bundled ``fpcalc.exe`` used for
Chromaprint fingerprinting - would otherwise pop up a black console window for as long
as it runs.  Called once per track, that shows up as the app "flashing" while it
searches.

Route every external tool through :func:`run_hidden` / :func:`popen_hidden`:
``CREATE_NO_WINDOW`` stops the console from being created, and a ``STARTUPINFO`` with
``SW_HIDE`` covers tools that open a window of their own.

Cancellable runs
----------------
``fpcalc`` on a long file can take a while, so :func:`run_hidden` also accepts an
:class:`~core.control.AbortController`.  With a token, the child is spawned through
:func:`popen_hidden`, registered with the controller (so CANCEL / ABORT kills it
instantly) and polled until it exits - keeping ``subprocess.run``'s timeout and
``check`` semantics.  Without a token the call is the plain, cheapest path.
"""

import subprocess
import sys
import time
from typing import Any, Optional, Sequence

from .control import AbortController, OperationAborted

IS_WINDOWS = sys.platform == "win32"

#: Keeps a console-subsystem child from creating a console window.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0

#: Value of ``STARTUPINFO.wShowWindow`` that requests an invisible window.
SW_HIDE = 0

#: How often a cancellable child is re-checked for an abort while it runs.
ABORT_POLL_SECONDS = 0.05


def _startup_info() -> Optional[Any]:
    if not IS_WINDOWS:
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return info


def hidden_kwargs(**kwargs: Any) -> dict:
    """Merge the window-suppressing options into ``subprocess`` keyword arguments."""
    merged = dict(kwargs)
    if IS_WINDOWS:
        merged["creationflags"] = merged.get("creationflags", 0) | CREATE_NO_WINDOW
        merged.setdefault("startupinfo", _startup_info())
    # A windowed app may have no usable stdin handle to hand down.
    merged.setdefault("stdin", subprocess.DEVNULL)
    return merged


def run_hidden(
    args: Sequence[str],
    *,
    timeout: Optional[float] = None,
    check: bool = False,
    abort: Optional[AbortController] = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` for external tools, with no window appearing.

    When ``abort`` is supplied the child is killed the moment that token is
    signalled (see :class:`core.control.AbortController`), which is what makes
    CANCEL / ABORT cancel a running ``fpcalc`` instead of waiting for it.
    """
    if abort is None:
        return subprocess.run(list(args), timeout=timeout, check=check, **hidden_kwargs(**kwargs))
    return _run_hidden_cancellable(
        list(args), timeout=timeout, check=check, abort=abort, **kwargs
    )


def _popen_kwargs(kwargs: Any) -> dict:
    """Translate ``subprocess.run`` style options into ``Popen`` options.

    ``capture_output`` and ``text`` only exist on ``run``; the cancellable path
    spawns the child directly, so it maps them onto ``PIPE`` pipes and text mode the
    same way ``subprocess.run`` does.
    """
    popen_kwargs = dict(kwargs)
    capture = popen_kwargs.pop("capture_output", False)
    text = popen_kwargs.pop("text", None)
    if capture:
        popen_kwargs.setdefault("stdout", subprocess.PIPE)
        popen_kwargs.setdefault("stderr", subprocess.PIPE)
    if text is not None:
        popen_kwargs.setdefault("universal_newlines", text)
    return popen_kwargs


def _run_hidden_cancellable(
    args: Sequence[str],
    *,
    timeout: Optional[float],
    check: bool,
    abort: AbortController,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run ``args`` hidden, polling ``abort`` and enforcing ``timeout``."""
    abort.check()
    process = popen_hidden(args, **_popen_kwargs(kwargs))
    # Registers the child so ``abort.abort()`` can kill it; raises if we lost the race.
    abort.register_process(process)

    deadline = time.monotonic() + timeout if timeout else None
    stdout: Any = None
    stderr: Any = None
    try:
        while True:
            slice_timeout = ABORT_POLL_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    stdout, stderr = _drain(process)
                    raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
                slice_timeout = min(slice_timeout, remaining)
            try:
                stdout, stderr = process.communicate(timeout=slice_timeout)
                break
            except subprocess.TimeoutExpired:
                if abort.is_aborted:
                    abort.kill_processes()
                    stdout, stderr = _drain(process)
                    raise OperationAborted("external tool aborted by user")
                # Not aborted and not out of time yet - keep waiting (the partial
                # output read so far is retained by communicate()).
                continue
    finally:
        abort.unregister_process(process)

    if abort.is_aborted:
        raise OperationAborted("external tool aborted by user")

    completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check:
        completed.check_returncode()
    return completed


def _drain(process: subprocess.Popen):
    """Collect whatever a (now dead) child already wrote, never blocking for long."""
    try:
        return process.communicate(timeout=2)
    except Exception:
        return None, None


def popen_hidden(args: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen`` for external tools, with no window appearing."""
    return subprocess.Popen(list(args), **hidden_kwargs(**kwargs))

