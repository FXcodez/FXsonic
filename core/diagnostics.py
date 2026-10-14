"""
Diagnostic logging that survives being frozen into a windowed executable.

A PyInstaller ``--windowed`` build has no console, and Python turns ``print()`` into
a silent no-op when ``sys.stdout`` is ``None`` - which means the messages that make
this app debuggable (pipeline progress, the native drop bridge) would disappear in
the field.  :func:`diag` keeps writing to the console *and* appends to a log file so
a packaged build can still be diagnosed.
"""

import os
import time
from pathlib import Path
from typing import Optional

LOG_FILE_NAME = "fxsonic.log"
_MAX_BYTES = 1_000_000


def log_file_path() -> Optional[Path]:
    """Return the diagnostic log file, creating its folder on first use."""
    try:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        folder = Path(base) / "FXsonic"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / LOG_FILE_NAME
    except Exception:
        return None


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink()
            path.replace(backup)
    except Exception:
        pass


def _append_line(path: Path, text: str) -> None:
    """Append one line with a single ``os.write`` so concurrent processes cannot
    interleave a partial line (the server *and* the native window process log)."""
    try:
        handle = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY)
        try:
            os.write(handle, text.encode("utf-8"))
        finally:
            os.close(handle)
    except Exception:
        pass


def diag(message: str) -> None:
    """Report a diagnostic line to the console (if any) and to the log file."""
    print(message, flush=True)  # silently ignored when there is no console

    path = log_file_path()
    if path is None:
        return
    _rotate(path)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_line(path, f"{stamp} {message}\n")
