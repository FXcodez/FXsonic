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
ICON = BASE_DIR / "icons" / "app_icon.ico"  # multi-size (16..256) ICO
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
        f"--add-data={BASE_DIR / 'icons'}{os.pathsep}icons",
        f"--add-data={BASE_DIR / 'help.html'}{os.pathsep}.",
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


def package_portable(version: str = "0.2.0") -> Path:
    """Create portable standalone ZIP package from dist/FXsonic."""
    import zipfile
    dist_dir = BASE_DIR / "dist"
    app_dir = dist_dir / APP_NAME
    zip_path = dist_dir / f"{APP_NAME}-v{version}-windows-x64.zip"

    if not app_dir.exists():
        sys.exit(f"Cannot package: {app_dir} does not exist.")

    print(f"Creating portable archive: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(app_dir):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(dist_dir)
                zf.write(file_path, arcname=str(rel_path))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Portable archive created successfully: {zip_path.name} ({size_mb:.2f} MB)")
    return zip_path


def compile_installer() -> None:
    """Compile Inno Setup installer package if ISCC is available."""
    import shutil
    import subprocess

    iss_file = BASE_DIR / "installer.iss"
    if not iss_file.exists():
        print(f"Skipping installer: {iss_file} not found.")
        return

    # Look for iscc in PATH and standard Inno Setup installation directories
    candidate_paths = [
        shutil.which("iscc"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    iscc = next((str(p) for p in candidate_paths if p and Path(p).is_file()), None)

    if not iscc:
        print("ISCC.exe not found. Install Inno Setup 6 to compile the Windows Installer.")
        return

    print(f"Compiling Windows Installer using {iscc}...")
    res = subprocess.run([iscc, str(iss_file)], cwd=str(BASE_DIR))
    if res.returncode != 0:
        print(f"ISCC compilation failed with exit code {res.returncode}")
    else:
        print("Windows Installer compiled successfully.")


if __name__ == "__main__":
    build()
    package_portable()
    compile_installer()

