"""
Main Staging Area (Left Pane - 65% width)

Layout fidelity notes (from FXsonic_v2_Dark_export.html / _Light_export.html):
  * Filter bar: 50px tall (49.5px + 0.5px border), 10px/16px padding, 12px gap,
    background = window surface (not the card surface).
  * Search input: 250x30px, 0 10px padding, 8px gap, 2px radius, 1px border.
  * Filter chips: 28px tall, 0 12px padding, 2px radius, Oswald 10px.
  * Sort button: 28px tall, 0 10px padding, 12px arrow icon.
  * Table header 33.5px / rows 39.5px with a LOCKED pixel column grid so the
    header and every cell stay aligned in both themes.
"""

import os
import re
import sys
import time
import subprocess
from pathlib import Path
from typing import Callable, Optional, List
from nicegui import ui
from nicegui.events import KeyEventArguments
from core.models import AudioTrack, TrackStatus
from core.state import FXsonicState
from core.resolver import clean_track_title
from ui.inspector_panel import show_track_editor_dialog

# ---------------------------------------------------------------------------
# Locked column grid (exact widths from both HTML exports)
# ---------------------------------------------------------------------------
COLUMN_WIDTHS = {
    "select": "28px",
    "status": "128px",
    "file": None,      # flexible column - absorbs the remaining row width
    "artist": "132px",
    "title": "132px",
    "album": "130px",
    "year": "76px",
    "id": "56px",
}

STATUS_BADGE = {
    TrackStatus.VERIFIED: "badge-matched",
    TrackStatus.AMBIGUOUS: "badge-ambiguous",
    TrackStatus.UNMATCHED: "badge-unmatched",
    TrackStatus.STAGED: "badge-staged",
    TrackStatus.UNVERIFIED: "badge-unverified",
}

STATUS_DOT_TOKEN = {
    TrackStatus.VERIFIED: "var(--fx-status-matched-dot)",
    TrackStatus.AMBIGUOUS: "var(--fx-status-ambig-dot)",
    TrackStatus.UNMATCHED: "var(--fx-status-unmatched-dot)",
    TrackStatus.STAGED: "var(--fx-text-muted)",
    TrackStatus.UNVERIFIED: "var(--fx-text-muted)",
}


def _table_cell(column: str, justify: str = "flex-start"):
    """Table cell carrying the locked pixel width for ``column``.

    Header cells and body cells are built with the same helper so a column can
    never drift out of alignment.
    """
    cell = ui.row().classes("fx-cell no-wrap").style(f"justify-content: {justify};")
    width = COLUMN_WIDTHS.get(column)
    if width:
        cell.style(f"width: {width}; flex-shrink: 0;")
    else:
        cell.classes("fx-cell-grow")
    return cell


def _clean_junk_from_text(text: str, search_str: str) -> str:
    if not text or not search_str:
        return text or ""
    raw = search_str.strip()
    core = raw.strip(" -_–—.,~|#[](){}:/\\")
    if not core:
        core = raw

    esc_core = re.escape(core)
    esc_raw = re.escape(raw)

    tokens = [esc_raw, esc_core]
    # If core contains a domain or dot (e.g. masstamil.com or masstamilan.com),
    # also match the domain stem (e.g. masstamil / masstamilan)
    if "." in core:
        domain_stem = core.split(".")[0]
        if len(domain_stem) >= 4:
            esc_stem = re.escape(domain_stem)
            tokens.append(rf"{esc_stem}(?:an)?(?:\.[\w\.-]+)?")

    sep_chars = r"\s\-_–—.,~|#:"
    wrapper_open = r"[\(\[\{]?"
    wrapper_close = r"[\)\]\}]?"

    pattern_parts = []
    for tok in tokens:
        pattern_parts.append(wrapper_open + r"[" + sep_chars + r"]*" + tok + r"[" + sep_chars + r"]*" + wrapper_close)

    regex_str = r"(?i)(?:https?://)?(?:www\.)?(?:" + "|".join(pattern_parts) + r")"
    pattern = re.compile(regex_str)
    cleaned = pattern.sub("", text)
    # Remove empty brackets e.g. (), [], {}
    cleaned = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", "", cleaned)
    # Collapse consecutive spaces
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    # Strip trailing/leading punctuation/separators
    cleaned = cleaned.strip(" -_–—.,~|#:")
    return cleaned


class StagingTable:
    def __init__(
        self,
        state: FXsonicState,
        on_select_track: Callable[[str], None],
    ):
        self.state = state
        self.on_select_track = on_select_track

        self.root_container = None
        self.search_input = None
        self.select_by_dropdown = None
        self.status_dropdown = None
        self.show_all_btn = None
        self.duplicates_btn = None
        self.edit_selected_btn = None
        self.clean_tracks_btn = None
        self.clean_titles_btn = None
        self.table_container = None
        self.keyboard = None
        self.row_elements: dict[str, ui.row] = {}
        self._last_clicked_track_id = None
        self._last_click_time = 0.0
        self._last_dialog_open_time = 0.0

        self.render()

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------
    def render(self):
        ui.add_head_html("""
<script>
window.addEventListener('keydown', (e) => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) {
        const active = document.activeElement;
        const tag = active ? active.tagName.toLowerCase() : '';
        if (['input', 'textarea', 'select'].includes(tag) || active?.closest('.q-dialog') || document.querySelector('.q-menu')) {
            return;
        }
        e.preventDefault();
    }
}, { passive: false });
</script>
""")
        self.keyboard = ui.keyboard(
            on_key=self.handle_key_event,
            active=True,
            ignore=['input', 'select', 'textarea'],
        )
        self.root_container = ui.column().classes("w-full h-full p-0 m-0 gap-0 flex-grow overflow-hidden")
        with self.root_container:
            # A. Filter Bar
            with ui.row().classes(
                "fx-filterbar w-full h-[46px] px-3 items-center justify-between border-b no-wrap flex-shrink-0"
            ).style(
                "gap: 6px; background-color: var(--fx-bg-window); border-bottom: 1px solid var(--fx-border); overflow-x: auto;"
            ):
                # Left: Search & Filter Controls
                with ui.row().classes("items-center no-wrap flex-shrink-0").style("gap: 6px;"):
                    # Search Input (compact 130px)
                    self.search_input = ui.input(
                        placeholder="Filter tracks...",
                        on_change=lambda e: self.on_search(e.value),
                    ).props("dense outlined").classes("fx-input-sm w-[130px] flex-shrink-0").style(
                        "background-color: var(--fx-bg-input);"
                    )
                    self.search_input.on("keydown.escape", lambda: self.clear_search())
                    self.search_input.on("keydown.esc", lambda: self.clear_search())
                    with self.search_input.add_slot("prepend"):
                        ui.icon("search", size="13px").style("color: var(--fx-text-muted);")

                    # Select By Dropdown
                    with ui.row().classes("items-center no-wrap flex-shrink-0").style("gap: 3px;"):
                        ui.label("SELECT BY:").classes("font-oswald text-[10px] font-semibold tracking-[0.4px]").style("color: var(--fx-text-muted);")
                        self.select_by_dropdown = ui.select(
                            options=["None", "Artist", "Album", "Folder", "Status"],
                            value=self.state.select_by_mode,
                            on_change=lambda e: self.on_select_by_changed(e.value),
                        ).props("dense outlined options-dense").classes("w-[88px]").style(
                            "background-color: var(--fx-bg-input); font-size: 11px;"
                        )
                        self.select_by_dropdown.tooltip("When active, selecting a track filters and selects all sibling tracks by that attribute")

                    # Status Filter Dropdown
                    with ui.row().classes("items-center no-wrap flex-shrink-0").style("gap: 3px;"):
                        ui.label("STATUS:").classes("font-oswald text-[10px] font-semibold tracking-[0.4px]").style("color: var(--fx-text-muted);")
                        self.status_dropdown = ui.select(
                            options=["ALL", "VERIFIED", "AMBIGUOUS", "UNMATCHED"],
                            value=self.state.status_filter,
                            on_change=lambda e: self.set_filter(e.value),
                        ).props("dense outlined options-dense").classes("w-[92px]").style(
                            "background-color: var(--fx-bg-input); font-size: 11px;"
                        )

                    # Reset / Show All Button (initially hidden)
                    self.show_all_btn = ui.button(
                        "SHOW ALL",
                        on_click=self.reset_filters,
                        color=None,
                    ).classes("fx-btn-outline px-2 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]").style("height: 26px; color: var(--fx-crimson);")
                    self.show_all_btn.set_visibility(False)
                    self.show_all_btn.tooltip("Clear all filters and show complete library")

                # Spacer so action buttons are pushed to the right
                ui.element("div").classes("flex-grow")

                # Right: Action Buttons Group with unified styling and alignment
                with ui.row().classes("items-center no-wrap flex-shrink-0").style("gap: 6px;"):
                    # Edit Selected Button (Global / Batch Track Metadata Editor)
                    self.edit_selected_btn = ui.button(
                        "EDIT SELECTED",
                        on_click=self.open_edit_selected_dialog,
                        color=None,
                    ).classes(
                        "fx-btn-outline px-2 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 26px; color: var(--fx-text-primary);")
                    self.edit_selected_btn.tooltip("Batch edit metadata for all selected tracks across the stage (or all staged tracks)")
                    if not self.state.tracks:
                        self.edit_selected_btn.disable()

                    # Select Duplicates Button
                    self.duplicates_btn = ui.button(
                        "DUPLICATES",
                        on_click=self.open_duplicates_dialog,
                        color=None,
                    ).classes(
                        "fx-btn-outline px-2 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 26px; color: var(--fx-text-primary);")
                    self.duplicates_btn.tooltip("Scan library for duplicate tracks across albums by fingerprint, metadata, and filename")
                    if not self.state.tracks:
                        self.duplicates_btn.disable()

                    # Clean Tracks Button (Watermark & Tag Junk Remover)
                    self.clean_tracks_btn = ui.button(
                        "CLEAN TRACKS",
                        on_click=self.open_clean_tracks_dialog,
                        color=None,
                    ).classes(
                        "fx-btn-outline px-2 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 26px; color: var(--fx-text-primary);")
                    self.clean_tracks_btn.tooltip("Search and strip promotional watermarks, website URLs, and junk tags across tracks and filenames")
                    if not self.state.tracks:
                        self.clean_tracks_btn.disable()
                    self.clean_titles_btn = self.clean_tracks_btn

            # B. Scrollable table shell (sticky header + rows)
            self.table_container = ui.column().classes(
                "w-full flex-grow min-h-0 overflow-y-auto p-0 m-0 gap-0"
            ).style("background-color: var(--fx-bg-window); scroll-padding-top: 36px; scroll-padding-bottom: 8px;")
            with self.table_container:
                self.render_header()
                self.render_rows()

    # ------------------------------------------------------------------
    # Table header + rows
    # ------------------------------------------------------------------
    def _header_cell_content(self, col_key: str, label_text: str):
        is_active = (self.state.sort_key == col_key)
        arrow = (" ▲" if self.state.sort_ascending else " ▼") if is_active else ""
        with ui.row().classes("items-center no-wrap cursor-pointer select-none").style("gap: 4px;").on(
            "click", lambda _, k=col_key: self.toggle_sort(k)
        ):
            lbl = ui.label(f"{label_text}{arrow}").classes("fx-th cursor-pointer")
            if is_active:
                lbl.style("color: var(--fx-crimson); font-weight: bold;")
            return lbl

    def render_header(self):
        with ui.row().classes(
            "fx-table-header w-full px-4 no-wrap items-center sticky top-0 z-10 flex-shrink-0"
        ):
            with _table_cell("select"):
                all_selected = len(self.state.tracks) > 0 and all(t.selected for t in self.state.tracks)
                ui.checkbox(
                    value=all_selected,
                    on_change=lambda e: self.toggle_all_selection(e.value),
                ).props('dense size="xs"')

            with _table_cell("status"):
                self._header_cell_content("status", "STATUS")
            with _table_cell("file"):
                self._header_cell_content("file_name", "FILE NAME")
            with _table_cell("artist"):
                self._header_cell_content("artist", "ARTIST")
            with _table_cell("title"):
                self._header_cell_content("title", "TITLE")
            with _table_cell("album"):
                self._header_cell_content("album", "ALBUM")
            with _table_cell("year"):
                self._header_cell_content("year", "YEAR / TRACK")
            with _table_cell("id", justify="center"):
                self._header_cell_content("id", "ID")

    def render_status_badge(self, track: AudioTrack):
        score_pct = int(track.proposed.score * 100)
        if track.status in (TrackStatus.STAGED, TrackStatus.UNVERIFIED):
            text = "STAGED" if track.status == TrackStatus.STAGED else "UNVERIFIED"
        elif track.status == TrackStatus.VERIFIED:
            text = f"{score_pct}% MATCH"
        elif track.status == TrackStatus.AMBIGUOUS:
            text = f"{score_pct}% AMBIG"
        else:
            text = "UNMATCHED"

        with ui.element("div").classes(STATUS_BADGE.get(track.status, "badge-unmatched")):
            ui.element("div").classes("dot")
            ui.label(text)

    @staticmethod
    def year_trk_text(track: AudioTrack) -> str:
        """Mockup format: '2016 · #03' (middle dot separator)."""
        year = track.proposed.year or track.current.year or ""
        track_no = track.proposed.track_number or track.current.track_number or ""
        if year and track_no:
            return f"{year} · #{track_no}"
        if year:
            return str(year)
        if track_no:
            return f"#{track_no}"
        return "—"

    def render_rows(self):
        filtered = self.state.get_filtered_tracks()
        self.row_elements.clear()

        if not filtered:
            with ui.column().classes("w-full py-24 items-center justify-center text-center gap-2"):
                ui.icon("library_music", size="42px").style("color: var(--fx-border);")
                ui.label("NO TRACKS STAGED").classes("font-oswald text-xs tracking-wider").style(
                    "color: var(--fx-text-muted);"
                )
                ui.label(
                    "Drag a source folder onto the folder field above or onto the TRACK INFO "
                    "panel to stage it, or use BROWSE."
                ).classes("text-xs font-roboto").style("color: var(--fx-text-muted);")
            return

        for track in filtered:
            is_selected = track.id == self.state.selected_track_id
            row_classes = "fx-table-row w-full px-4 no-wrap items-center" + (
                " row-selected" if is_selected else ""
            )

            row = ui.row().classes(row_classes)
            self.row_elements[track.id] = row
            with row:
                row.on("click", lambda e, t=track: self.handle_row_click(e, t))
                row.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))

                # Checkbox
                with _table_cell("select"):
                    ui.checkbox(
                        value=track.selected,
                        on_change=lambda e, t=track: self.toggle_track_selected(t, e.value),
                    ).props('dense size="xs"')

                # Status badge
                with _table_cell("status"):
                    self.render_status_badge(track)

                # File name (flexible column)
                with _table_cell("file") as cell_file:
                    cell_file.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    file_lbl = ui.label(track.file_name).classes("fx-td fx-td-mono truncate")
                    file_lbl.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    with file_lbl:
                        ui.tooltip(track.file_name)

                # Artist
                with _table_cell("artist") as cell_art:
                    cell_art.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    art_text = track.proposed.artist or track.current.artist or "—"
                    art_lbl = ui.label(art_text).classes("fx-td truncate")
                    art_lbl.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    if art_text != "—":
                        with art_lbl:
                            ui.tooltip(art_text)

                # Title
                with _table_cell("title") as cell_title:
                    cell_title.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    title_text = track.proposed.title or track.current.title or track.file_name
                    title_lbl = ui.label(title_text).classes("fx-td truncate")
                    title_lbl.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    with title_lbl:
                        ui.tooltip(title_text)

                # Album
                with _table_cell("album") as cell_album:
                    cell_album.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    album_text = track.proposed.album or track.current.album or "—"
                    album_lbl = ui.label(album_text).classes("fx-td fx-td-muted truncate")
                    album_lbl.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    if album_text != "—":
                        with album_lbl:
                            ui.tooltip(album_text)

                # Year / Track
                with _table_cell("year") as cell_year:
                    cell_year.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))
                    yr_lbl = ui.label(self.year_trk_text(track)).classes("fx-td-year")
                    yr_lbl.on("dblclick", lambda _, t=track: self.open_track_editor_dialog(t))

                # Fingerprint indicator (tinted by status in both themes)
                with _table_cell("id", justify="center"):
                    has_fp = bool(track.fingerprint)
                    ui.icon("graphic_eq" if has_fp else "music_off", size="16px").style(
                        f"color: {STATUS_DOT_TOKEN.get(track.status, 'var(--fx-text-muted)')};"
                    )

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------
    def on_search(self, val: str):
        new_val = val or ""
        if self.state.search_filter == new_val:
            return
        self.state.search_filter = new_val
        self.update_display()

    def clear_search(self):
        """Clears the search input on Escape and resets table filtering."""
        self.state.search_filter = ""
        if self.search_input and self.search_input.value != "":
            self.search_input.set_value("")
        self.update_display()

    def apply_context_for_track(self, track: AudioTrack, mode: str):
        if not track or mode == "None":
            self.state.active_context_filter = None
            return

        val = ""
        if mode == "Artist":
            val = (track.proposed.artist or track.current.artist or "").strip()
            if val:
                self.state.active_context_filter = val
                for t in self.state.tracks:
                    t.selected = bool((t.proposed.artist or t.current.artist or "").strip().lower() == val.lower())
        elif mode == "Album":
            val = (track.proposed.album or track.current.album or "").strip()
            if val:
                self.state.active_context_filter = val
                for t in self.state.tracks:
                    t.selected = bool((t.proposed.album or t.current.album or "").strip().lower() == val.lower())
        elif mode == "Folder":
            val = str(Path(track.file_path).parent)
            self.state.active_context_filter = val
            for t in self.state.tracks:
                t.selected = bool(str(Path(t.file_path).parent).lower() == val.lower())
        elif mode == "Status":
            val = track.status.value
            self.state.active_context_filter = val
            for t in self.state.tracks:
                t.selected = bool(t.status.value == val)

    def reset_filters(self):
        """Resets search filter, contextual filter, category filter, and Select By mode back to default ALL view."""
        self.state.search_filter = ""
        self.state.status_filter = "ALL"
        self.state.active_context_filter = None
        self.state.select_by_mode = "None"
        if self.select_by_dropdown:
            self.select_by_dropdown.value = "None"
        if self.status_dropdown and self.status_dropdown.options:
            self.status_dropdown.value = self.status_dropdown.options[0]
        if self.search_input and self.search_input.value != "":
            self.search_input.set_value("")
        self.update_display()
        self.state.notify()

    def set_filter(self, filter_name: str):
        raw = str(filter_name or "ALL")
        clean_name = raw.split()[0].strip() if "(" in raw else raw.strip()
        self.state.status_filter = clean_name
        self.update_display()

    def on_select_by_changed(self, val: str):
        mode = val or "None"
        self.state.select_by_mode = mode
        if mode == "None":
            self.state.active_context_filter = None
        else:
            # Immediately filter & select based on the currently selected track (or first loaded track)
            active_track = None
            if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
                active_track = self.state.tracks_by_id[self.state.selected_track_id]
            elif self.state.tracks:
                active_track = self.state.tracks[0]
                self.state.selected_track_id = active_track.id

            if active_track:
                self.apply_context_for_track(active_track, mode)
                self.on_select_track(active_track.id)

        self.update_display()
        self.state.notify()

    def toggle_sort(self, key: str):
        if self.state.sort_key == key:
            self.state.sort_ascending = not self.state.sort_ascending
        else:
            self.state.sort_key = key
            self.state.sort_ascending = True
        self.update_display()

    def open_clean_tracks_dialog(self):
        """Opens modal dialog to search and strip promotional watermarks, website URLs, and junk text."""
        if not self.state.tracks:
            ui.notify("No tracks staged to clean.", color="warning")
            return

        selected_tracks = [t for t in self.state.tracks if t.selected]
        has_selection = len(selected_tracks) > 0
        total_tracks = len(self.state.tracks)

        active_track = None
        if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
            active_track = self.state.tracks_by_id[self.state.selected_track_id]
        elif selected_tracks:
            active_track = selected_tracks[0]
        elif self.state.tracks:
            active_track = self.state.tracks[0]

        album_tracks = self.state.get_album_tracks_for(active_track) if active_track else []

        with ui.dialog() as dialog, ui.card().classes("p-5 gap-3").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); "
            "min-width: 480px; max-width: 540px; border-radius: 4px;"
        ):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("cleaning_services", size="20px").style("color: var(--fx-crimson);")
                with ui.column().classes("gap-0.5"):
                    ui.label("CLEAN TRACKS • WATERMARK STRIPPER").classes(
                        "font-oswald text-[13px] font-bold tracking-[0.6px]"
                    ).style("color: var(--fx-text-primary);")
                    ui.label("Search and remove promotional watermarks, website URLs, and junk tags").classes(
                        "font-roboto text-[11px]"
                    ).style("color: var(--fx-text-muted);")

            with ui.column().classes("w-full gap-2.5 my-2"):
                ui.label("TEXT OR PATTERN TO REMOVE").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                search_input = ui.input(
                    placeholder="e.g. - masstamil.com, [SongsPK], (320kbps)..."
                ).props("dense outlined autofocus").classes("w-full fx-dialog-input").style(
                    "background-color: var(--fx-bg-input);"
                )
                with search_input.add_slot("append"):
                    ui.icon("close", size="14px").classes("cursor-pointer").style(
                        "color: var(--fx-text-muted);"
                    ).on("click", lambda: search_input.set_value("")).tooltip("Clear input")

                # Target scope
                ui.label("TARGET SCOPE").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px] mt-1"
                ).style("color: var(--fx-text-muted);")

                opt_all = f"All Staged Tracks ({total_tracks})"
                scope_options = [opt_all]
                if album_tracks and len(album_tracks) < total_tracks:
                    opt_album = f"Current Album Tracks ({len(album_tracks)})"
                    scope_options.append(opt_album)
                else:
                    opt_album = None

                if has_selection:
                    opt_sel = f"Selected Tracks Only ({len(selected_tracks)})"
                    scope_options.insert(0, opt_sel)
                    default_scope = opt_sel
                elif opt_album:
                    default_scope = opt_album
                else:
                    default_scope = opt_all

                scope_radio = ui.radio(
                    scope_options,
                    value=default_scope,
                ).props("dense").classes("text-xs font-roboto")

                # Formatting options
                format_checkbox = ui.checkbox(
                    "Also format title capitalization (Smart Title Case)",
                    value=True,
                ).props("dense size=xs").classes("text-xs font-roboto mt-1")

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("CANCEL", on_click=dialog.close, color=None).classes(
                    "fx-btn-outline px-[14px]"
                ).style("height: 30px;")

                def do_clean():
                    search_str = (search_input.value or "").strip()
                    apply_title_case = format_checkbox.value

                    if not search_str and not apply_title_case:
                        ui.notify("Please enter text to remove or enable title case formatting.", color="warning")
                        return

                    scope_val = scope_radio.value
                    if "Selected Tracks" in scope_val:
                        targets = selected_tracks
                    elif "Current Album" in scope_val and album_tracks:
                        targets = album_tracks
                    else:
                        targets = self.state.tracks

                    count_cleaned = 0
                    for t in targets:
                        changed = False
                        if search_str:
                            for attr in ("title", "artist", "album", "album_artist", "genre", "year"):
                                # 1. Clean proposed metadata
                                prop_val = getattr(t.proposed, attr, "") or ""
                                if prop_val:
                                    c_prop = _clean_junk_from_text(prop_val, search_str)
                                    if c_prop != prop_val:
                                        setattr(t.proposed, attr, c_prop)
                                        changed = True

                                # 2. Clean current metadata so inspection diff and fallbacks don't retain junk
                                curr_val = getattr(t.current, attr, "") or ""
                                if curr_val:
                                    c_curr = _clean_junk_from_text(curr_val, search_str)
                                    if c_curr != curr_val:
                                        setattr(t.current, attr, c_curr)
                                        changed = True

                            # 3. Clean filename display stem
                            fn_p = Path(t.file_name)
                            c_fn_stem = _clean_junk_from_text(fn_p.stem, search_str)
                            if c_fn_stem and c_fn_stem != fn_p.stem:
                                t.file_name = f"{c_fn_stem}{fn_p.suffix}"
                                changed = True

                            # 4. Clean artwork_info
                            if t.proposed.artwork_info:
                                c_art = _clean_junk_from_text(t.proposed.artwork_info, search_str)
                                if c_art != t.proposed.artwork_info:
                                    t.proposed.artwork_info = c_art
                                    changed = True

                            # 5. Clean junk_frames
                            if t.current.junk_frames:
                                new_junk = []
                                for jf in t.current.junk_frames:
                                    c_jf = _clean_junk_from_text(jf, search_str)
                                    if c_jf and c_jf != jf:
                                        new_junk.append(c_jf)
                                        changed = True
                                    elif not c_jf:
                                        changed = True
                                    else:
                                        new_junk.append(jf)
                                t.current.junk_frames = new_junk

                        if apply_title_case:
                            raw_title = t.proposed.title or t.current.title or Path(t.file_name).stem
                            raw_album = t.proposed.album or t.current.album or ""
                            cleaned_title = clean_track_title(raw_title, raw_album)
                            if cleaned_title != t.proposed.title:
                                t.proposed.title = cleaned_title
                                changed = True
                            if cleaned_title != t.current.title:
                                t.current.title = cleaned_title
                                changed = True

                        if changed:
                            count_cleaned += 1

                    self.state.refresh_destination_paths()
                    # Also strip junk from target_path filename if rename_to_title was off
                    if search_str:
                        for t in targets:
                            if t.target_path:
                                tp = Path(t.target_path)
                                c_stem = _clean_junk_from_text(tp.stem, search_str)
                                if c_stem and c_stem != tp.stem:
                                    t.target_path = str(tp.with_name(f"{c_stem}{tp.suffix}"))

                    self.state.update_metrics()
                    dialog.close()
                    self.update_display()
                    self.state.notify()
                    ui.notify(f"Cleaned watermark & junk tags for {count_cleaned} track(s).", color="positive")

                ui.button("CLEAN TRACKS", on_click=do_clean, color=None).classes(
                    "fx-btn-primary px-[14px]"
                ).style("height: 30px;")

        dialog.open()

    def clean_track_titles(self):
        """Strips leading track numbers, trailing album tags, and applies Smart Title Case."""
        if not self.state.tracks:
            ui.notify("No tracks staged to clean.", color="warning")
            return
        selected = [t for t in self.state.tracks if t.selected]
        targets = selected if selected else self.state.tracks
        for t in targets:
            raw_title = t.proposed.title or t.current.title or Path(t.file_name).stem
            raw_album = t.proposed.album or t.current.album or ""
            t.proposed.title = clean_track_title(raw_title, raw_album)
        self.state.refresh_destination_paths()
        self.update_display()
        self.state.notify()
        ui.notify(f"Cleaned track titles for {len(targets)} track(s).", color="positive")

    def toggle_all_selection(self, selected: bool):
        for t in self.state.tracks:
            t.selected = bool(selected)
        self.update_display()
        self.state.notify()

    def toggle_track_selected(self, track: AudioTrack, val: bool):
        track.selected = bool(val)
        self.state.notify()

    def handle_row_click(self, event, track: AudioTrack):
        args = getattr(event, "args", {}) or {}
        ctrl = False
        shift = False
        if isinstance(args, dict):
            ctrl = bool(args.get("ctrlKey") or args.get("metaKey"))
            shift = bool(args.get("shiftKey"))

        # Double-click software detection (triggers edit popup on rapid click on same track)
        now = time.monotonic()
        is_double_click = (
            not ctrl
            and not shift
            and self._last_clicked_track_id == track.id
            and (now - getattr(self, "_last_click_time", 0.0)) < 0.45
        )
        self._last_click_time = now

        if is_double_click:
            self._last_click_time = 0.0
            self.open_track_editor_dialog(track)
            return

        # Contextual selection when "Select By" is enabled
        if self.state.select_by_mode != "None" and not ctrl and not shift:
            self.apply_context_for_track(track, self.state.select_by_mode)
            self._last_clicked_track_id = track.id
            self.select_track(track.id)
            self.update_display()
            self.state.notify()
            return

        if ctrl:
            track.selected = not track.selected
        elif shift and self._last_clicked_track_id:
            ids = [t.id for t in self.state.tracks]
            if self._last_clicked_track_id in ids and track.id in ids:
                i1 = ids.index(self._last_clicked_track_id)
                i2 = ids.index(track.id)
                start, end = min(i1, i2), max(i1, i2)
                for idx in range(start, end + 1):
                    self.state.tracks[idx].selected = True

        self._last_clicked_track_id = track.id
        self.select_track(track.id)

        # Only update display / notify when multiselection changed!
        if ctrl or shift:
            self.update_display()
            self.state.notify()

    def handle_key_event(self, e: KeyEventArguments):
        if not e.action.keydown:
            return
        if not (e.key.arrow_up or e.key.arrow_down or getattr(e.key, "page_up", False) or getattr(e.key, "page_down", False) or getattr(e.key, "home", False) or getattr(e.key, "end", False)):
            return

        # Do not navigate tracks if a modal dialog is currently open
        try:
            client = ui.context.client
            if client and any(isinstance(el, ui.dialog) and el.value for el in client.elements.values()):
                return
        except Exception:
            pass

        filtered_tracks = self.state.get_filtered_tracks()
        if not filtered_tracks:
            return

        track_ids = [t.id for t in filtered_tracks]
        current_id = self.state.selected_track_id
        curr_idx = track_ids.index(current_id) if current_id in track_ids else -1

        if e.key.arrow_up:
            target_idx = len(filtered_tracks) - 1 if curr_idx == -1 else max(0, curr_idx - 1)
        elif e.key.arrow_down:
            target_idx = 0 if curr_idx == -1 else min(len(filtered_tracks) - 1, curr_idx + 1)
        elif getattr(e.key, "page_up", False):
            target_idx = max(0, curr_idx - 10) if curr_idx != -1 else 0
        elif getattr(e.key, "page_down", False):
            target_idx = min(len(filtered_tracks) - 1, curr_idx + 10) if curr_idx != -1 else len(filtered_tracks) - 1
        elif getattr(e.key, "home", False):
            target_idx = 0
        elif getattr(e.key, "end", False):
            target_idx = len(filtered_tracks) - 1
        else:
            return

        target_track = filtered_tracks[target_idx]
        self._last_clicked_track_id = target_track.id
        self.select_track(target_track.id, scroll=True)

        if e.modifiers.shift:
            target_track.selected = True
            self.state.notify()

    def select_track(self, track_id: str, scroll: bool = False):
        prev_id = self.state.selected_track_id
        self.state.selected_track_id = track_id
        if prev_id and prev_id != track_id and prev_id in self.row_elements:
            self.row_elements[prev_id].classes(remove="row-selected")
        if track_id in self.row_elements:
            row = self.row_elements[track_id]
            row.classes(add="row-selected")
            if scroll:
                try:
                    row.run_method("scrollIntoView", {"block": "nearest"})
                except Exception:
                    pass
        self.on_select_track(track_id)

    def open_track_editor_dialog(self, track: AudioTrack):
        """Opens modal dialog for editing metadata of a single track."""
        now = time.monotonic()
        if now - getattr(self, "_last_dialog_open_time", 0.0) < 0.4:
            return
        self._last_dialog_open_time = now
        show_track_editor_dialog(
            track=track,
            state=self.state,
            on_done=lambda: (self.update_display(), self.state.notify()),
        )

    def play_track(self, file_path: str):
        """Launches audio file in default OS media player."""
        if not file_path or not Path(file_path).exists():
            return
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", file_path])
            else:
                subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            print(f"Error launching media player for {file_path}: {e}")

    def open_edit_selected_dialog(self):
        """Opens modal dialog for batch editing metadata across selected tracks (or all staged tracks)."""
        now = time.monotonic()
        if now - getattr(self, "_last_dialog_open_time", 0.0) < 0.4:
            return
        self._last_dialog_open_time = now

        if not self.state.tracks:
            ui.notify("No tracks staged to edit.", color="warning")
            return

        selected_tracks = [t for t in self.state.tracks if t.selected]
        has_selection = len(selected_tracks) > 0
        total_tracks = len(self.state.tracks)

        active_track = None
        if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
            active_track = self.state.tracks_by_id[self.state.selected_track_id]
        elif selected_tracks:
            active_track = selected_tracks[0]
        elif self.state.tracks:
            active_track = self.state.tracks[0]

        initial_album = (active_track.proposed.album or active_track.current.album or "") if active_track else ""
        initial_album_artist = (active_track.proposed.album_artist or active_track.current.album_artist or "") if active_track else ""
        initial_artist = (active_track.proposed.artist or active_track.current.artist or "") if active_track else ""
        initial_year = (active_track.proposed.year or active_track.current.year or "") if active_track else ""
        initial_genre = (active_track.proposed.genre or active_track.current.genre or "") if active_track else ""

        with ui.dialog() as dialog, ui.card().classes("p-5 gap-3").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); "
            "min-width: 480px; max-width: 540px; border-radius: 4px;"
        ):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("edit_note", size="20px").style("color: var(--fx-crimson);")
                    with ui.column().classes("gap-0.5"):
                        ui.label("EDIT SELECTED TRACKS").classes(
                            "font-oswald text-[13px] font-bold tracking-[0.6px]"
                        ).style("color: var(--fx-text-primary);")
                        sub_text = (
                            f"Global batch edit • {len(selected_tracks)} selected of {total_tracks} staged"
                            if has_selection
                            else f"Global batch edit • All {total_tracks} staged tracks"
                        )
                        ui.label(sub_text).classes(
                            "font-roboto text-[11px] truncate max-w-[280px]"
                        ).style("color: var(--fx-text-muted);")
                ui.button(
                    "CLEAR ALL FIELDS",
                    on_click=lambda: clear_all_fields(),
                    color=None,
                ).classes("fx-btn-outline px-2 text-[10px]").style("height: 24px;").tooltip("Clear all fields to retain original track metadata")

            def clear_all_fields():
                album_input.set_value("")
                album_artist_input.set_value("")
                artist_input.set_value("")
                year_input.set_value("")
                genre_input.set_value("")

            with ui.column().classes("w-full gap-2.5 my-2"):
                # Field 1: Album Title
                with ui.column().classes("w-full gap-1"):
                    ui.label("ALBUM TITLE").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    album_input = ui.input(
                        value=initial_album,
                        placeholder="Enter album title (leave blank to keep original track info)..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )
                    with album_input.add_slot("append"):
                        ui.icon("close", size="14px").classes("cursor-pointer").style(
                            "color: var(--fx-text-muted);"
                        ).on("click", lambda: album_input.set_value("")).tooltip("Clear to keep original track info")

                # Field 2: Album Artist
                with ui.column().classes("w-full gap-1"):
                    ui.label("ALBUM ARTIST").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    album_artist_input = ui.input(
                        value=initial_album_artist,
                        placeholder="Enter album artist (leave blank to keep original track info)..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )
                    with album_artist_input.add_slot("append"):
                        ui.icon("close", size="14px").classes("cursor-pointer").style(
                            "color: var(--fx-text-muted);"
                        ).on("click", lambda: album_artist_input.set_value("")).tooltip("Clear to keep original track info")

                # Field 3: Track Artist
                with ui.column().classes("w-full gap-1"):
                    ui.label("TRACK ARTIST").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    artist_input = ui.input(
                        value=initial_artist,
                        placeholder="Enter artist for tracks (leave blank to keep original track info)..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )
                    with artist_input.add_slot("append"):
                        ui.icon("close", size="14px").classes("cursor-pointer").style(
                            "color: var(--fx-text-muted);"
                        ).on("click", lambda: artist_input.set_value("")).tooltip("Clear to keep original track info")

                # Row with Year & Genre
                with ui.row().classes("w-full gap-3 no-wrap"):
                    with ui.column().classes("flex-1 gap-1"):
                        ui.label("YEAR").classes(
                            "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                        ).style("color: var(--fx-text-muted);")
                        year_input = ui.input(
                            value=initial_year,
                            placeholder="YYYY"
                        ).props("dense outlined").classes("w-full fx-dialog-input").style(
                            "background-color: var(--fx-bg-input);"
                        )
                        with year_input.add_slot("append"):
                            ui.icon("close", size="14px").classes("cursor-pointer").style(
                                "color: var(--fx-text-muted);"
                            ).on("click", lambda: year_input.set_value("")).tooltip("Clear to keep original track info")

                    with ui.column().classes("flex-1 gap-1"):
                        ui.label("GENRE").classes(
                            "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                        ).style("color: var(--fx-text-muted);")
                        genre_input = ui.input(
                            value=initial_genre,
                            placeholder="e.g. Soundtrack, Pop..."
                        ).props("dense outlined").classes("w-full fx-dialog-input").style(
                            "background-color: var(--fx-bg-input);"
                        )
                        with genre_input.add_slot("append"):
                            ui.icon("close", size="14px").classes("cursor-pointer").style(
                                "color: var(--fx-text-muted);"
                            ).on("click", lambda: genre_input.set_value("")).tooltip("Clear to keep original track info")

            # Target Scope
            ui.label("TARGET SCOPE").classes(
                "font-oswald text-[10px] font-semibold tracking-[0.5px] mt-1"
            ).style("color: var(--fx-text-muted);")

            opt_sel = f"Selected Tracks Only ({len(selected_tracks)})"
            opt_all = f"All Staged Tracks ({total_tracks})"
            if has_selection:
                scope_options = [opt_sel, opt_all]
                default_scope = opt_sel
            else:
                scope_options = [opt_all]
                default_scope = opt_all

            scope_radio = ui.radio(
                scope_options,
                value=default_scope,
            ).props("dense").classes("text-xs font-roboto")

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("CANCEL", on_click=dialog.close, color=None).classes(
                    "fx-btn-outline px-[14px]"
                ).style("height: 30px;")

                def apply_batch():
                    scope = scope_radio.value
                    if scope.startswith("Selected Tracks"):
                        targets = [t for t in self.state.tracks if t.selected]
                        if not targets:
                            targets = list(self.state.tracks)
                    else:
                        targets = list(self.state.tracks)

                    new_album = album_input.value.strip() if album_input.value else ""
                    new_album_artist = album_artist_input.value.strip() if album_artist_input.value else ""
                    new_artist = artist_input.value.strip() if artist_input.value else ""
                    new_year = year_input.value.strip() if year_input.value else ""
                    new_genre = genre_input.value.strip() if genre_input.value else ""

                    for t in targets:
                        if new_album:
                            t.proposed.album = new_album
                        if new_album_artist:
                            t.proposed.album_artist = new_album_artist
                        if new_artist:
                            t.proposed.artist = new_artist
                        if new_year:
                            t.proposed.year = new_year
                        if new_genre:
                            t.proposed.genre = new_genre

                    self.state.refresh_destination_paths()
                    self.state.update_metrics()
                    dialog.close()
                    self.update_display()
                    self.state.notify()
                    ui.notify(f"Updated metadata for {len(targets)} track(s).", color="positive")

                ui.button("APPLY CHANGES", on_click=apply_batch, color=None).classes(
                    "fx-btn-primary px-[14px]"
                ).style("height: 30px;")

        dialog.open()

    def open_album_editor_dialog(self):
        """Backwards-compatibility alias for open_edit_selected_dialog."""
        return self.open_edit_selected_dialog()

    def open_duplicates_dialog(self):
        """Opens modal dialog displaying detected duplicate tracks with unstage/merge actions."""
        groups = self.state.detect_duplicates()
        if not groups:
            ui.notify("No duplicate tracks detected in staging list.", color="positive")
            return

        total_dups = sum(len(g) - 1 for g in groups)
        dup_track_ids = [t.id for g in groups for t in g[1:]]

        # Suggest default target album from the first primary track
        initial_album = ""
        for g in groups:
            if g[0].proposed.album or g[0].current.album:
                initial_album = g[0].proposed.album or g[0].current.album
                break
        if not initial_album and self.state.tracks:
            for t in self.state.tracks:
                if t.proposed.album or t.current.album:
                    initial_album = t.proposed.album or t.current.album
                    break

        with ui.dialog() as dlg, ui.card().classes("p-5 gap-3 min-w-[540px] max-w-[620px]").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); border-radius: 4px;"
        ):
            with ui.row().classes("items-center gap-2"):
                ui.icon("content_copy", size="20px").style("color: var(--fx-crimson);")
                ui.label(f"DUPLICATE TRACKS DETECTED ({total_dups})").classes(
                    "font-oswald text-sm font-bold tracking-wide"
                ).style("color: var(--fx-text-primary);")

            ui.label(
                f"Found {total_dups} duplicate tracks across {len(groups)} distinct song groups based on audio fingerprints, metadata, and filenames. "
                "The highest quality / primary version of each song has been selected to keep."
            ).classes("text-xs font-roboto leading-relaxed").style("color: var(--fx-text-muted);")

            # Duplicate items preview list
            with ui.column().classes("w-full max-h-[200px] overflow-y-auto p-2 border rounded gap-2").style(
                "background-color: var(--fx-bg-input); border-color: var(--fx-border);"
            ):
                for idx, g in enumerate(groups[:15]):
                    primary = g[0]
                    p_title = primary.proposed.title or primary.current.title or primary.file_name
                    p_art = primary.proposed.artist or primary.current.artist or "—"
                    p_folder = Path(primary.file_path).parent.name
                    p_size = f"{primary.file_size / (1024*1024):.1f}MB" if primary.file_size else ""

                    with ui.column().classes("w-full p-2 border rounded gap-1").style(
                        "background-color: var(--fx-bg-window); border-color: var(--fx-border);"
                    ):
                        with ui.row().classes("items-center justify-between w-full no-wrap"):
                            ui.label(f"{idx+1}. {p_art} - {p_title}").classes("font-oswald text-[11px] font-bold truncate").style("color: var(--fx-text-primary);")
                            ui.label(f"{len(g)} copies").classes("text-[9px] font-mono").style("color: var(--fx-text-muted);")

                        # Primary track to keep
                        with ui.row().classes("items-center gap-1.5 no-wrap pl-1"):
                            ui.label("[KEEP]").classes("font-mono text-[9px] font-bold").style("color: var(--fx-status-verified-dot);")
                            ui.label(f"{primary.file_name} ({p_folder}) {p_size}").classes("text-[10px] truncate").style("color: var(--fx-text-muted);")

                        # Secondary duplicates to discard
                        for sec in g[1:]:
                            s_folder = Path(sec.file_path).parent.name
                            s_size = f"{sec.file_size / (1024*1024):.1f}MB" if sec.file_size else ""
                            with ui.row().classes("items-center gap-1.5 no-wrap pl-1"):
                                ui.label("[DROP]").classes("font-mono text-[9px] font-bold").style("color: var(--fx-crimson);")
                                ui.label(f"{sec.file_name} ({s_folder}) {s_size}").classes("text-[10px] truncate").style("color: var(--fx-text-muted);")

                if len(groups) > 15:
                    ui.label(f"... and {len(groups) - 15} more duplicate song groups").classes(
                        "text-[10px] font-roboto italic px-2"
                    ).style("color: var(--fx-text-muted);")

            # Target album for consolidation
            with ui.column().classes("w-full gap-1 mt-1"):
                ui.label("TARGET CONSOLIDATED ALBUM NAME:").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                album_input = ui.input(
                    value=initial_album,
                    placeholder="Enter album name to consolidate all unique tracks into..."
                ).props("dense outlined").classes("w-full fx-dialog-input").style(
                    "background-color: var(--fx-bg-input);"
                )

            with ui.row().classes("w-full justify-between items-center gap-2 mt-2"):
                ui.button("CLOSE", on_click=dlg.close, color=None).classes("fx-btn-outline px-3").style("height: 30px;")

                with ui.row().classes("items-center gap-2"):
                    def do_unstage():
                        self.state.unstage_tracks(dup_track_ids)
                        dlg.close()
                        self.update_display()
                        self.state.notify()
                        ui.notify(f"Unstaged {len(dup_track_ids)} duplicate tracks. Kept unique primary tracks.", color="positive")

                    def do_consolidate():
                        target_alb = album_input.value.strip() if album_input.value else initial_album
                        if not target_alb:
                            ui.notify("Please enter a target album name.", color="warning")
                            return
                        self.state.consolidate_duplicates_to_album(groups, target_alb)
                        dlg.close()
                        self.update_display()
                        self.state.notify()
                        ui.notify(f"Consolidated into unique album '{target_alb}' with {len(dup_track_ids)} duplicates removed.", color="positive")

                    ui.button(
                        "UNSTAGE DUPLICATES ONLY",
                        on_click=do_unstage,
                        color=None,
                    ).classes("fx-btn-outline px-3").style("height: 30px;").tooltip("Remove duplicate copies from staging, keeping each unique track in its original folder")

                    ui.button(
                        "CONSOLIDATE TO UNIQUE ALBUM",
                        on_click=do_consolidate,
                        color=None,
                    ).classes("fx-btn-primary px-3").style("height: 30px;").tooltip("Discard duplicates so every song is unique, and merge all tracks into one album folder")

        dlg.open()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def update_display(self):
        total = len(self.state.tracks)
        v = sum(1 for t in self.state.tracks if t.status == TrackStatus.VERIFIED)
        a = sum(1 for t in self.state.tracks if t.status == TrackStatus.AMBIGUOUS)
        u = sum(1 for t in self.state.tracks if t.status in (TrackStatus.UNMATCHED, TrackStatus.STAGED, TrackStatus.UNVERIFIED))

        if self.status_dropdown:
            opts = [f"ALL ({total})", f"VERIFIED ({v})", f"AMBIGUOUS ({a})", f"UNMATCHED ({u})"]
            self.status_dropdown.options = opts
            active_prefix = self.state.status_filter
            matching = [opt for opt in opts if opt.startswith(active_prefix)]
            if matching and self.status_dropdown.value != matching[0]:
                self.status_dropdown.value = matching[0]

        if self.select_by_dropdown and self.select_by_dropdown.value != self.state.select_by_mode:
            self.select_by_dropdown.value = self.state.select_by_mode

        has_filter = bool(
            self.state.search_filter
            or (self.state.active_context_filter and self.state.select_by_mode != "None")
            or self.state.status_filter != "ALL"
        )
        if self.show_all_btn:
            self.show_all_btn.set_visibility(has_filter)

        if self.search_input and self.search_input.value != self.state.search_filter:
            self.search_input.set_value(self.state.search_filter)

        has_tracks = bool(self.state.tracks)
        for btn in (self.edit_selected_btn, self.clean_tracks_btn, self.clean_titles_btn, self.duplicates_btn):
            if btn:
                if has_tracks:
                    btn.enable()
                else:
                    btn.disable()

        if self.table_container:
            self.table_container.clear()
            with self.table_container:
                self.render_header()
                self.render_rows()
