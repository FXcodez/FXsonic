"""
Instant abort / cancellation control for FXsonic pipelines.

Scanning, fingerprinting, network lookups and tag writing run on long-lived
background work (``asyncio.to_thread``, worker pools and ``fpcalc`` subprocesses).
A CANCEL / ABORT click must stop all of that *immediately* - not at the end of the
current track - so every stage shares one cooperative token:

  * :class:`AbortController` wraps a ``threading.Event`` (safe to read from the event
    loop thread *and* from worker threads) and keeps a registry of the child
    processes that are currently running, so :meth:`AbortController.abort` can kill
    a live ``fpcalc`` instead of waiting for it to finish.
  * :class:`OperationAborted` is raised by :meth:`AbortController.check` at the
    natural yield points (between items, before each network call) and is caught by
    the pipeline owners (``FXsonicState.process_album`` / ``apply_changes``) to unwind
    cleanly.
  * :func:`bind` / :func:`unbind` publish the token for the *current run* so nested
    helpers that cannot take an extra argument (for example the album consensus
    entry point, whose signature is exercised by the audit harness) still observe
    cancellation through :func:`bound`.

Binding is thread-scoped and identity checked: an older run finishing late can never
disarm a newer run's token.
"""

import threading
from typing import Any, List, Optional

__all__ = [
    "OperationAborted",
    "AbortController",
    "bind",
    "unbind",
    "bound",
    "check",
]


class OperationAborted(RuntimeError):
    """Raised when the running operation was cancelled by the user."""


class AbortController:
    """Cooperative cancellation token shared by every pipeline stage."""

    def __init__(self, name: str = "operation"):
        self.name = name
        self._event = threading.Event()
        # Live child processes (fpcalc etc.) that must die the moment we abort.
        self._processes: List[Any] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    @property
    def is_aborted(self) -> bool:
        return self._event.is_set()

    # Backwards/alternative spelling used across the pipeline.
    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        """Arm a fresh run (called before each scan / apply batch)."""
        self._event.clear()

    def abort(self) -> None:
        """Signal every worker and kill any external tool that is still running."""
        self._event.set()
        self.kill_processes()

    # ------------------------------------------------------------------ checks
    def check(self) -> None:
        """Raise :class:`OperationAborted` when the user asked to stop."""
        if self._event.is_set():
            raise OperationAborted(f"{self.name} aborted by user")

    def raise_if_aborted(self) -> None:
        self.check()

    # --------------------------------------------------------------- children
    def register_process(self, process: Any) -> None:
        """Track ``process`` so :meth:`abort` can terminate it at once."""
        with self._lock:
            self._processes.append(process)
        # Abort may have landed between the spawn and this registration.
        if self._event.is_set():
            _terminate(process)
            self.unregister_process(process)
            raise OperationAborted(f"{self.name} aborted by user")

    def unregister_process(self, process: Any) -> None:
        with self._lock:
            try:
                self._processes.remove(process)
            except ValueError:
                pass

    def kill_processes(self) -> None:
        """Terminate every tracked child process immediately."""
        with self._lock:
            processes = list(self._processes)
            self._processes.clear()
        for process in processes:
            _terminate(process)


def _terminate(process: Any) -> None:
    """Best-effort immediate kill of a ``subprocess.Popen`` instance."""
    try:
        if process.poll() is not None:
            return
    except Exception:
        pass
    for killer in ("kill", "terminate"):
        try:
            getattr(process, killer)()
            return
        except Exception:
            continue


# --------------------------------------------------------------------------- #
# Run-scoped binding
# --------------------------------------------------------------------------- #
_LOCAL = threading.local()


def bind(controller: Optional[AbortController]) -> None:
    """Publish ``controller`` as the active token for the current thread."""
    _LOCAL.controller = controller


def unbind(controller: Optional[AbortController]) -> None:
    """Drop the binding, but only if it is still the caller's own token."""
    if getattr(_LOCAL, "controller", None) is controller:
        _LOCAL.controller = None


def bound() -> Optional[AbortController]:
    """Return the active token for this thread, if any."""
    return getattr(_LOCAL, "controller", None)


def resolve(controller: Optional[AbortController] = None) -> Optional[AbortController]:
    """Return the explicit token when given, else the bound one (may be ``None``)."""
    return controller if controller is not None else bound()


def check(controller: Optional[AbortController] = None) -> None:
    """Raise when the given (or bound) token has been aborted."""
    token = resolve(controller)
    if token is not None:
        token.check()
