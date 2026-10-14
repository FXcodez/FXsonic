"""
PyInstaller packaging for FXsonic.

Builds a **one-directory** bundle (``dist/FXsonic/``) rather than ``--onefile``:
the app runs its native window in a child process, and onefile would re-extract the
whole archive on every window spawn, adding seconds to startup.

Run from the ``App`` folder with the project environment:

    uv run python build.py
    # or: App\\.venv\\Scripts\\python.exe build.py

Output: ``App/dist/FXsonic/FXsonic.exe`` (zipped, that folder is the distributable).

Notes for a packaged build
--------------------------
* ``--windowed`` means there is no console at all: every diagnostic goes to
  ``%LOCALAPPDATA%\\FXsonic\\fxsonic.log`` instead (see ``core/diagnostics.py``).
* The window process is spawned by NiceGUI; PyInstaller's bundled
  ``pyi_rth_multiprocessing`` hook diverts it, and NiceGUI calls
  ``multiprocessing.freeze_support()`` before spawning - no extra code needed.
* PyInstaller hooks for ``webview`` (contrib + pywebview's own), ``pythonnet``,
  ``uvicorn``, ``websockets``, ``anyio`` and ``nicegui`` are auto-discovered from
  their package entry points.
* The target machine needs the Microsoft Edge **WebView2 Runtime** (pre-installed
  on Windows 11; on Windows 10 install the Evergreen Runtime).
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

BASE_DIR = Path(__file__).parent.resolve()
APP_NAME = "FXsonic"
ICON = BASE_DIR / "icons" / "favicon.ico"  # multi-size (16..256) ICO
ENTRY_POINT = BASE_DIR / "main.py"


def build() -> None:
    if not ENTRY_POINT.exists():
        sys.exit(f"entry point not found: {ENTRY_POINT}")
    if not ICON.exists():
        sys.exit(f"icon not found: {ICON}")

    PyInstaller.__main__.run([
        str(ENTRY_POINT),
        f"--name={APP_NAME}",
        "--onedir",
        "--windowed",
        "--clean",
        "--noconfirm",
        f"--icon={ICON}",
        # --- bundled runtime data -------------------------------------------
        # assets/ is served at /assets (logos) and read through sys._MEIPASS;
        # fpcalc.exe is resolved from the same bundle root (core/fingerprint.py).
        f"--add-data={BASE_DIR / 'bin' / 'fpcalc.exe'}{os.pathsep}bin",
        f"--add-data={BASE_DIR / 'assets'}{os.pathsep}assets",
        # --- imports the analyser cannot see --------------------------------
        # NiceGUI has no PyInstaller hook of its own, so collect its data files
        # (static JavaScript/CSS payload) and every element submodule.
        "--collect-all=nicegui",
        "--hidden-import=webview",
        "--hidden-import=clr",
        "--hidden-import=mutagen",
        "--hidden-import=acoustid",
        "--hidden-import=musicbrainzngs",
        "--hidden-import=PIL",
        "--hidden-import=httpx",
        "--hidden-import=socketio",
        "--hidden-import=engineio",
    ])


if __name__ == "__main__":
    build()

