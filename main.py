"""
FXsonic // AUDIO WORKBENCH
Main Entry Point

Theme handling
--------------
``ui.dark_mode()`` drives Quasar's dark plugin, which toggles ``body.body--dark`` /
``body.body--light`` on the page. All FXsonic tokens are scoped to those two body classes
(see ``ui/theme.py``), so every surface, border, badge, chip and button swaps palette the
moment the theme flips - and the header logo is re-bound to the matching SVG asset.
"""

import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Union
from nicegui import ui, app
from nicegui.native import find_open_port

# Ensure local package imports work cleanly
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

# Mount static assets directory for NiceGUI (logos live here)
app.add_static_files("/assets", str(BASE_DIR / "assets"))
app.add_static_files("/icons", str(BASE_DIR / "icons"))

from core.fingerprint import setup_fpcalc_environment
from core.state import FXsonicState
from ui.theme import GLOBAL_CSS, LOGO_URL_DARK, LOGO_URL_LIGHT
from ui.navbar import TopNavbar
from ui.options_bar import OptionsBar
from ui.staging_table import StagingTable
from ui.inspector_panel import InspectorPanel
from ui.status_footer import StatusFooter
from ui.drop_zone import (
    ensure_native_bridge,
    install_native_drop_endpoint,
    register_workbench,
    start_native_drop_forwarder,
    unregister_workbench,
)

# Ensure fpcalc binary is resolved and configured at startup
setup_fpcalc_environment()

# FXSONIC_HEADLESS=1 serves the same UI without spawning the native pywebview
# window (used for automated smoke tests / CI).
HEADLESS = os.environ.get("FXSONIC_HEADLESS", "") not in {"", "0", "false", "False"}

# Port the NiceGUI server binds to. NiceGUI keeps this exact port in native mode.
# A free port is chosen up front (NiceGUI's own packaging guidance) so a packaged
# build still starts when 8080 is taken; FXSONIC_PORT overrides it for tooling.
# The value is exported because the native window runs in a subprocess that NiceGUI
# spawns *before* it exports NICEGUI_*, so the drop bridge there has no other way to
# learn the address.
SERVER_PORT = int(os.environ.get("FXSONIC_PORT") or find_open_port())
os.environ["FXSONIC_PORT"] = str(SERVER_PORT)

# Drag & drop plumbing. The native window and the NiceGUI server run in separate
# processes, so dropped folder paths are armed here and forwarded from the window
# process to the endpoint below.
ensure_native_bridge()
install_native_drop_endpoint(app)
start_native_drop_forwarder(enabled=not HEADLESS, port=SERVER_PORT)

# Both logo variants are pre-loaded (same URLs the <img> uses) so the theme swap
# is instantaneous with no flicker while a new image is fetched.
LOGO_PRELOAD_HTML = (
    f'<link rel="preload" as="image" href="{LOGO_URL_DARK}">'
    f'<link rel="preload" as="image" href="{LOGO_URL_LIGHT}">'
)

# Icon definitions: favicon (<100px) for small representations and app icon (>100px) for larger displays
ICON_HEAD_HTML = (
    '<link rel="icon" type="image/x-icon" href="/icons/app_icon.ico">'
    '<link rel="icon" type="image/png" sizes="16x16" href="/icons/favicon-16x16.png">'
    '<link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32x32.png">'
    '<link rel="icon" type="image/png" sizes="48x48" href="/icons/favicon-48x48.png">'
    '<link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png">'
    '<link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png">'
)


@ui.page("/")
def main_page():
    # Inject global styles & fonts (dark tokens on :root, light on body.body--light)
    ui.add_head_html(f"<style>{GLOBAL_CSS}</style>")
    ui.add_head_html(LOGO_PRELOAD_HTML)
    ui.add_head_html(ICON_HEAD_HTML)

    # Initialize state (dark mode is the FXsonic default)
    state = FXsonicState()

    # Reactive theme controller: bound to the state, owned by Quasar from here on.
    dark = ui.dark_mode(value=state.dark_mode)

    render_workbench(state, dark)


def render_workbench(state: FXsonicState, dark):
    """Build the full workbench shell for ``state``.

    Extracted from the page handler so tooling/tests can render the identical
    shell (light or dark) without duplicating the layout.

    :param state: the FXsonic application state
    :param dark: the ``ui.dark_mode()`` element controlling the active theme
    :return: dict of the instantiated UI components
    """
    components = {
        "navbar": None,
        "options_bar": None,
        "staging_table": None,
        "inspector": None,
        "footer": None,
    }

    # Sync handler
    def refresh_all_ui():
        if components["navbar"]:
            components["navbar"].update_counts()
        if components["options_bar"]:
            components["options_bar"].update_display()
        if components["staging_table"]:
            components["staging_table"].update_display()
        if components["inspector"]:
            components["inspector"].update_display()
        if components["footer"]:
            components["footer"].update_display()

    def refresh_progress_ui():
        """Cheap repaint used by throttled batch progress (the footer counter only).

        APPLY CHANGES writes files in parallel, so the numeric progress counter is all
        that has to move while it runs; re-rendering the staging table for every file
        is what made the batch feel slow (the table is refreshed once, at the end).
        """
        if components["footer"]:
            components["footer"].update_display()

    state.on_state_change = refresh_all_ui
    state.on_progress_change = refresh_progress_ui

    async def handle_scan():
        if state.is_scanning:
            return
        await state.process_album()

    async def handle_apply():
        if state.is_applying:
            return
        await state.apply_changes()

    def handle_cancel():
        state.cancel_task()

    def handle_track_selected(track_id: str):
        if components["inspector"]:
            components["inspector"].update_display()

    async def handle_folder_dropped(paths_or_folder: Any = "", append: bool = False):
        """Load one or more folders/files dropped onto a drop zone.

        ``append=True`` keeps existing tracks and adds new unique files without clearing.
        """
        if not paths_or_folder:
            return

        if isinstance(paths_or_folder, str):
            paths = [paths_or_folder]
        elif isinstance(paths_or_folder, (list, tuple)):
            paths = [str(p) for p in paths_or_folder if p]
        else:
            paths = [str(paths_or_folder)]

        if not paths:
            return

        if not append:
            state.search_filter = ""
            state.status_filter = "ALL"
            state.active_context_filter = None
            if components["staging_table"]:
                if components["staging_table"].search_input:
                    components["staging_table"].search_input.value = ""
                components["staging_table"].reset_filters()

        await state.intake_paths(paths, append=append)

        if components["navbar"] and components["navbar"].dir_input:
            components["navbar"].dir_input.value = state.source_directory

        refresh_all_ui()

    # Prevent default browser window file navigation when dragging & dropping
    ui.add_head_html(
        "<script>window.addEventListener('dragover', (e) => e.preventDefault(), false); "
        "window.addEventListener('drop', (e) => e.preventDefault(), false);</script>"
    )

    # Main Application Frame (1440x940 design viewport, column flex, never scrolls)
    with ui.column().classes(
        "w-full h-screen p-0 m-0 gap-0 no-wrap overflow-hidden"
    ).style(
        "background-color: var(--fx-bg-window); height: 100vh; overflow: hidden;"
    ):
        # 1. Top Navigation Bar (Height: 64px)
        components["navbar"] = TopNavbar(
            state=state,
            dark_mode=dark,
            on_scan=handle_scan,
            on_apply=handle_apply,
            on_cancel=handle_cancel,
            on_folder_drop=handle_folder_dropped,
        )

        # 2. Configuration & Options Bar (Height: 38px)
        components["options_bar"] = OptionsBar(state=state)

        # 3. Main Split - 65% staging table / 35% inspector panel
        with ui.row().classes(
            "w-full flex-grow min-h-0 p-0 m-0 gap-0 no-wrap overflow-hidden"
        ):
            # Left: Main Staging Area (65%)
            with ui.column().classes(
                "fx-staging flex-grow min-w-0 h-full p-0 m-0 gap-0 overflow-hidden"
            ).style("border-right: 1px solid var(--fx-border); background-color: var(--fx-bg-window);"):
                components["staging_table"] = StagingTable(
                    state=state,
                    on_select_track=handle_track_selected,
                )

            # Right: Inspector & Diff Panel (35% -> exactly 504px at the 1440px
            # design width, matching the 504px inspector in both HTML exports)
            with ui.column().classes(
                "fx-inspector h-full p-0 m-0 gap-0 overflow-hidden"
            ).style("flex: 0 0 35%; min-width: 400px; max-width: 504px; background-color: var(--fx-bg-card);"):
                components["inspector"] = InspectorPanel(
                    state=state,
                    on_folder_drop=handle_folder_dropped,
                )

        # 4. Activity Drawer (Height: 43.5px fixed footer, pinned flush to the bottom)
        components["footer"] = StatusFooter(state=state, dark_mode=dark)

    # Native drops are forwarded by the window process to the server endpoint and
    # applied to the registered workbench (see ui/drop_zone.py).
    client = ui.context.client
    register_workbench(client, state, handle_folder_dropped)
    client.on_disconnect(lambda: unregister_workbench(state))

    return components


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="FXsonic",
        favicon=str(BASE_DIR / "icons" / "app_icon.ico"),
        native=not HEADLESS,
        window_size=(1440, 940),
        dark=True,
        show=not HEADLESS,
        port=SERVER_PORT,
        reload=False,
        # Scanning saturates every core with fpcalc processes and tag batches keep the
        # disk busy, so the browser's heartbeat can wobble for a moment.  The default
        # 3 s is tight enough that a busy scan could flash "connection lost"; the heavy
        # work already runs off the event loop (core.fingerprint's worker pool is driven
        # from a thread, and core.state awaits its write pool) and this gives the socket
        # room to survive the remaining CPU spikes.
        reconnect_timeout=60.0,
    )
