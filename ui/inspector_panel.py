"""
Inspector & Diff Panel (Right Pane - 35% width, 504px at the 1440px design width)

Mockup alignment (both exports):
  * Card surface background (#2D2D2D dark / #FFFFFF light)
  * Header 55.5px (10px/16px padding, 3px gap)
  * Album art section: 220x220 artwork (4px radius) + cover-art info column
  * Metadata diff: Oswald 11.5px heading, 8.5px column heads, 92px field labels,
    27.5px rows separated by a subtle border; "current" values use the mockup's
    diff accent (--fx-diff-current), proposed values the matched accent
  * Path transformation: OLD/NEW mono path boxes with OLD/NEW tags
"""

import os
import sys
import subprocess
import base64
import hashlib
from pathlib import Path
from typing import Any, Callable, Optional, List
from nicegui import ui
from core.models import AudioTrack, TrackStatus
from core.state import FXsonicState
from core.tagger import extract_current_artwork
from core.dialogs import choose_image_file_dialog
from ui.drop_zone import attach_folder_drop_zone

# Artwork metadata (dimensions/format/size) is derived once per distinct payload
# so re-rendering the inspector never re-decodes the same image.
_ART_META_CACHE: dict = {}


def _artwork_meta(data: bytes, mime: str) -> str:
    """Return the mockup's meta line, e.g. "600 × 600 · JPEG · 184 KB"."""
    if not data:
        return ""
    key = (mime, len(data), data[:32])
    cached = _ART_META_CACHE.get(key)
    if cached is not None:
        return cached

    fmt = (mime or "image/jpeg").split("/")[-1].upper()
    size_kb = f"{len(data) / 1024:.0f} KB"
    dims = ""
    try:
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(data)) as img:
            dims = f"{img.width} × {img.height} · "
    except Exception:
        dims = ""

    meta = f"{dims}{fmt} · {size_kb}"
    _ART_META_CACHE[key] = meta
    return meta


class InspectorPanel:
    ART_SIZE = "220px"

    def __init__(self, state: FXsonicState, on_folder_drop: Optional[Callable[[str], Any]] = None):
        self.state = state
        self.on_folder_drop = on_folder_drop
        self._current_art_hash = None

        self.container = None
        self.empty_container = None
        self.detail_container = None
        self.header_container = None
        self.art_section = None
        self.art_wrapper = None
        self.art_img = None
        self.art_source_overlay = None
        self.art_meta_overlay = None
        self.art_placeholder = None
        self.art_info_column = None
        self.diff_container = None

        self.render()

    def render(self):
        self.container = ui.column().classes(
            "w-full h-full p-0 m-0 gap-0 flex-grow overflow-y-auto"
        ).style(
            "background-color: var(--fx-bg-card);"
        )
        with self.container:
            # 1. Empty state view
            self.empty_container = ui.column().classes(
                "w-full py-24 items-center justify-center text-center gap-2 p-4"
            )
            with self.empty_container:
                ui.icon("info", size="36px").style("color: var(--fx-border);")
                ui.label("NO TRACK SELECTED").classes(
                    "font-oswald text-xs tracking-wider"
                ).style("color: var(--fx-text-muted);")
                ui.label(
                    "Click any track in the staging list to inspect proposed changes and metadata diff."
                ).classes("text-xs font-roboto").style("color: var(--fx-text-muted);")

                # Drop zone #2 - "the track info zone": the panels below stay
                # empty until a track is loaded, so point users at the drop.
                with ui.column().classes(
                    "fx-drop-hint mt-3 px-5 py-3 items-center gap-1"
                ):
                    ui.icon("folder_open", size="18px").style("color: var(--fx-crimson);")
                    ui.label("DROP A SOURCE FOLDER HERE").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.6px]"
                    ).style("color: var(--fx-text-primary);")
                    ui.label("or use BROWSE to pick one").classes(
                        "font-roboto text-[10px]"
                    ).style("color: var(--fx-text-muted);")

            # 2. Detail state view
            self.detail_container = ui.column().classes("w-full p-0 m-0 gap-0")
            with self.detail_container:
                # Header
                self.header_container = ui.column().classes(
                    "w-full px-4 py-[10px] gap-[3px] border-b flex-shrink-0"
                ).style("border-bottom: 1px solid var(--fx-border);")

                # Artwork section
                self.art_section = ui.row().classes(
                    "w-full px-4 py-[10px] border-b no-wrap items-start flex-shrink-0"
                ).style("gap: 14px; border-bottom: 1px solid var(--fx-border);")
                with self.art_section:
                    # Persistent image wrapper (prevents DOM thrashing and image flashing)
                    self.art_wrapper = ui.element("div").classes("relative flex-shrink-0").style(
                        f"width: {self.ART_SIZE}; height: {self.ART_SIZE};"
                    )
                    with self.art_wrapper:
                        self.art_img = ui.image("").classes("w-full h-full object-cover border").style(
                            "border-radius: 4px; border-color: var(--fx-border);"
                        )
                        with ui.column().classes("absolute bottom-0 left-0 right-0").style(
                            "gap: 1px; padding: 5px 8px; background-color: rgba(15, 15, 15, 0.9); "
                            "border-bottom-left-radius: 4px; border-bottom-right-radius: 4px;"
                        ):
                            self.art_source_overlay = ui.label("").classes(
                                "font-oswald text-[9.5px] font-semibold truncate"
                            ).style("color: #FFFFFF;")
                            self.art_meta_overlay = ui.label("").classes(
                                "font-roboto text-[8.5px] truncate"
                            ).style("color: #C9C9C9;")

                    # Placeholder when no art exists
                    self.art_placeholder = ui.element("div").classes(
                        "flex flex-col items-center justify-center border flex-shrink-0"
                    ).style(
                        f"width: {self.ART_SIZE}; height: {self.ART_SIZE}; border-radius: 4px; "
                        "border-color: var(--fx-border); background-color: var(--fx-art-bg);"
                    )
                    with self.art_placeholder:
                        ui.icon("album", size="48px").style("color: var(--fx-border);")
                        ui.label("NO ART").classes("font-oswald text-[10px] mt-1").style(
                            "color: var(--fx-text-muted);"
                        )

                    # Right-hand Artwork Info & Action Button Group
                    self.art_info_column = ui.column().classes(
                        "flex-grow min-w-0 h-full justify-between py-[2px]"
                    ).style(f"min-height: {self.ART_SIZE};")

                # Metadata diff container
                self.diff_container = ui.column().classes(
                    "w-full px-4 py-[10px] gap-[5px] flex-shrink-0"
                )

        # Drop zone #2 - the whole Inspector / track info panel accepts a folder.
        if self.on_folder_drop:
            attach_folder_drop_zone(self.container, self.on_folder_drop)

        self.update_display()

    # ------------------------------------------------------------------
    # Sections Rendering / Reactive Updates
    # ------------------------------------------------------------------
    def update_display(self):
        track: AudioTrack = None
        if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
            track = self.state.tracks_by_id[self.state.selected_track_id]

        if not track:
            self.empty_container.set_visibility(True)
            self.detail_container.set_visibility(False)
            self._current_art_hash = None
            return

        self.empty_container.set_visibility(False)
        self.detail_container.set_visibility(True)

        total_tracks = len(self.state.tracks)
        current_idx = self.state.tracks.index(track) + 1 if track in self.state.tracks else 1

        self.render_header(track, current_idx, total_tracks)
        self.render_artwork(track)
        self.render_metadata_diff(track)

    def render_header(self, track: AudioTrack, current_idx: int, total_tracks: int):
        self.header_container.clear()
        with self.header_container:
            ui.label(
                f"TRACK {current_idx} OF {total_tracks} • SELECTED FOR REVIEW"
            ).classes("font-oswald text-[12px] font-bold tracking-[0.6px]").style(
                "color: var(--fx-text-primary);"
            )
            hdr_lbl = ui.label(track.file_name).classes("font-mono text-[11px] truncate").style(
                "color: var(--fx-text-muted);"
            )
            with hdr_lbl:
                ui.tooltip(track.file_name)

    def render_artwork(self, track: AudioTrack):
        art_data = None
        art_mime = "image/jpeg"
        art_source = "MusicBrainz Cover Art Archive"
        art_meta = ""

        if track.proposed.artwork_data:
            art_data = track.proposed.artwork_data
            art_mime = track.proposed.artwork_mime or "image/jpeg"
            art_source = track.proposed.artwork_info or "MusicBrainz Cover Art Archive"
            art_meta = _artwork_meta(art_data, art_mime)
        else:
            curr_art = extract_current_artwork(track.file_path)
            if curr_art:
                art_data, art_mime = curr_art
                art_source = "Local ID3 APIC"
                art_meta = _artwork_meta(art_data, art_mime)

        new_hash = hashlib.md5(art_data).hexdigest() if art_data else None

        # Check hash to prevent artwork flicker/flashing
        if art_data:
            self.art_placeholder.set_visibility(False)
            self.art_wrapper.set_visibility(True)

            if new_hash != self._current_art_hash:
                b64_str = base64.b64encode(art_data).decode("utf-8")
                self.art_img.set_source(f"data:{art_mime};base64,{b64_str}")
                self._current_art_hash = new_hash

            self.art_source_overlay.text = art_source
            self.art_meta_overlay.text = art_meta or "—"
        else:
            self.art_wrapper.set_visibility(False)
            self.art_placeholder.set_visibility(True)
            self._current_art_hash = None

        # Check multi-selection state across staged tracks
        selected_tracks = [t for t in self.state.tracks if t.selected]
        selected_count = len(selected_tracks)
        multi_selected = selected_count > 1

        # Populate Right Info Column & Action Controls
        self.art_info_column.clear()
        with self.art_info_column:
            # Top: Play Button replacing redundant text to the right of the image
            with ui.column().classes("w-full gap-1"):
                with ui.button(
                    on_click=lambda: self.play_track(track.file_path),
                    color=None,
                ).classes(
                    "fx-btn-primary w-full px-3 py-2 items-center justify-center whitespace-nowrap font-oswald text-[11.5px] font-semibold tracking-[0.6px]"
                ).style("height: 36px; gap: 6px;"):
                    ui.icon("play_arrow", size="18px")
                    ui.label("PLAY TRACK")

            # Album Level Controls (beside the album cover)
            with ui.column().classes("w-full gap-1.5 mt-auto pt-1"):
                ui.label("ALBUM CONTROLS").classes(
                    "font-oswald text-[9px] font-semibold tracking-[0.6px]"
                ).style("color: var(--fx-text-muted);")

                ui.button(
                    "EDIT ALBUM DATA",
                    on_click=self.open_album_editor_dialog,
                    color=None,
                ).classes(
                    "fx-btn-outline w-full px-2 whitespace-nowrap font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("height: 26px;").tooltip("Batch edit album metadata for tracks in this album")

                ui.button(
                    "COPY ART TO ALBUM",
                    on_click=lambda: self.inject_artwork_to_album(track),
                    color=None,
                ).classes(
                    "fx-btn-outline w-full px-2 whitespace-nowrap font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("height: 26px;").tooltip("Copy the cover art shown above and inject into all tracks in this album")

                ui.button(
                    "REPLACE ALBUM ART (FILE)",
                    on_click=self.replace_album_artwork,
                    color=None,
                ).classes(
                    "fx-btn-outline w-full px-2 whitespace-nowrap font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("height: 26px;").tooltip("Choose an image file from disk and apply to all tracks in this album")

    def render_metadata_diff(self, track: AudioTrack):
        self.diff_container.clear()
        with self.diff_container:
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("TRACK INFO").classes("fx-section-head")

            # Column heads: FIELD / CURRENT / PROPOSED
            with ui.row().classes("w-full items-center no-wrap").style("gap: 8px; padding: 3px 0px;"):
                ui.label("FIELD").classes("fx-diff-head").style("width: 92px; flex-shrink: 0;")
                ui.label("CURRENT").classes("fx-diff-head").style("flex: 1 1 0; min-width: 0;")
                ui.label("PROPOSED").classes("fx-diff-head").style("flex: 1 1 0; min-width: 0;")

            fields = (
                ("TITLE", track.current.title, track.proposed.title),
                ("ARTIST", track.current.artist, track.proposed.artist),
                ("ALBUM", track.current.album, track.proposed.album),
                ("ALBUM ARTIST", track.current.album_artist, track.proposed.album_artist),
                ("RELEASE YEAR", track.current.year, track.proposed.year),
                ("GENRE", track.current.genre, track.proposed.genre),
                ("TRACK / DISC", self.track_disc_text(track), self.track_disc_text(track, proposed=True)),
            )

            for label, curr_val, prop_val in fields:
                has_diff = curr_val != prop_val
                with ui.row().classes("fx-diff-row w-full no-wrap"):
                    ui.label(label).classes("fx-diff-label")
                    c_lbl = ui.label(curr_val or "—").classes("fx-diff-value truncate").style(
                        f"color: {'var(--fx-diff-current)' if has_diff else 'var(--fx-text-muted)'};"
                    )
                    if curr_val:
                        with c_lbl:
                            ui.tooltip(curr_val)

                    disp_prop = prop_val or ("— (CLEARED)" if (has_diff and curr_val) else "—")
                    disp_style = (
                        "color: var(--fx-crimson); font-style: italic;"
                        if (has_diff and not prop_val and curr_val)
                        else ("color: var(--fx-text-primary);" if prop_val else "color: var(--fx-text-muted);")
                    )
                    p_lbl = ui.label(disp_prop).classes("fx-diff-value truncate").style(disp_style)
                    if prop_val:
                        with p_lbl:
                            ui.tooltip(prop_val)

            # Deleted junk frames callout
            if track.current.junk_frames:
                with ui.column().classes("w-full p-2 mt-1 gap-1").style(
                    "background-color: var(--fx-status-unmatched-bg); "
                    "border: 1px solid rgba(170, 24, 44, 0.3); border-radius: 2px;"
                ):
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("delete_sweep", size="14px").style(
                            "color: var(--fx-status-unmatched-text);"
                        )
                        ui.label(
                            f"DELETED JUNK FRAMES ({len(track.current.junk_frames)})"
                        ).classes("font-oswald text-[10px] font-semibold tracking-[0.5px]").style(
                            "color: var(--fx-status-unmatched-text);"
                        )

                    for junk in track.current.junk_frames[:4]:
                        frame_type, _, frame_value = junk.partition("::")
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(frame_type.upper()).classes("font-oswald text-[9px] font-semibold").style(
                                "color: var(--fx-status-unmatched-text);"
                            )
                            j_lbl = ui.label(frame_value or frame_type).classes(
                                "font-mono text-[9.5px] truncate flex-grow"
                            ).style("color: var(--fx-text-primary);")
                            with j_lbl:
                                ui.tooltip(frame_value or frame_type)

            # Track Level Control Buttons (strictly for the active track)
            with ui.column().classes("w-full gap-1.5 mt-2 pt-2 border-t").style("border-color: var(--fx-border);"):
                ui.label("TRACK CONTROLS").classes(
                    "font-oswald text-[9.5px] font-semibold tracking-[0.6px]"
                ).style("color: var(--fx-text-muted);")

                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.button(
                        "EDIT TRACK DETAILS",
                        on_click=lambda: self.open_track_editor_dialog(track),
                        color=None,
                    ).classes(
                        "fx-btn-outline flex-1 px-1 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 28px;").tooltip("Edit metadata fields for this individual track")

                    ui.button(
                        "REPLACE TRACK ART",
                        on_click=lambda: self.replace_artwork(track),
                        color=None,
                    ).classes(
                        "fx-btn-outline flex-1 px-1 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 28px;").tooltip("Choose an image file from disk and apply to this track")

                    ui.button(
                        "REMOVE TRACK ART",
                        on_click=lambda: self.remove_artwork(track),
                        color=None,
                    ).classes(
                        "fx-btn-cancel flex-1 px-1 whitespace-nowrap font-oswald text-[9.5px] font-semibold tracking-[0.4px]"
                    ).style("height: 28px;").tooltip("Remove artwork from this track")

    @staticmethod
    def track_disc_text(track: AudioTrack, proposed: bool = False) -> str:
        meta = track.proposed if proposed else track.current
        parts = [p for p in (meta.track_number, meta.disc_number) if p]
        return f"{' / '.join(parts)}" if parts else ""

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

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    async def replace_album_artwork(self):
        """Prompt user for an image file (.jpg, .png) and apply to staged tracks belonging to this album."""
        if not self.state.tracks:
            ui.notify("No tracks staged.", color="warning")
            return

        active_track = None
        if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
            active_track = self.state.tracks_by_id[self.state.selected_track_id]
        elif self.state.tracks:
            selected = [t for t in self.state.tracks if t.selected]
            active_track = selected[0] if selected else self.state.tracks[0]

        album_tracks = self.state.get_album_tracks_for(active_track) if active_track else list(self.state.tracks)

        img_path = await choose_image_file_dialog("Select New Album Artwork (.jpg, .png)")
        if img_path and Path(img_path).exists():
            with open(img_path, "rb") as f:
                data = f.read()
            mime = "image/png" if img_path.lower().endswith(".png") else "image/jpeg"
            self.state.album_cover_art = data
            self.state.album_cover_mime = mime
            info = f"Custom Album Art • {Path(img_path).name}"

            # Mark all staged tracks in this album to receive the new artwork bytes in their APIC frame
            for t in album_tracks:
                t.proposed.artwork_data = data
                t.proposed.artwork_mime = mime
                t.proposed.artwork_info = info

            self.update_display()
            self.state.notify()
            ui.notify(f"Album artwork updated for {len(album_tracks)} track(s) in this album.", color="positive")

    def inject_artwork_to_album(self, track: Optional[AudioTrack] = None):
        """Copy cover art from the selected track and inject into tracks in this album, with confirmation pop-up."""
        if not self.state.tracks:
            ui.notify("No tracks loaded.", color="warning")
            return

        target_track = track
        if not target_track:
            if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
                target_track = self.state.tracks_by_id[self.state.selected_track_id]
            elif self.state.tracks:
                target_track = self.state.tracks[0]

        album_tracks = self.state.get_album_tracks_for(target_track) if target_track else list(self.state.tracks)

        art_data = None
        art_mime = "image/jpeg"

        if target_track and target_track.proposed.artwork_data:
            art_data = target_track.proposed.artwork_data
            art_mime = target_track.proposed.artwork_mime or "image/jpeg"
        elif target_track:
            curr_art = extract_current_artwork(target_track.file_path)
            if curr_art:
                art_data, art_mime = curr_art

        if not art_data and self.state.album_cover_art:
            art_data = self.state.album_cover_art
            art_mime = self.state.album_cover_mime or "image/jpeg"

        if not art_data:
            ui.notify("The selected track has no cover art to copy. Select a track with cover art or use 'Replace Album Art'.", color="warning")
            return

        track_title = (target_track.proposed.title or target_track.current.title or target_track.file_name) if target_track else "Selected Track"
        album_name = (target_track.proposed.album or target_track.current.album or "this album") if target_track else "this album"

        with ui.dialog() as dlg, ui.card().classes("p-5 gap-3 min-w-[420px] max-w-[500px]").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); border-radius: 4px;"
        ):
            with ui.row().classes("items-center gap-2"):
                ui.icon("collections", size="20px").style("color: var(--fx-crimson);")
                ui.label("COPY ART TO ALBUM").classes(
                    "font-oswald text-[13px] font-bold tracking-[0.6px]"
                ).style("color: var(--fx-text-primary);")

            ui.label(
                f"Are you sure you want to copy cover art from '{track_title}' into all {len(album_tracks)} track(s) in album '{album_name}'?\n\n"
                "Only tracks belonging to this album will be updated. Other staged folders/albums remain untouched."
            ).classes("text-xs font-roboto whitespace-pre-line leading-relaxed").style("color: var(--fx-text-muted);")

            with ui.row().classes("w-full justify-end items-center gap-2 mt-3"):
                ui.button("CANCEL", on_click=dlg.close, color=None).classes(
                    "fx-btn-outline px-[14px]"
                ).style("height: 30px;")

                def do_inject():
                    dlg.close()
                    info = f"Injected from {target_track.file_name if target_track else 'Selected Track'}"
                    for t in album_tracks:
                        t.proposed.artwork_data = art_data
                        t.proposed.artwork_mime = art_mime
                        t.proposed.artwork_info = info
                        t.current.has_artwork = True
                    self.state.album_cover_art = art_data
                    self.state.album_cover_mime = art_mime
                    self.update_display()
                    self.state.notify()
                    ui.notify(f"Injected cover art into {len(album_tracks)} track(s) in album '{album_name}'.", color="positive")

                ui.button("CONFIRM & COPY", on_click=do_inject, color=None).classes(
                    "fx-btn-primary px-[14px]"
                ).style("height: 30px;")

        dlg.open()

    def inject_artwork_to_all_tracks(self, track: AudioTrack):
        return self.inject_artwork_to_album(track)

    async def replace_artwork(self, track: AudioTrack):
        img_path = await choose_image_file_dialog("Select New Artwork")
        if img_path and Path(img_path).exists():
            with open(img_path, "rb") as f:
                data = f.read()
            track.proposed.artwork_data = data
            track.proposed.artwork_mime = "image/png" if img_path.lower().endswith(".png") else "image/jpeg"
            track.proposed.artwork_info = f"Custom File • {Path(img_path).name}"
            self.update_display()
            self.state.notify()

    async def replace_artwork_batch(self, tracks: List[AudioTrack]):
        if not tracks:
            return
        img_path = await choose_image_file_dialog("Select New Artwork")
        if img_path and Path(img_path).exists():
            with open(img_path, "rb") as f:
                data = f.read()
            mime = "image/png" if img_path.lower().endswith(".png") else "image/jpeg"
            info = f"Custom File • {Path(img_path).name}"
            for t in tracks:
                t.proposed.artwork_data = data
                t.proposed.artwork_mime = mime
                t.proposed.artwork_info = info
            ui.notify(f"Artwork updated for {len(tracks)} selected tracks.", color="positive")
            self.update_display()
            self.state.notify()

    def remove_artwork(self, track: AudioTrack):
        track.proposed.artwork_data = b""
        track.proposed.artwork_info = "Removed"
        ui.notify("Artwork removed from track.", color="positive")
        self.update_display()
        self.state.notify()

    def remove_artwork_batch(self, tracks: List[AudioTrack]):
        if not tracks:
            return
        for t in tracks:
            t.proposed.artwork_data = b""
            t.proposed.artwork_info = "Removed"
        ui.notify(f"Artwork removed from {len(tracks)} selected tracks.", color="positive")
        self.update_display()
        self.state.notify()

    def open_track_editor_dialog(self, track: AudioTrack):
        """Opens modal dialog for editing metadata of a single track."""
        show_track_editor_dialog(
            track=track,
            state=self.state,
            on_done=lambda: (self.update_display(), self.state.notify()),
        )

    def open_album_editor_dialog(self):
        """Opens modal dialog for batch editing album metadata."""
        if not self.state.tracks:
            ui.notify("No tracks staged to edit.", color="warning")
            return

        active_track = None
        if self.state.selected_track_id and self.state.selected_track_id in self.state.tracks_by_id:
            active_track = self.state.tracks_by_id[self.state.selected_track_id]
        elif self.state.tracks:
            selected = [t for t in self.state.tracks if t.selected]
            active_track = selected[0] if selected else self.state.tracks[0]

        album_tracks = self.state.get_album_tracks_for(active_track) if active_track else list(self.state.tracks)

        initial_album = (active_track.proposed.album or active_track.current.album) if active_track else ""
        initial_artist = (active_track.proposed.album_artist or active_track.proposed.artist or active_track.current.album_artist or active_track.current.artist) if active_track else ""
        initial_year = (active_track.proposed.year or active_track.current.year) if active_track else ""
        initial_genre = (active_track.proposed.genre or active_track.current.genre) if active_track else ""

        with ui.dialog() as dialog, ui.card().classes("p-5 gap-3").style(
            "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); "
            "min-width: 460px; max-width: 520px; border-radius: 4px;"
        ):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                with ui.column().classes("gap-0.5"):
                    ui.label("EDIT ALBUM METADATA").classes(
                        "font-oswald text-[13px] font-bold tracking-[0.6px]"
                    ).style("color: var(--fx-text-primary);")
                    subtitle = f"Album ({len(album_tracks)} tracks) • Values from Track {active_track.id}: {active_track.file_name}" if active_track else "Batch edit proposed metadata across staged tracks"
                    ui.label(subtitle).classes(
                        "font-roboto text-[11px] truncate max-w-[310px]"
                    ).style("color: var(--fx-text-muted);")
                ui.button(
                    "CLEAR ALL FIELDS",
                    on_click=lambda: clear_all_fields(),
                    color=None,
                ).classes("fx-btn-outline px-2 text-[10px]").style("height: 24px;").tooltip("Clear all fields to retain original track metadata")

            def clear_all_fields():
                album_input.set_value("")
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
                        placeholder="Enter album title (leave blank to keep track info)..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )
                    with album_input.add_slot("append"):
                        ui.icon("close", size="14px").classes("cursor-pointer").style(
                            "color: var(--fx-text-muted);"
                        ).on("click", lambda: album_input.set_value("")).tooltip("Clear to keep original track info")

                # Field 2: Album Artist / Artist
                with ui.column().classes("w-full gap-1"):
                    ui.label("ALBUM ARTIST / ARTIST").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    artist_input = ui.input(
                        value=initial_artist,
                        placeholder="Enter album artist or artist (leave blank to keep track info)..."
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

            ui.label("BATCH TARGET").classes(
                "font-oswald text-[10px] font-semibold tracking-[0.5px] mt-1"
            ).style("color: var(--fx-text-muted);")

            album_scope_label = f"Apply to All Tracks in Album ({len(album_tracks)})"
            selected_in_album = [t for t in album_tracks if t.selected]
            selected_count = len(selected_in_album) if selected_in_album else len([t for t in self.state.tracks if t.selected])
            selected_scope_label = f"Apply to Selected Tracks Only ({selected_count})"

            scope_radio = ui.radio(
                [album_scope_label, selected_scope_label],
                value=album_scope_label,
            ).props("dense").classes("text-xs font-roboto")

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("CANCEL", on_click=dialog.close, color=None).classes(
                    "fx-btn-outline px-[14px]"
                ).style("height: 30px;")

                def apply_batch():
                    scope = scope_radio.value
                    if scope.startswith("Apply to All Tracks in Album"):
                        targets = album_tracks
                    else:
                        selected_in_album = [t for t in album_tracks if t.selected]
                        targets = selected_in_album if selected_in_album else [t for t in self.state.tracks if t.selected]
                        if not targets:
                            targets = album_tracks

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
                    ui.notify(f"Updated album metadata for {len(targets)} track(s).", color="positive")

                ui.button("APPLY CHANGES", on_click=apply_batch, color=None).classes(
                    "fx-btn-primary px-[14px]"
                ).style("height: 30px;")

        dialog.open()


def show_track_editor_dialog(track: AudioTrack, state: FXsonicState, on_done: Optional[Callable[[], None]] = None):
    """Opens modal dialog for editing metadata of a single track."""
    if not track:
        return

    initial_title = track.proposed.title or track.current.title or track.file_name
    initial_artist = track.proposed.artist or track.current.artist or ""
    initial_album = track.proposed.album or track.current.album or ""
    initial_album_artist = track.proposed.album_artist or track.current.album_artist or ""
    initial_year = track.proposed.year or track.current.year or ""
    initial_genre = track.proposed.genre or track.current.genre or ""
    initial_track_no = track.proposed.track_number or track.current.track_number or ""
    initial_disc_no = track.proposed.disc_number or track.current.disc_number or ""

    with ui.dialog() as dialog, ui.card().classes("p-5 gap-3").style(
        "background-color: var(--fx-bg-card); border: 1px solid var(--fx-border); "
        "min-width: 460px; max-width: 520px; border-radius: 4px;"
    ):
        with ui.column().classes("w-full gap-1"):
            ui.label("EDIT TRACK DATA").classes(
                "font-oswald text-[13px] font-bold tracking-[0.6px]"
            ).style("color: var(--fx-text-primary);")
            sub = ui.label(track.file_name).classes(
                "font-mono text-[11px] truncate w-full"
            ).style("color: var(--fx-text-muted);")
            with sub:
                ui.tooltip(track.file_path)

        with ui.column().classes("w-full gap-2.5 my-2"):
            # Field 1: Track Title
            with ui.column().classes("w-full gap-1"):
                ui.label("TRACK TITLE / NAME").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                title_input = ui.input(
                    value=initial_title,
                    placeholder="Enter track title..."
                ).props("dense outlined").classes("w-full fx-dialog-input").style(
                    "background-color: var(--fx-bg-input);"
                )

            # Field 2: Track Artist
            with ui.column().classes("w-full gap-1"):
                ui.label("TRACK ARTIST").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                artist_input = ui.input(
                    value=initial_artist,
                    placeholder="Enter track artist..."
                ).props("dense outlined").classes("w-full fx-dialog-input").style(
                    "background-color: var(--fx-bg-input);"
                )

            # Field 3: Album
            with ui.column().classes("w-full gap-1"):
                ui.label("ALBUM").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                album_input = ui.input(
                    value=initial_album,
                    placeholder="Enter album title..."
                ).props("dense outlined").classes("w-full fx-dialog-input").style(
                    "background-color: var(--fx-bg-input);"
                )

            # Field 4: Album Artist
            with ui.column().classes("w-full gap-1"):
                ui.label("ALBUM ARTIST").classes(
                    "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                ).style("color: var(--fx-text-muted);")
                album_artist_input = ui.input(
                    value=initial_album_artist,
                    placeholder="Enter album artist..."
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
                        placeholder="e.g. Soundtrack, Pop, Rock..."
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )

            # Row with Track # & Disc #
            with ui.row().classes("w-full gap-3 no-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    ui.label("TRACK NUMBER").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    track_no_input = ui.input(
                        value=initial_track_no,
                        placeholder="e.g. 1 or 01"
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )

                with ui.column().classes("flex-1 gap-1"):
                    ui.label("DISC NUMBER").classes(
                        "font-oswald text-[10px] font-semibold tracking-[0.5px]"
                    ).style("color: var(--fx-text-muted);")
                    disc_no_input = ui.input(
                        value=initial_disc_no,
                        placeholder="e.g. 1"
                    ).props("dense outlined").classes("w-full fx-dialog-input").style(
                        "background-color: var(--fx-bg-input);"
                    )

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("CANCEL", on_click=dialog.close, color=None).classes(
                "fx-btn-outline px-[14px]"
            ).style("height: 30px;")

            def save_track_data():
                track.proposed.title = title_input.value.strip() if title_input.value else ""
                track.proposed.artist = artist_input.value.strip() if artist_input.value else ""
                track.proposed.album = album_input.value.strip() if album_input.value else ""
                track.proposed.album_artist = album_artist_input.value.strip() if album_artist_input.value else ""
                track.proposed.year = year_input.value.strip() if year_input.value else ""
                track.proposed.genre = genre_input.value.strip() if genre_input.value else ""
                track.proposed.track_number = track_no_input.value.strip() if track_no_input.value else ""
                track.proposed.disc_number = disc_no_input.value.strip() if disc_no_input.value else ""

                state.refresh_destination_paths()
                state.update_metrics()
                dialog.close()
                if on_done:
                    on_done()

            ui.button("SAVE CHANGES", on_click=save_track_data, color=None).classes(
                "fx-btn-primary px-[14px]"
            ).style("height: 30px;")

    dialog.open()

