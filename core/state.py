"""
Main Application State Manager

Every long-running pipeline (staging, album identification, tag writing) runs behind a
single :class:`core.control.AbortController`, so CANCEL / ABORT stops the work at the
next item boundary, kills any live ``fpcalc`` process and resets the workbench.
"""

import asyncio
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from . import control
from .control import AbortController, OperationAborted
from .models import AudioTrack, TrackStatus, TrackMetadata, ProposedMetadata
from .diagnostics import diag
from .tagger import read_track_metadata, write_track_metadata, extract_current_artwork, applied_metadata
from .resolver import resolve_track, resolve_album_consensus, sanitize_metadata_text
from .router import compute_destination_path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aiff"}

#: Parallel readers used while staging a folder (mutagen reads are I/O bound).
STAGING_WORKERS = 8

#: Parallel writers used by APPLY CHANGES - the task's spec calls for 8.
APPLY_WORKERS = 8

#: Minimum spacing of progress *paints* during a batch.  Tag writing must not push a
#: WebSocket update for every file, so the footer counter is refreshed at most this
#: often and the staging table is repainted on a coarser cadence.
PROGRESS_UI_THROTTLE_SECONDS = 0.1

#: How often the staging table itself is re-rendered while a tag batch runs, so the
#: freshly written titles/artists become visible without a full table update per file.
BATCH_TABLE_REFRESH_SECONDS = 0.5



class FXsonicState:
    def __init__(self):
        # Directories
        self.source_directory: str = ""
        self.output_directory: str = ""

        # Options
        # Auto-Fetch Cover Art is OFF at launch: artwork is only downloaded when the
        # user explicitly opts in (network + accuracy cost), and even then the release
        # thumbnail is fetched once per album and capped at 1000x1000 px.
        self.auto_fetch_artwork: bool = False
        self.strip_junk_frames: bool = True
        self.prefer_romanized: bool = False
        self.rename_organize: bool = False
        self.rename_to_title: bool = True
        self.dark_mode: bool = True

        # Album Cover Art Cache
        self.album_cover_art: Optional[bytes] = None
        self.album_cover_mime: str = "image/jpeg"

        # Tracks data
        self.tracks: List[AudioTrack] = []
        self.tracks_by_id: Dict[str, AudioTrack] = {}
        self.selected_track_id: Optional[str] = None

        # Filter & Search
        self.search_filter: str = ""
        self.status_filter: str = "ALL"  # ALL, VERIFIED, AMBIGUOUS, UNMATCHED
        self.sort_key: str = "file_name"
        self.sort_ascending: bool = True
        self.select_by_mode: str = "None"  # None, Artist, Album, Folder, Status
        self.active_context_filter: Optional[str] = None

        # Scanning / Processing Task State
        #
        # ``abort`` is the one cancellation token every stage observes: async stages use
        # asyncio, worker threads use plain attribute reads, and it owns the live fpcalc
        # subprocesses so CANCEL / ABORT kills them instead of waiting for them.
        self.abort = AbortController("FXsonic")
        self.abort_requested: bool = False
        self.is_scanning: bool = False
        self.is_applying: bool = False
        # Staging runs off the event loop (parallel tag reads), so a second load can
        # start before the first finished.  Only the newest load may stage rows.
        self._intake_generation: int = 0
        # Folder currently being read; a duplicate delivery for it is ignored.
        self._intake_inflight: str = ""

        # Progress & Metrics
        self.progress_val: float = 0.0
        # Label the footer shows next to the bar (matches the mockup's
        # "Fingerprinting: 24 of 28 tracks (85%)" while the fingerprint stage runs).
        self.progress_phase: str = "Fingerprinting"
        self.status_message: str = "READY • Awaiting directory selection"
        self.count_verified: int = 0
        self.count_ambiguous: int = 0
        self.count_unmatched: int = 0
        self.count_errors: int = 0

        # UI Notification Callbacks
        self.on_state_change: Optional[Callable[[], None]] = None
        self.on_log_message: Optional[Callable[[str], None]] = None
        # Lightweight hook used for throttled batch progress: paints only the footer
        # counter, never the whole staging table.
        self.on_progress_change: Optional[Callable[[], None]] = None
        # Bookkeeping for the batch progress throttle (see report_progress).
        self._last_full_refresh: float = 0.0
        self._last_full_phase: str = ""

    def notify(self):
        if self.on_state_change:
            self.on_state_change()

    def notify_progress(self):
        """Paint only the progress counter (footer), not the whole workbench.

        Used by batch tag writing, where re-rendering the staging table for every file
        is what made APPLY CHANGES feel slow.  Falls back to a full refresh when no
        lightweight hook was registered (headless runs, audits).
        """
        if self.on_progress_change:
            try:
                self.on_progress_change()
                return
            except Exception:
                pass
        self.notify()

    def log(self, msg: str):
        # Always mirror pipeline status to the diagnostic sink (console + log file)
        # so network/parsing issues are visible even when the UI is not being
        # watched, or when a windowed build has no console at all.
        diag(msg)
        self.status_message = msg
        if self.on_log_message:
            self.on_log_message(msg)
        if self.is_scanning or self.is_applying:
            # During batch execution, update the status footer ticker without
            # triggering synchronous, heavy table rebuilds on every single line.
            self.notify_progress()
        else:
            self.notify()

    def report_progress(self, value: float, phase: str = "", refresh: bool = True) -> None:
        """Publish pipeline progress (0.0 - 1.0) plus a phase label for the footer.

        Called once per track by the identification pipeline, so the footer bar and
        its "Fingerprinting: 3 of 8 tracks (38%)" label follow the work instead of
        sitting at a fixed value.

        While a batch is running (scan or apply) the *footer counter* is repainted on
        every report, but the staging table - which means rebuilding every row element -
        follows at :data:`BATCH_TABLE_REFRESH_SECONDS`, and immediately whenever the
        phase changes.  Analysing 32 files in parallel otherwise delivers 32 table
        rebuilds in one synchronous burst, which is exactly what freezes the UI.
        A report outside a batch always paints fully.
        """
        try:
            self.progress_val = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        if phase:
            self.progress_phase = phase

        if not refresh:
            self.notify_progress()
            return

        if self.is_scanning or self.is_applying:
            now = time.monotonic()
            phase_changed = bool(phase) and phase != self._last_full_phase
            if phase_changed or (now - self._last_full_refresh) >= BATCH_TABLE_REFRESH_SECONDS:
                self._last_full_refresh = now
                if phase:
                    self._last_full_phase = phase
                self.notify()
            else:
                self.notify_progress()
            return

        self.notify()

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------
    @property
    def abort_requested(self) -> bool:
        """True once CANCEL / ABORT was pressed (backed by ``self.abort``)."""
        return self.abort.is_aborted

    @abort_requested.setter
    def abort_requested(self, value: bool) -> None:
        if value:
            self.abort.abort()
        else:
            self.abort.reset()

    def request_abort(self) -> None:
        """Signal every stage and kill live external tools immediately."""
        self.abort.abort()
        self.is_scanning = False
        self.is_applying = False

    def check_abort(self) -> None:
        """Raise :class:`OperationAborted` when the user asked to stop."""
        self.abort.check()


    def update_metrics(self):
        v = sum(1 for t in self.tracks if t.status == TrackStatus.VERIFIED)
        a = sum(1 for t in self.tracks if t.status == TrackStatus.AMBIGUOUS)
        u = sum(1 for t in self.tracks if t.status == TrackStatus.UNMATCHED)
        e = sum(1 for t in self.tracks if t.error_message is not None)
        self.count_verified = v
        self.count_ambiguous = a
        self.count_unmatched = u
        self.count_errors = e

    def get_filtered_tracks(self) -> List[AudioTrack]:
        results = self.tracks
        
        # Filter by status
        if self.status_filter == "VERIFIED":
            results = [t for t in results if t.status == TrackStatus.VERIFIED]
        elif self.status_filter == "AMBIGUOUS":
            results = [t for t in results if t.status == TrackStatus.AMBIGUOUS]
        elif self.status_filter == "UNMATCHED":
            results = [t for t in results if t.status in (TrackStatus.UNMATCHED, TrackStatus.STAGED, TrackStatus.UNVERIFIED)]

        # Contextual filter (Select By)
        if self.active_context_filter and self.select_by_mode != "None":
            ctx = self.active_context_filter.strip().lower()
            if self.select_by_mode == "Artist":
                results = [t for t in results if (t.proposed.artist or t.current.artist or "").strip().lower() == ctx]
            elif self.select_by_mode == "Album":
                results = [t for t in results if (t.proposed.album or t.current.album or "").strip().lower() == ctx]
            elif self.select_by_mode == "Folder":
                results = [t for t in results if str(Path(t.file_path).parent).lower() == ctx]
            elif self.select_by_mode == "Status":
                results = [t for t in results if t.status.value.lower() == ctx]

        # Filter by text search
        query = self.search_filter.strip().lower()
        if query:
            filtered = []
            for t in results:
                title = (t.proposed.title or t.current.title).lower()
                artist = (t.proposed.artist or t.current.artist).lower()
                album = (t.proposed.album or t.current.album).lower()
                fname = t.file_name.lower()
                if query in title or query in artist or query in album or query in fname:
                    filtered.append(t)
            results = filtered

        # Helper for numeric sorting
        def _num_or_zero(s: Any) -> int:
            try:
                digits = re.search(r"\d+", str(s or ""))
                return int(digits.group(0)) if digits else 0
            except Exception:
                return 0

        # Sort
        reverse = not self.sort_ascending
        if self.sort_key == "file_name":
            results = sorted(results, key=lambda x: x.file_name.lower(), reverse=reverse)
        elif self.sort_key == "title":
            results = sorted(results, key=lambda x: (x.proposed.title or x.current.title or x.file_name).lower(), reverse=reverse)
        elif self.sort_key == "artist":
            results = sorted(results, key=lambda x: (x.proposed.artist or x.current.artist or "").lower(), reverse=reverse)
        elif self.sort_key == "album":
            results = sorted(results, key=lambda x: (x.proposed.album or x.current.album or "").lower(), reverse=reverse)
        elif self.sort_key == "year":
            results = sorted(results, key=lambda x: (_num_or_zero(x.proposed.year or x.current.year), _num_or_zero(x.proposed.track_number or x.current.track_number)), reverse=reverse)
        elif self.sort_key == "status":
            results = sorted(results, key=lambda x: x.status.value, reverse=reverse)
        elif self.sort_key == "score":
            results = sorted(results, key=lambda x: x.proposed.score, reverse=not reverse)
        elif self.sort_key == "id":
            results = sorted(results, key=lambda x: int(x.id) if x.id.isdigit() else x.id, reverse=reverse)

        return results

    def refresh_destination_paths(self):
        for t in self.tracks:
            t.target_path = compute_destination_path(
                source_file=t.file_path,
                source_root=self.source_directory,
                output_dir=self.output_directory,
                rename_organize=self.rename_organize,
                current=t.current,
                proposed=t.proposed,
                rename_to_title=self.rename_to_title,
            )
        self._resolve_target_collisions()

    def _resolve_target_collisions(self):
        """Give colliding destinations a deterministic " (2)", " (3)" suffix.

        Two staged tracks can legitimately want the same name (e.g. duplicate song
        titles during an in-place rename), so the planned path - which is what the
        inspector previews and what apply_changes writes to - must already be unique.
        """
        seen: Dict[str, int] = {}
        for t in self.tracks:
            target = t.target_path
            if not target or target == t.file_path:
                continue
            info = Path(target)
            key = os.path.normcase(str(info.parent)) + "|" + os.path.normcase(info.name)
            count = seen.get(key, 0) + 1
            seen[key] = count
            if count > 1:
                t.target_path = str(info.with_name(f"{info.stem} ({count}){info.suffix}"))

    async def intake_directory(self, folder_path: str = ""):
        """Backward-compatible intake for a single folder."""
        await self.intake_paths([folder_path] if folder_path else [], append=False)

    async def intake_paths(self, paths: List[str], append: bool = False):
        """
        Intake scan of one or multiple folders and audio files.
        If append is True (e.g. Ctrl + Drag & Drop), appends new tracks to the active workbench
        without clearing existing tracks or creating duplicates.
        Extracts Mutagen metadata in memory and stages tracks.
        """
        valid_paths = [p for p in (paths or []) if p and Path(p).exists()]
        if not valid_paths and not append:
            self.tracks.clear()
            self.tracks_by_id.clear()
            self.selected_track_id = None
            self.source_directory = ""
            self.refresh_destination_paths()
            self.update_metrics()
            self.status_message = "READY"
            self.notify()
            return

        if not valid_paths:
            return

        if len(valid_paths) == 1 and Path(valid_paths[0]).is_dir():
            if not append or not self.source_directory:
                self.source_directory = valid_paths[0]
        elif not append:
            self.source_directory = f"{len(valid_paths)} folders/items staged"

        # Check duplicate inflight load
        inflight_key = "|".join(sorted(valid_paths))
        if self._intake_inflight and self._intake_inflight == inflight_key:
            diag(f"[Staging] Ignoring duplicate load for {inflight_key}")
            return

        existing_norm_paths = set()
        if not append:
            self.tracks.clear()
            self.tracks_by_id.clear()
            self.selected_track_id = None
            self.album_cover_art = None
            self.album_cover_mime = "image/jpeg"
            self.progress_val = 0.0
            self.search_filter = ""
            self.status_filter = "ALL"
            self.active_context_filter = None
            start_index = 0
        else:
            existing_norm_paths = {os.path.normcase(t.file_path) for t in self.tracks}
            start_index = len(self.tracks)

        found_files: List[Path] = []
        try:
            for item in valid_paths:
                p_item = Path(item)
                if p_item.is_dir():
                    for root, _, files in os.walk(p_item):
                        for f in files:
                            p = Path(root) / f
                            if p.suffix.lower() in AUDIO_EXTENSIONS:
                                if os.path.normcase(str(p)) not in existing_norm_paths:
                                    found_files.append(p)
                                    existing_norm_paths.add(os.path.normcase(str(p)))
                elif p_item.is_file():
                    if p_item.suffix.lower() in AUDIO_EXTENSIONS:
                        if os.path.normcase(str(p_item)) not in existing_norm_paths:
                            found_files.append(p_item)
                            existing_norm_paths.add(os.path.normcase(str(p_item)))
        except Exception as e:
            self.log(f"Error enumerating files: {e}")
            self.refresh_destination_paths()
            self.update_metrics()
            self.notify()
            return

        if not found_files:
            if not append:
                self.refresh_destination_paths()
                self.update_metrics()
                self.status_message = "READY"
                self.log(f"Scan complete: No compatible audio files found in {valid_paths}.")
                self.notify()
            else:
                self.log("Scan complete: No new audio files to add.")
            return

        found_files.sort(key=lambda p: (p.parent, p.name.lower()))

        if not self.is_scanning and not self.is_applying:
            self.abort.reset()
        self._intake_generation += 1
        generation = self._intake_generation
        self._intake_inflight = inflight_key

        def _superseded() -> bool:
            return generation != self._intake_generation

        chunk_size = STAGING_WORKERS * 4
        pool = ThreadPoolExecutor(max_workers=STAGING_WORKERS, thread_name_prefix="fxsonic-staging")
        index = start_index
        try:
            if len(found_files) <= chunk_size:
                file_paths_str = [str(p) for p in found_files]
                read_meta = list(pool.map(read_track_metadata, file_paths_str))
                index = self._stage_tracks(found_files, read_meta, index)
            else:
                for start in range(0, len(found_files), chunk_size):
                    if self.abort.is_aborted or _superseded():
                        break
                    batch = found_files[start:start + chunk_size]
                    batch_str = [str(p) for p in batch]
                    try:
                        read_meta = await asyncio.to_thread(
                            lambda p=batch_str: list(pool.map(read_track_metadata, p))
                        )
                    except Exception as e:
                        self.log(f"Error reading tags: {e}")
                        break

                    if _superseded():
                        break

                    index = self._stage_tracks(batch, read_meta, index)
        finally:
            pool.shutdown(wait=False)
            if self._intake_inflight == inflight_key:
                self._intake_inflight = ""

        if _superseded():
            return

        if self.tracks and not self.selected_track_id:
            self.selected_track_id = self.tracks[0].id

        self.refresh_destination_paths()
        self.update_metrics()

        added_count = len(found_files)
        if self.abort.is_aborted:
            self.log(f"STAGING ABORTED • {len(self.tracks)} tracks currently staged")
        elif append:
            self.log(f"ADDED • {added_count} new tracks staged (Total: {len(self.tracks)})")
        else:
            self.log(f"STAGED • {len(self.tracks)} tracks loaded locally")

    def _stage_tracks(
        self,
        batch: List[Path],
        read_meta: List[tuple],
        start_index: int,
    ) -> int:
        """Turn one batch of tag reads into staging rows and return the new index.

        Rows are appended in file order, so ``track.id`` stays ``"1", "2", …`` - the
        numeric ids the whole UI (and the drop-zone audit) relies on.
        """
        index = start_index
        for file_path, (curr_meta, duration) in zip(batch, read_meta):
            if self.abort.is_aborted:
                break
            index += 1
            track_id = str(index)
            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = 0

            track = AudioTrack(
                id=track_id,
                file_path=str(file_path),
                file_name=file_path.name,
                file_size=file_size,
                duration=duration,
                current=curr_meta,
                status=TrackStatus.STAGED,
            )
            p_title = sanitize_metadata_text(curr_meta.title) if self.strip_junk_frames else curr_meta.title
            p_artist = sanitize_metadata_text(curr_meta.artist) if self.strip_junk_frames else curr_meta.artist
            p_album = sanitize_metadata_text(curr_meta.album) if self.strip_junk_frames else curr_meta.album
            p_album_artist = sanitize_metadata_text(curr_meta.album_artist) if self.strip_junk_frames else curr_meta.album_artist

            track.proposed = ProposedMetadata(
                title=p_title,
                artist=p_artist,
                album=p_album,
                album_artist=p_album_artist,
                year=curr_meta.year,
                track_number=curr_meta.track_number,
                disc_number=curr_meta.disc_number,
                genre=curr_meta.genre,
            )
            self.tracks.append(track)
            self.tracks_by_id[track_id] = track
        return index

    def detect_duplicates(self) -> List[List[AudioTrack]]:
        """
        Group tracks that appear to be duplicates based on:
        1. Chromaprint acoustic fingerprint (if both have fingerprints, duration diff <= 2s)
        2. Normalized (artist, title) + duration diff <= 2.5s
        3. Normalized filename stems (stripping track numbers, version suffixes) + duration diff <= 3.5s or matching artist
        4. Identical file size + duration diff <= 1s

        Ranks tracks in each group so group[0] is the highest quality primary track to keep.
        Marks secondary tracks with is_duplicate = True and selected = True.
        Returns list of duplicate groups (each group has >= 2 tracks).
        """
        groups: List[List[AudioTrack]] = []
        if len(self.tracks) < 2:
            return groups

        # Reset duplicate flags
        for t in self.tracks:
            t.is_duplicate = False
            t.duplicate_group_id = None

        def _normalize_name_stem(name: str) -> str:
            if not name:
                return ""
            stem = Path(name).stem if "." in name else name
            cleaned = re.sub(r"^\s*(?:\d+[\s._\-]+)+", "", stem)
            cleaned = re.sub(r"\s*[\(\[](?:\d+|copy|official\s*(?:audio|video)?|audio|video|lyrics|remaster(?:ed)?|live)[\)\]]", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"[^\w\s]", " ", cleaned).lower()
            return " ".join(cleaned.split())

        def _track_quality_score(track: AudioTrack) -> float:
            score = 0.0
            ext = Path(track.file_path).suffix.lower()
            if ext in {".flac", ".wav", ".aiff"}:
                score += 1000.0
            elif ext in {".m4a", ".aac"}:
                score += 500.0
            elif ext == ".mp3":
                score += 200.0
            score += min(float(track.file_size or 0) / (1024.0 * 1024.0), 100.0)
            curr, prop = track.current, track.proposed
            if prop.title or curr.title:
                score += 10.0
            if prop.artist or curr.artist:
                score += 10.0
            if prop.album or curr.album:
                score += 10.0
            if prop.artwork_data or curr.has_artwork:
                score += 15.0
            return score

        visited = set()
        group_idx = 0

        for i, t1 in enumerate(self.tracks):
            if t1.id in visited:
                continue
            group = [t1]
            dur1 = float(t1.duration or 0.0)
            art1 = (t1.proposed.artist or t1.current.artist or "").strip().lower()
            title1 = (t1.proposed.title or t1.current.title or Path(t1.file_name).stem).strip().lower()
            stem1 = _normalize_name_stem(t1.file_name)
            title1_norm = _normalize_name_stem(title1)

            for j in range(i + 1, len(self.tracks)):
                t2 = self.tracks[j]
                if t2.id in visited:
                    continue
                dur2 = float(t2.duration or 0.0)
                dur_diff = abs(dur1 - dur2) if dur1 > 0 and dur2 > 0 else 0.0
                art2 = (t2.proposed.artist or t2.current.artist or "").strip().lower()
                title2 = (t2.proposed.title or t2.current.title or Path(t2.file_name).stem).strip().lower()
                stem2 = _normalize_name_stem(t2.file_name)
                title2_norm = _normalize_name_stem(title2)

                is_dup = False
                # 1. Fingerprint match
                if t1.fingerprint and t2.fingerprint and t1.fingerprint == t2.fingerprint and dur_diff <= 2.0:
                    is_dup = True
                # 2. Exact Artist & Title & Duration match
                elif art1 and title1 and art1 == art2 and title1 == title2 and dur_diff <= 2.5:
                    is_dup = True
                # 3. Normalized filename stem match (across albums)
                elif stem1 and stem2 and stem1 == stem2 and len(stem1) >= 3 and (
                    (dur1 > 0 and dur2 > 0 and dur_diff <= 3.5)
                    or (art1 and art2 and art1 == art2)
                    or (t1.file_size > 0 and t1.file_size == t2.file_size)
                ):
                    is_dup = True
                # 4. Normalized title match with duration match
                elif title1_norm and title2_norm and title1_norm == title2_norm and len(title1_norm) >= 3 and (
                    (dur1 > 0 and dur2 > 0 and dur_diff <= 3.0)
                    or (art1 and art2 and art1 == art2)
                ):
                    is_dup = True
                # 5. File size match and identical stem
                elif t1.file_size > 0 and t1.file_size == t2.file_size and Path(t1.file_name).stem.lower() == Path(t2.file_name).stem.lower():
                    is_dup = True

                if is_dup:
                    group.append(t2)
                    visited.add(t2.id)

            if len(group) > 1:
                group.sort(key=_track_quality_score, reverse=True)
                group_idx += 1
                gid = f"DUP-{group_idx}"
                visited.add(group[0].id)
                group[0].duplicate_group_id = gid
                group[0].is_duplicate = False
                for secondary in group[1:]:
                    secondary.is_duplicate = True
                    secondary.duplicate_group_id = gid
                    secondary.selected = True
                groups.append(group)

        return groups

    def unstage_tracks(self, track_ids: List[str]):
        """Remove tracks from the active workbench by track ID (does not touch files on disk)."""
        to_remove = set(track_ids)
        if not to_remove:
            return
        self.tracks = [t for t in self.tracks if t.id not in to_remove]
        self.tracks_by_id = {t.id: t for t in self.tracks}
        if self.selected_track_id in to_remove:
            self.selected_track_id = self.tracks[0].id if self.tracks else None
        self.refresh_destination_paths()
        self.update_metrics()
        self.notify()

    def combine_albums(self, track_ids: List[str], target_album_name: str):
        """Standardize proposed album name across selected tracks to merge into a single album."""
        target_ids = set(track_ids)
        if not target_ids or not target_album_name:
            return
        for t in self.tracks:
            if t.id in target_ids:
                t.proposed.album = target_album_name
        self.refresh_destination_paths()
        self.notify()

    def consolidate_duplicates_to_album(self, groups: List[List[AudioTrack]], target_album_name: str):
        """
        Consolidates library into a single target album with UNIQUE files:
        1. Keeps only the primary (best quality) track for each duplicate group and unstages secondary copies.
        2. Assigns target_album_name to all remaining unique tracks.
        """
        if not target_album_name:
            return
        secondary_ids = [t.id for g in groups for t in g[1:]]
        to_remove = set(secondary_ids)

        self.tracks = [t for t in self.tracks if t.id not in to_remove]
        self.tracks_by_id = {t.id: t for t in self.tracks}
        if self.selected_track_id in to_remove:
            self.selected_track_id = self.tracks[0].id if self.tracks else None

        for t in self.tracks:
            t.proposed.album = target_album_name

        self.refresh_destination_paths()
        self.update_metrics()
        self.notify()

    def get_album_tracks_for(self, track: Optional[AudioTrack] = None) -> List[AudioTrack]:
        """
        Returns the subset of staged tracks belonging to the same album or folder as ``track``.
        If multiple folders or albums are staged, this ensures album-level actions
        (Edit Album, Replace Album Art, Copy Art to Album) only affect the specific album,
        not the entire staging library.
        """
        if not self.tracks:
            return []

        if track is None:
            if self.selected_track_id and self.selected_track_id in self.tracks_by_id:
                track = self.tracks_by_id[self.selected_track_id]
            else:
                track = self.tracks[0]

        # 1. If user has an active album context filter (SELECT BY: Album), respect that
        if self.select_by_mode == "Album" and self.active_context_filter:
            filter_album = self.active_context_filter.strip().lower()
            filtered = [
                t for t in self.tracks
                if (t.proposed.album or t.current.album or "").strip().lower() == filter_album
            ]
            if filtered:
                return filtered
        elif self.select_by_mode == "Folder" and self.active_context_filter:
            filter_folder = os.path.normcase(self.active_context_filter.strip().lower())
            filtered = [
                t for t in self.tracks
                if os.path.normcase(str(Path(t.file_path).parent).lower()) == filter_folder
            ]
            if filtered:
                return filtered

        track_dir = os.path.normcase(str(Path(track.file_path).parent))
        track_album = (track.proposed.album or track.current.album or "").strip().lower()

        # 2. Check if tracks match by album tag or by parent directory
        generic_names = {"unknown", "unknown album", "untitled", ""}
        if track_album and track_album not in generic_names:
            matched_tracks = [
                t for t in self.tracks
                if (t.proposed.album or t.current.album or "").strip().lower() == track_album
            ]
            if matched_tracks:
                return matched_tracks

        # Otherwise match by parent folder
        matched_tracks = [
            t for t in self.tracks
            if os.path.normcase(str(Path(t.file_path).parent)) == track_dir
        ]
        return matched_tracks if matched_tracks else [track]

    async def process_album(self):
        """
        Consensus-based album processing:
        Runs MusicBrainz consensus lookup, single CAA artwork fetch, tracklist matching,
        and only fingerprints unmatched/ambiguous tracks.

        The whole run is bound to ``self.abort``, so CANCEL / ABORT unwinds it at the
        next track boundary and kills any fpcalc that is mid-decode.
        """
        if not self.tracks:
            self.log("PROCESS CANCELLED: No tracks staged.")
            return

        self.is_scanning = True
        self.abort.reset()
        # Publish the token for this run: the resolver's stages (and the fpcalc pool
        # they drive) read it through core.control.
        control.bind(self.abort)
        aborted = False
        try:
            # Real progress: the resolver reports once per finalized track (see the
            # progress callback below), so no placeholder value is needed here.
            self.report_progress(0.0, "Searching release")
            self.log(f"Processing album with {len(self.tracks)} staged tracks...")

            try:
                art_bytes, art_mime = await resolve_album_consensus(
                    tracks=self.tracks,
                    source_dir=self.source_directory,
                    prefer_romanized=self.prefer_romanized,
                    auto_fetch_artwork=self.auto_fetch_artwork,
                    log=self.log,
                    progress=self.report_progress,
                )
                if art_bytes:
                    self.album_cover_art = art_bytes
                    self.album_cover_mime = art_mime
            except OperationAborted:
                aborted = True
                self.log("PROCESS ABORTED • Background identification stopped.")
            except Exception as e:
                self.log(f"Album processing error: {e}")
        finally:
            control.unbind(self.abort)
            self.is_scanning = False

        if aborted:
            # CANCEL / ABORT already reset the workbench; do not paint a completion
            # line (or a filled bar) over it.
            self.progress_val = 0.0
            self.notify()
            return

        self.refresh_destination_paths()
        self.update_metrics()
        self.progress_val = 1.0
        if "fingerprint" in self.progress_phase.lower():
            self.progress_phase = "Fingerprinting Complete"
        else:
            self.progress_phase = "Identification Complete"
        self.log(
            f"PROCESS COMPLETED • {self.count_verified} Identified • "
            f"{self.count_ambiguous} Ambiguous • {self.count_unmatched} Unmatched"
        )
        self.notify()

    async def scan_directory(self):
        """Backward-compatible entry point that ingests and processes album."""
        if not self.tracks:
            await self.intake_directory()
        await self.process_album()

    async def apply_changes(self):
        """
        Applies proposed metadata to disk - local file writes and renames ONLY.

        This path never fingerprints, never queries MusicBrainz/AcoustID and never
        downloads artwork: everything it needs is already staged on the track
        (``proposed`` metadata plus the cached album cover), so a batch no longer pays
        for lookup logic that already ran during the scan.

        Writes run in a background pool (8 workers, disk I/O bound); each task saves
        the tags and renames the file in the same unit of work, so the move is atomic
        per file.  The batch is awaited through ``asyncio.wait`` (never
        ``concurrent.futures.as_completed``, which would block the event loop and freeze
        the UI for the whole batch): the footer counter follows the work, the staging
        table is repainted at a coarse interval so freshly written tags appear, and it is
        refreshed once more when the batch is complete.
        """
        selected_tracks = [t for t in self.tracks if t.selected]
        if not selected_tracks:
            self.log("APPLY CANCELLED: No tracks selected.")
            return

        self.is_applying = True
        self.abort.reset()
        control.bind(self.abort)
        total = len(selected_tracks)
        done = 0
        written_count = 0
        failures = 0
        last_paint = 0.0
        last_table_refresh = time.monotonic()
        futures: Dict[Any, AudioTrack] = {}
        self.report_progress(0.0, "Applying tags")
        self.log(f"Applying tags and changes to {total} selected tracks...")

        def _write_one(track: AudioTrack) -> Optional[str]:
            """Worker task: surgically tag the file, then rename it (atomic per file)."""
            if self.abort.is_aborted:
                return None
            return write_track_metadata(
                source_path=track.file_path,
                target_path=track.target_path or track.file_path,
                proposed=track.proposed,
                strip_junk=self.strip_junk_frames,
                # Embed whatever this track carries (fetched art or a manual pick);
                # nothing is downloaded here.
                embed_artwork=bool(track.proposed.artwork_data),
            )

        pool = ThreadPoolExecutor(max_workers=APPLY_WORKERS, thread_name_prefix="fxsonic-apply")
        loop = asyncio.get_running_loop()
        try:
            for track in selected_tracks:
                futures[loop.run_in_executor(pool, _write_one, track)] = track

            pending = set(futures)
            while pending:
                # ``asyncio.wait`` yields to the event loop on every pass (and at least
                # every 0.25 s), so progress paints actually reach the browser and the
                # websocket heartbeat keeps ticking while the pool writes.
                completed, pending = await asyncio.wait(
                    pending, timeout=0.25, return_when=asyncio.FIRST_COMPLETED
                )
                for future in completed:
                    track = futures[future]
                    try:
                        written_path = future.result()
                    except Exception as e:
                        failures += 1
                        track.error_message = f"Write error: {e}"
                    else:
                        if written_path:
                            # The writer may have had to suffix a colliding name, so
                            # trust its result rather than the planned path.
                            # ``applied_metadata`` mirrors exactly what was written, so no
                            # second file read is needed to refresh the staging row.
                            track.current = applied_metadata(
                                track.current, track.proposed, self.strip_junk_frames
                            )
                            track.file_path = written_path
                            track.file_name = Path(written_path).name
                            track.target_path = written_path
                            written_count += 1
                    done += 1

                if self.abort.is_aborted:
                    break

                now = time.monotonic()
                if done and now - last_paint >= PROGRESS_UI_THROTTLE_SECONDS:
                    last_paint = now
                    # Numbers only: one push per ~100 ms instead of a full table
                    # re-render per file.
                    self.report_progress(done / total, "Applying tags", refresh=False)
                if written_count and now - last_table_refresh >= BATCH_TABLE_REFRESH_SECONDS:
                    # Coarse full repaint so the freshly written tags become visible
                    # without pushing a table update for every single file.
                    last_table_refresh = now
                    self.notify()
        finally:
            if self.abort.is_aborted:
                for future in futures:
                    if not future.done():
                        future.cancel()
            pool.shutdown(wait=True, cancel_futures=self.abort.is_aborted)
            control.unbind(self.abort)
            self.is_applying = False

        if self.abort.is_aborted:
            self.progress_val = 0.0
            self.log(f"APPLY ABORTED • {written_count} of {total} tracks were written.")
            self.notify()
            return

        self.update_metrics()
        self.refresh_destination_paths()
        self.progress_val = 1.0
        self.progress_phase = "Apply Complete"
        if failures:
            self.log(
                f"APPLY CHANGES COMPLETED • {written_count} file(s) written • {failures} error(s)."
            )
        else:
            self.log(
                f"APPLY CHANGES COMPLETED • All {written_count} files written successfully."
            )
        self.notify()

    def cancel_task(self):
        """
        Clean reset on CANCEL / ABORT:
          - Signals the abort token immediately and kills any running fpcalc child, so
            scanning, fingerprinting, network lookups and tag writing stop at once
            instead of finishing the current track.
          - Clears the staging table completely (tracks.clear()).
          - Resets all counters (0 Identified, 0 Ambiguous, 0 Errors) and the progress bar.
          - Clears the selection, which reverts the Inspector to 'NO TRACK SELECTED'.
        """
        self.request_abort()
        control.unbind(self.abort)

        self.tracks.clear()
        self.tracks_by_id.clear()
        self.selected_track_id = None
        self.album_cover_art = None
        self.album_cover_mime = "image/jpeg"

        self.progress_val = 0.0
        self.progress_phase = "Fingerprinting"
        self.count_verified = 0
        self.count_ambiguous = 0
        self.count_unmatched = 0
        self.count_errors = 0

        self.status_message = "READY • Awaiting directory selection"
        self.log("CANCEL / ABORT • Reset state and cleared staging table.")
        self.notify()

