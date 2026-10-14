"""
Native OS Folder & File Dialog Helpers
"""

import asyncio
from typing import Optional, Tuple

from .hidden_process import run_hidden

_is_picking_folder = False
_is_picking_file = False


async def choose_directory_dialog(title: str = "Select Folder") -> Optional[str]:
    """
    Opens native folder selection dialog with re-entrancy guard.
    Explicitly treats cancellation as a normal exit without triggering fallback dialogs.
    """
    global _is_picking_folder
    if _is_picking_folder:
        return None
    _is_picking_folder = True
    try:
        # 1. Try pywebview window if available
        try:
            import webview
            if webview.windows and len(webview.windows) > 0:
                window = webview.windows[0]
                result = window.create_file_dialog(webview.FOLDER_DIALOG)
                if result is not None:
                    if len(result) > 0 and result[0]:
                        return result[0]
                    # User cancelled dialog in pywebview - exit immediately without fallback
                    return None
        except Exception:
            pass

        # 2. Try Tkinter filedialog in a background thread
        def _ask_tk() -> Tuple[bool, Optional[str]]:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                folder_path = filedialog.askdirectory(title=title)
                root.destroy()
                return True, (folder_path if folder_path else None)
            except Exception:
                return False, None

        tk_succeeded, folder_path = await asyncio.to_thread(_ask_tk)
        if tk_succeeded:
            # Tkinter ran successfully; return chosen path or None (if cancelled)
            return folder_path

        # 3. Fallback to Windows PowerShell FolderBrowserDialog ONLY if Tkinter failed to launch
        def _ask_powershell() -> Optional[str]:
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$f.Description = '{title}'; "
                "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
            )
            try:
                # run_hidden keeps the PowerShell console from flashing on screen.
                p = run_hidden(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                )
                out = p.stdout.strip()
                return out if out else None
            except Exception:
                return None

        return await asyncio.to_thread(_ask_powershell)
    finally:
        _is_picking_folder = False


async def choose_image_file_dialog(title: str = "Select Artwork Image") -> Optional[str]:
    """
    Opens native file chooser for image replacement (JPEG, PNG, WebP) with re-entrancy guard.
    """
    global _is_picking_file
    if _is_picking_file:
        return None
    _is_picking_file = True
    try:
        def _ask_tk() -> Optional[str]:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                file_path = filedialog.askopenfilename(
                    title=title,
                    filetypes=[
                        ("Image files", "*.jpg;*.jpeg;*.png;*.webp"),
                        ("All files", "*.*"),
                    ],
                )
                root.destroy()
                return file_path if file_path else None
            except Exception:
                return None

        return await asyncio.to_thread(_ask_tk)
    finally:
        _is_picking_file = False
