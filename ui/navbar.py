"""
Top Navigation Bar Component

Aligned with the FXsonic v2 HTML exports:
  * 64px tall bar, 18px side padding, 18px gap, card surface background,
    1px bottom border (63.5px + 0.5px in the exports).
  * Brand lockup = dynamic logo (FXsonicD.svg for dark / FXsonicL.svg for light)
    with the "AUDIO WORKBENCH // v0.1.5" subtitle.
  * Outline buttons use the mockup border colour per theme (#4A4A4A dark /
    #1A1A1A light); the primary action stays solid #AA182C.
"""

import asyncio
from typing import Optional, Callable, Any
from pathlib import Path
from nicegui import ui
from core.state import FXsonicState
from core.dialogs import choose_directory_dialog
from ui.drop_zone import attach_folder_drop_zone
from ui.theme import logo_url


class TopNavbar:
    def __init__(
        self,
        state: FXsonicState,
        on_apply: callable,
        on_scan: callable,
        on_cancel: callable,
        dark_mode=None,
        on_folder_drop: Optional[Callable[[str], Any]] = None,
    ):
        self.state = state
        self.on_apply = on_apply
        self.on_scan = on_scan
        self.on_cancel = on_cancel
        self.on_folder_drop = on_folder_drop
        # NiceGUI DarkMode element (ui.dark_mode()) driving body.body--dark/--light
        self.dark_mode_element = dark_mode

        self.dir_input = None
        self.dir_row = None
        self.process_btn = None
        self.apply_btn = None
        self.apply_label = None
        self.logo_img = None
        self.theme_btn = None
        # Tracks what the client is currently showing so repeated notify() calls
        # do not re-push identical props (keeps the logo swap jitter-free).
        self._applied_logo = logo_url(state.dark_mode)
        self._applied_icon = "dark_mode" if state.dark_mode else "light_mode"
        self.render()

    def render(self):
        with ui.row().classes(
            "fx-navbar w-full h-[64px] px-[18px] items-center justify-between no-wrap flex-shrink-0"
        ).style(
            "gap: 18px; background-color: var(--fx-bg-card); border-bottom: 1px solid var(--fx-border);"
        ):
            # Left: Brand Lockup - clicking it toggles the theme
            with ui.column().classes(
                "items-start justify-center gap-[3px] flex-shrink-0 leading-none cursor-pointer"
            ).on("click", self.toggle_theme):
                self.logo_img = ui.image(logo_url(self.state.dark_mode)).classes("fx-logo")

                # Subtitle: AUDIO WORKBENCH // v0.1.5 (Oswald 9.5px / 600 / 0.6px)
                ui.label("AUDIO WORKBENCH // v0.1.5").classes(
                    "font-oswald text-[9.5px] font-semibold tracking-[0.6px] leading-none"
                ).style("color: var(--fx-text-muted);")

            # Center: Directory Browser Input & BROWSE Button
            # This row is drop zone #1 - "the input folder": dropping a source
            # folder anywhere on it loads that folder as the staging source.
            self.dir_row = ui.row().classes("items-center gap-2 flex-grow min-w-0 no-wrap")
            with self.dir_row:
                self.dir_input = ui.input(
                    placeholder="",
                    value=self.state.source_directory,
                    on_change=lambda e: asyncio.create_task(self.on_dir_changed(e.value)),
                ).props("dense outlined").classes("fx-input flex-grow min-w-0").style(
                    "background-color: var(--fx-bg-input);"
                )
                self.dir_input.on("keydown.enter", lambda: asyncio.create_task(self.on_dir_changed(self.dir_input.value)))
                with self.dir_input.add_slot("prepend"):
                    ui.icon("folder", size="14px").style("color: var(--fx-text-muted);")

                ui.button("BROWSE", on_click=self.browse_source, color=None).classes(
                    "fx-btn-outline px-[14px]"
                )

            attach_folder_drop_zone(self.dir_row, self.on_folder_drop or self.handle_folder_dropped)
            self.dir_row.tooltip("Drag & drop a source folder here to load it")

            # Right: Action Group
            with ui.row().classes("items-center gap-2 flex-shrink-0 no-wrap"):
                # Process Album (Consensus-Based Resolution)
                self.process_btn = ui.button(on_click=self.on_scan, color=None).classes(
                    "fx-btn-outline px-[14px] gap-2"
                ).style("gap: 8px;")
                with self.process_btn:
                    ui.icon("album", size="14px").classes("mr-1").style("color: var(--fx-text-primary);")
                    ui.label("PROCESS ALBUM").classes("font-oswald text-[11px] font-semibold tracking-[0.6px]")
                if not self.state.tracks or self.state.is_scanning:
                    self.process_btn.disable()

                # Apply Changes CTA (solid crimson in both themes)
                selected_count = sum(1 for t in self.state.tracks if t.selected)
                self.apply_btn = ui.button(on_click=self.on_apply, color=None).classes(
                    "fx-btn-primary px-4"
                ).style("gap: 7px;")
                with self.apply_btn:
                    ui.icon("check", size="14px").style("color: var(--fx-text-on-accent);")
                    self.apply_label = ui.label(
                        f"APPLY CHANGES ({selected_count} SELECTED)"
                    ).classes("font-oswald text-[11px] font-bold tracking-[0.6px]")

                # Cancel / Abort
                with ui.button(on_click=self.on_cancel, color=None).classes(
                    "fx-btn-ghost-danger px-[13px]"
                ).style("gap: 4px;"):
                    ui.icon("close", size="14px").style("color: var(--fx-crimson);")
                    ui.label("CANCEL / ABORT").classes("font-oswald text-[11px] font-semibold tracking-[0.6px]")

                # Theme Toggle (icon-only, flat)
                self.theme_btn = ui.button(
                    icon="dark_mode" if self.state.dark_mode else "light_mode",
                    on_click=self.toggle_theme,
                    color=None,
                ).props("flat round dense").classes("fx-theme-toggle")

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def toggle_theme(self):
        self.set_theme(not self.state.dark_mode)

    def set_theme(self, is_dark: bool):
        """Flip the active theme and rebind every theme-dependent visual."""
        self.state.dark_mode = bool(is_dark)
        if self.dark_mode_element is not None:
            # Quasar toggles body.body--dark / body.body--light -> all CSS tokens swap
            self.dark_mode_element.set_value(self.state.dark_mode)
        else:
            ui.dark_mode().set_value(self.state.dark_mode)
        self.refresh_theme_visuals()
        self.state.notify()

    def refresh_theme_visuals(self):
        """Swap the logo + toggle affordance without touching the layout box."""
        target_logo = logo_url(self.state.dark_mode)
        if self.logo_img and target_logo != self._applied_logo:
            self.logo_img.set_source(target_logo)
            self._applied_logo = target_logo

        target_icon = "dark_mode" if self.state.dark_mode else "light_mode"
        if self.theme_btn and target_icon != self._applied_icon:
            label = "Switch to light mode" if self.state.dark_mode else "Switch to dark mode"
            self.theme_btn.props(f'icon="{target_icon}"')
            self.theme_btn.props(f'aria-label="{label}"')
            self._applied_icon = target_icon

    # ------------------------------------------------------------------
    # Directory handling
    # ------------------------------------------------------------------
    async def on_dir_changed(self, val: str):
        val = val or ""
        if val == self.state.source_directory and self.state.tracks:
            return
        self.state.source_directory = val
        self.state.search_filter = ""
        self.state.status_filter = "ALL"
        if val and Path(val).is_dir():
            await self.state.intake_directory(val)
        else:
            self.state.tracks.clear()
            self.state.tracks_by_id.clear()
            self.state.selected_track_id = None
            self.state.album_cover_art = None
            self.state.refresh_destination_paths()
            self.state.update_metrics()
            self.state.status_message = "READY"
            self.state.notify()

    async def browse_source(self):
        folder = await choose_directory_dialog("Select Source Audio Folder")
        if folder:
            self.state.source_directory = folder
            self.state.search_filter = ""
            self.state.status_filter = "ALL"
            if self.dir_input:
                self.dir_input.value = folder
            await self.state.intake_directory(folder)

    async def handle_folder_dropped(self, folder_path: str):
        """Fallback handler used when no app-level drop callback was supplied.

        ``folder_path`` has already been resolved into an absolute directory by
        :mod:`ui.drop_zone`, so it only has to be applied to the state here.
        """
        if not folder_path:
            return
        self.state.source_directory = folder_path
        self.state.search_filter = ""
        self.state.status_filter = "ALL"
        if self.dir_input:
            self.dir_input.value = folder_path
        await self.state.intake_directory(folder_path)
        self.state.notify()

    def update_counts(self):
        selected_count = sum(1 for t in self.state.tracks if t.selected)
        if self.apply_label:
            self.apply_label.text = f"APPLY CHANGES ({selected_count} SELECTED)"
        if self.dir_input and self.dir_input.value != self.state.source_directory:
            self.dir_input.value = self.state.source_directory

        has_tracks = len(self.state.tracks) > 0
        if self.process_btn:
            if has_tracks and not self.state.is_scanning:
                self.process_btn.enable()
            else:
                self.process_btn.disable()

        self.refresh_theme_visuals()
