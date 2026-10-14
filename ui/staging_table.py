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
import sys
import time
import subprocess
from pathlib import Path
from typing import Callable
from nicegui import ui
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
        self.chip_all = None
        self.chip_verified = None
        self.chip_ambiguous = None
        self.chip_unmatched = None
        self.edit_album_btn = None
        self.clean_titles_btn = None
        self.table_container = None
        self.row_elements: dict[str, ui.row] = {}
        self._last_clicked_track_id = None
        self._last_click_time = 0.0
        self._last_dialog_open_time = 0.0

        self.render()

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------
    def render(self):
        self.root_container = ui.column().classes("w-full h-full p-0 m-0 gap-0 flex-grow overflow-hidden")
        with self.root_container:
            # A. Filter Bar
            with ui.row().classes(
                "fx-filterbar w-full h-[50px] px-4 items-center justify-between border-b no-wrap flex-shrink-0"
            ).style(
                "gap: 12px; background-color: var(--fx-bg-window); border-bottom: 1px solid var(--fx-border);"
            ):
                # Search Input (250x30px)
                self.search_input = ui.input(
                    placeholder="Filter by title, artist, or status...",
                    on_change=lambda e: self.on_search(e.value),
                ).props("dense outlined").classes("fx-input-sm w-[250px] flex-shrink-0").style(
                    "background-color: var(--fx-bg-input);"
                )
                self.search_input.on("keydown.escape", lambda: self.clear_search())
                self.search_input.on("keydown.esc", lambda: self.clear_search())
                with self.search_input.add_slot("prepend"):
                    ui.icon("search", size="14px").style("color: var(--fx-text-muted);")

                # Filter Chips
                with ui.row().classes("items-center gap-[6px] no-wrap"):
                    self.chip_all = ui.label("ALL (0)").classes("filter-chip active").on(
                        "click", lambda: self.set_filter("ALL")
                    )
                    self.chip_verified = ui.label("VERIFIED (0)").classes("filter-chip").on(
                        "click", lambda: self.set_filter("VERIFIED")
                    )
                    self.chip_ambiguous = ui.label("AMBIGUOUS (0)").classes("filter-chip").on(
                        "click", lambda: self.set_filter("AMBIGUOUS")
                    )
                    self.chip_unmatched = ui.label("UNMATCHED (0)").classes("filter-chip").on(
                        "click", lambda: self.set_filter("UNMATCHED")
                    )

                # Spacer so the action controls are pushed to the far right
                ui.element("div").classes("flex-grow")

                # Edit Album Metadata Button (28px tall, text only, fixed padding)
                self.edit_album_btn = ui.button(
                    "EDIT ALBUM METADATA",
                    on_click=self.open_album_editor_dialog,
                    color=None,
                ).classes(
                    "fx-btn-outline px-3 py-1.5 whitespace-nowrap font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("height: 28px; color: var(--fx-text-primary);")
                if not self.state.tracks:
                    self.edit_album_btn.disable()

                # Clean Track Titles Button (28px tall, text only, fixed padding)
                self.clean_titles_btn = ui.button(
                    "CLEAN TRACK TITLES",
                    on_click=self.clean_track_titles,
                    color=None,
                ).classes(
                    "fx-btn-outline px-3 py-1.5 whitespace-nowrap font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("height: 28px; color: var(--fx-text-primary);")
                self.clean_titles_btn.tooltip("Strip leading track numbers, trailing album tags, and apply Smart Title Case")
                if not self.state.tracks:
                    self.clean_titles_btn.disable()

            # B. Scrollable table shell (sticky header + rows)
            self.table_container = ui.column().classes(
                "w-full flex-grow min-h-0 overflow-y-auto p-0 m-0 gap-0"
            ).style("background-color: var(--fx-bg-window);")
            with self.table_container:
                self.render_header()
                self.render_rows()

    # ------------------------------------------------------------------
    # Table header + rows
    # ------------------------------------------------------------------
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
                ui.label("STATUS").classes("fx-th")
            with _table_cell("file"):
                ui.label("FILE NAME").classes("fx-th")
            with _table_cell("artist"):
                ui.label("ARTIST").classes("fx-th")
            with _table_cell("title"):
                ui.label("TITLE").classes("fx-th")
            with _table_cell("album"):
                ui.label("ALBUM").classes("fx-th")
            with _table_cell("year"):
                ui.label("YEAR / TRACK").classes("fx-th")
            with _table_cell("id", justify="center"):
                ui.label("ID").classes("fx-th")

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

    def reset_filters(self):
        """Resets search filter and category filter chips to default ALL view."""
        self.state.search_filter = ""
        self.state.status_filter = "ALL"
        if self.search_input and self.search_input.value != "":
            self.search_input.set_value("")
        self.update_display()

    def set_filter(self, filter_name: str):
        self.state.status_filter = filter_name
        self.update_display()

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

    def select_track(self, track_id: str):
        prev_id = self.state.selected_track_id
        self.state.selected_track_id = track_id
        if prev_id and prev_id in self.row_elements:
            self.row_elements[prev_id].classes(remove="row-selected")
        if track_id in self.row_elements:
            self.row_elements[track_id].classes(add="row-selected")
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

    def open_album_editor_dialog(self):
        """Opens modal dialog for batch editing album metadata."""
        if not self.state.tracks:
            ui.notify("No tracks staged to edit.", color="warning")
            return

        initial_album = ""
        initial_artist = ""
        initial_year = ""
        initial_genre = ""

        for t in self.state.tracks:
            if not initial_album and (t.proposed.album or t.current.album):
                initial_album = t.proposed.album or t.current.album
            if not initial_artist and (t.proposed.album_artist or t.proposed.artist or t.current.album_artist or t.current.artist):
                initial_artist = t.proposed.album_artist or t.proposed.artist or t.current.album_artist or t.current.artist
            if not initial_year and (t.proposed.year or t.current.year):
                initial_year = t.proposed.year or t.current.year
            if not initial_genre and (t.proposed.genre or t.current.genre):
                initial_genre = t.proposed.genre or t.current.genre

        with ui.dialog() as dialog, ui.card().classes("p-5 gap-3").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); "
            "min-width: 440px; max-width: 500px; border-radius: 4px;"
        ):
            with ui.column().classes("w-full gap-1"):
                ui.label("EDIT ALBUM METADATA").classes(
                    "font-oswald text-[13px] font-bold tracking-[0.6px]"
                ).style("color: var(--fx-text-primary);")
                ui.label("Batch edit proposed metadata across staged tracks").classes(
                    "font-roboto text-[11px]"
                ).style("color: var(--fx-text-muted);")

            with ui.column().classes("w-full gap-2.5 my-2"):
                # Field 1: Album Title
                with ui.column().classes("w-full gap-1"):
                    ui.label("ALBUM TITLE").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    album_input = ui.input(
                        value=initial_album,
                        placeholder="Enter album title..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )

                # Field 2: Album Artist / Artist
                with ui.column().classes("w-full gap-1"):
                    ui.label("ALBUM ARTIST / ARTIST").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    artist_input = ui.input(
                        value=initial_artist,
                        placeholder="Enter album artist or artist..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )

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

            ui.label("BATCH TARGET").classes(
                "font-oswald text-[10px] font-semibold tracking-[0.5px] mt-1"
            ).style("color: var(--fx-text-muted);")

            scope_radio = ui.radio(
                ["Apply to All Tracks in Album", "Apply to Selected Tracks Only"],
                value="Apply to All Tracks in Album",
            ).props("dense").classes("text-xs font-roboto")

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("CANCEL", on_click=dialog.close, color=None).classes(
                    "fx-btn-outline px-[14px]"
                ).style("height: 30px;")

                def apply_batch():
                    scope = scope_radio.value
                    targets = (
                        self.state.tracks
                        if scope == "Apply to All Tracks in Album"
                        else [t for t in self.state.tracks if t.selected]
                    )
                    new_album = album_input.value.strip() if album_input.value else ""
                    new_artist = artist_input.value.strip() if artist_input.value else ""
                    new_year = year_input.value.strip() if year_input.value else ""
                    new_genre = genre_input.value.strip() if genre_input.value else ""

                    for t in targets:
                        if new_album:
                            t.proposed.album = new_album
                        if new_artist:
                            t.proposed.artist = new_artist
                            t.proposed.album_artist = new_artist
                        if new_year:
                            t.proposed.year = new_year
                        if new_genre:
                            t.proposed.genre = new_genre

                    self.state.refresh_destination_paths()
                    self.state.update_metrics()
                    dialog.close()
                    self.update_display()
                    self.state.notify()

                ui.button("APPLY CHANGES", on_click=apply_batch, color=None).classes(
                    "fx-btn-primary px-[14px]"
                ).style("height: 30px;")

        dialog.open()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def update_display(self):
        total = len(self.state.tracks)
        v = sum(1 for t in self.state.tracks if t.status == TrackStatus.VERIFIED)
        a = sum(1 for t in self.state.tracks if t.status == TrackStatus.AMBIGUOUS)
        u = sum(1 for t in self.state.tracks if t.status == TrackStatus.UNMATCHED)

        chips = (
            (self.chip_all, "ALL", total),
            (self.chip_verified, "VERIFIED", v),
            (self.chip_ambiguous, "AMBIGUOUS", a),
            (self.chip_unmatched, "UNMATCHED", u),
        )
        for chip, name, count in chips:
            if not chip:
                continue
            chip.text = f"{name} ({count})"
            is_active = self.state.status_filter == name
            chip.classes(add="active" if is_active else "", remove="" if is_active else "active")

        if self.search_input and self.search_input.value != self.state.search_filter:
            self.search_input.set_value(self.state.search_filter)

        if self.clean_titles_btn:
            if not self.state.tracks:
                self.clean_titles_btn.disable()
            else:
                self.clean_titles_btn.enable()

        if self.edit_album_btn:
            if not self.state.tracks:
                self.edit_album_btn.disable()
            else:
                self.edit_album_btn.enable()

        if self.table_container:
            self.table_container.clear()
            with self.table_container:
                self.render_header()
                self.render_rows()
