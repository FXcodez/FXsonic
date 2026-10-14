"""
Tagging and Scrubbing Engine using Mutagen
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import mutagen
from mutagen.id3 import (
    ID3,
    ID3NoHeaderError,
    TIT2,  # Title
    TPE1,  # Artist
    TALB,  # Album
    TPE2,  # Album Artist
    TDRC,  # Date/Year
    TRCK,  # Track number
    TPOS,  # Disc number
    TCON,  # Genre
    APIC,  # Attached Picture
    ID3TimeStamp,
)
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

from .models import TrackMetadata, ProposedMetadata, AudioTrack
from .resolver import sanitize_metadata_text

# Junk frame IDs according to business rules:
# COMM (Comments), WXXX / WOAR (URLs/Commercial), TSSE / TENC (Encoder), PRIV (Private), etc.
JUNK_FRAME_PREFIXES = ("COMM", "WXXX", "WOAR", "WCOM", "WOAS", "WORS", "WPAY", "WPUB", "TSSE", "TENC", "PRIV", "UFID", "MCDI")
CANONICAL_FRAME_PREFIXES = ("TIT2", "TPE1", "TALB", "TPE2", "TDRC", "TYER", "TRCK", "TPOS", "TCON", "APIC")


def read_track_metadata(file_path: str) -> Tuple[TrackMetadata, float]:
    """
    Read ID3 tags and duration from an audio file.
    """
    meta = TrackMetadata()
    duration = 0.0
    path = Path(file_path)

    try:
        try:
            audio = mutagen.File(str(path))
            if audio is not None and audio.info is not None:
                duration = getattr(audio.info, "length", 0.0)
        except Exception:
            pass

        # Try to load ID3 tags
        try:
            tags = ID3(str(path))
        except (ID3NoHeaderError, Exception):
            tags = None

        if tags:
            # Parse canonical fields
            if "TIT2" in tags:
                meta.title = str(tags["TIT2"].text[0]) if tags["TIT2"].text else ""
            if "TPE1" in tags:
                meta.artist = str(tags["TPE1"].text[0]) if tags["TPE1"].text else ""
            if "TALB" in tags:
                meta.album = str(tags["TALB"].text[0]) if tags["TALB"].text else ""
            if "TPE2" in tags:
                meta.album_artist = str(tags["TPE2"].text[0]) if tags["TPE2"].text else ""
            if "TDRC" in tags:
                meta.year = str(tags["TDRC"].text[0]) if tags["TDRC"].text else ""
            elif "TYER" in tags:
                meta.year = str(tags["TYER"].text[0]) if tags["TYER"].text else ""
            if "TRCK" in tags:
                meta.track_number = str(tags["TRCK"].text[0]) if tags["TRCK"].text else ""
            if "TPOS" in tags:
                meta.disc_number = str(tags["TPOS"].text[0]) if tags["TPOS"].text else ""
            if "TCON" in tags:
                meta.genre = str(tags["TCON"].text[0]) if tags["TCON"].text else ""

            # Check APIC
            for key in tags.keys():
                if key.startswith("APIC"):
                    meta.has_artwork = True
                    break

            # Find junk frames
            junk_list = []
            for frame_id in tags.keys():
                fid = frame_id[:4]
                if fid in JUNK_FRAME_PREFIXES or not any(frame_id.startswith(c) for c in CANONICAL_FRAME_PREFIXES):
                    frame_obj = tags[frame_id]
                    desc = getattr(frame_obj, "desc", "")
                    val = ""
                    if hasattr(frame_obj, "text") and frame_obj.text:
                        val = str(frame_obj.text[0])
                    elif hasattr(frame_obj, "url"):
                        val = str(frame_obj.url)
                    elif hasattr(frame_obj, "data"):
                        val = f"<{len(frame_obj.data)} bytes binary data>"
                    junk_list.append(f"{frame_id}: {desc} ({val})" if desc else f"{frame_id}: {val}")
            meta.junk_frames = junk_list

    except Exception as e:
        # File might not have tags or might be corrupted
        pass

    return meta, duration


def extract_current_artwork(file_path: str) -> Optional[Tuple[bytes, str]]:
    """
    Extract APIC image bytes and mime type from file.
    """
    try:
        tags = ID3(file_path)
        for key in tags.keys():
            if key.startswith("APIC"):
                frame: APIC = tags[key]
                return frame.data, frame.mime or "image/jpeg"
    except Exception:
        pass
    return None


def _unique_sibling_path(candidate: Path, source: Path, limit: int = 100) -> Path:
    """Return ``candidate``, or a ``" (2)"``/``" (3)"``… sibling that does not collide.

    Only used for in-place renames, where silently overwriting a *different* file
    would destroy data.  ``source`` itself is never treated as a collision.
    """
    if not candidate.exists():
        return candidate
    if os.path.normcase(str(candidate)) == os.path.normcase(str(source)):
        return candidate
    for index in range(2, limit + 1):
        alternative = candidate.with_name(f"{candidate.stem} ({index}){candidate.suffix}")
        if not alternative.exists():
            return alternative
    return candidate


def applied_metadata(
    current: Optional[TrackMetadata],
    proposed: ProposedMetadata,
    strip_junk: bool = True,
    embedded_artwork: bool = False,
) -> TrackMetadata:
    """Predict what :func:`write_track_metadata` just wrote, without re-reading it.

    The writer only sets a text frame when the proposal carries a value, so an empty
    proposal leaves the file's own value in place.  Re-building the same result here
    means APPLY CHANGES can update the staging rows instantly instead of parsing every
    file a second time (the old behaviour, which doubled the batch cost).
    """
    base = current if current is not None else TrackMetadata()

    def pick(new_value: str, old_value: str) -> str:
        value = sanitize_metadata_text(new_value) if strip_junk else (new_value or "")
        return value or (old_value or "")

    return TrackMetadata(
        title=pick(proposed.title, base.title),
        artist=pick(proposed.artist, base.artist),
        album=pick(proposed.album, base.album),
        album_artist=pick(proposed.album_artist, base.album_artist),
        year=pick(proposed.year, base.year),
        track_number=pick(proposed.track_number, base.track_number),
        disc_number=pick(proposed.disc_number, base.disc_number),
        genre=pick(proposed.genre, base.genre),
        has_artwork=False if proposed.artwork_info == "Removed" else bool(embedded_artwork or base.has_artwork),
        junk_frames=[] if strip_junk else list(base.junk_frames),
    )


def _set_text_frame(tags, frame_id: str, frame_cls, value: str, encoding: int) -> bool:
    """Write one text frame, but only when it actually differs.

    Returns ``True`` when the frame was touched.  Leaving identical frames untouched
    is what keeps the ID3 header (and its padding) in place instead of forcing a full
    audio-stream rewrite for a file that is already correct.
    """
    if not value:
        return False
    existing = tags.get(frame_id)
    if existing is not None:
        text = getattr(existing, "text", None) or []
        if len(text) == 1 and str(text[0]) == str(value):
            return False
    tags[frame_id] = frame_cls(encoding=encoding, text=[value])
    return True


def _artwork_unchanged(tags, artwork_bytes: bytes) -> bool:
    """True when the file already carries exactly these artwork bytes."""
    for key in list(tags.keys()):
        if not key.startswith("APIC"):
            continue
        try:
            if bytes(tags[key].data) == bytes(artwork_bytes):
                return True
        except Exception:
            continue
    return False


def write_track_metadata(
    source_path: str,
    target_path: str,
    proposed: ProposedMetadata,
    strip_junk: bool = True,
    embed_artwork: bool = True,
    custom_artwork_data: Optional[bytes] = None,
    custom_artwork_mime: str = "image/jpeg",
) -> str:
    """
    Write updated ID3 tags, strip junk frames, embed artwork, and handle destination routing.
    Mutagen strictly encodes in UTF-8 (encoding=3) for ID3v2.4.

    Routing:
      * identical path            -> the file is tagged in place.
      * same folder, other name   -> the file is *renamed in place*: tagged first,
                                     then moved with ``os.replace`` (atomic, no copy,
                                     and no leftover original).
      * different folder          -> copied to the destination first, then tagged
                                     there (the source is intentionally left as-is).

    :return: the path that was actually written; callers must use this rather than
        ``target_path``, because a colliding name may have been suffixed.
    """
    src = Path(source_path).resolve()
    dst = Path(target_path).resolve()

    rename_after: Optional[Path] = None
    if os.path.normcase(str(src)) == os.path.normcase(str(dst)):
        active_file = str(src)
    elif src.parent == dst.parent:
        dst = _unique_sibling_path(dst, src)
        if os.path.normcase(str(dst)) == os.path.normcase(str(src)):
            active_file = str(src)
        else:
            rename_after = dst
            active_file = str(src)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        active_file = str(dst)

    # Open or create ID3 tags (in place - the audio stream is never touched)
    try:
        tags = ID3(active_file)
    except ID3NoHeaderError:
        tags = ID3()

    changed = False

    if strip_junk:
        # Purge junk / non-canonical frames.  Only the junk *frames* are removed;
        # the canonical ones (and any artwork) are left exactly as they are.
        keys_to_remove = []
        for frame_id in list(tags.keys()):
            fid = frame_id[:4]
            if fid in JUNK_FRAME_PREFIXES or not any(frame_id.startswith(c) for c in CANONICAL_FRAME_PREFIXES):
                keys_to_remove.append(frame_id)
        for k in keys_to_remove:
            del tags[k]
        changed = changed or bool(keys_to_remove)

    # UTF-8 encoding is 3 in ID3v2.4
    ENC_UTF8 = 3

    title_val = sanitize_metadata_text(proposed.title) if strip_junk else proposed.title
    artist_val = sanitize_metadata_text(proposed.artist) if strip_junk else proposed.artist
    album_val = sanitize_metadata_text(proposed.album) if strip_junk else proposed.album
    album_artist_val = sanitize_metadata_text(proposed.album_artist) if strip_junk else proposed.album_artist

    # Target frames are touched only when their value really changes.
    changed |= _set_text_frame(tags, "TIT2", TIT2, title_val, ENC_UTF8)
    changed |= _set_text_frame(tags, "TPE1", TPE1, artist_val, ENC_UTF8)
    changed |= _set_text_frame(tags, "TALB", TALB, album_val, ENC_UTF8)
    changed |= _set_text_frame(tags, "TPE2", TPE2, album_artist_val, ENC_UTF8)
    changed |= _set_text_frame(tags, "TDRC", TDRC, proposed.year, ENC_UTF8)
    changed |= _set_text_frame(tags, "TRCK", TRCK, proposed.track_number, ENC_UTF8)
    changed |= _set_text_frame(tags, "TPOS", TPOS, proposed.disc_number, ENC_UTF8)
    changed |= _set_text_frame(tags, "TCON", TCON, proposed.genre, ENC_UTF8)

    # Artwork handling - existing APIC frames are only replaced when the new artwork
    # is genuinely different (identical bytes are left alone). If artwork was removed,
    # purge existing APIC frames.
    if proposed.artwork_info == "Removed":
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        if apic_keys:
            for k in apic_keys:
                del tags[k]
            changed = True
    else:
        artwork_bytes = custom_artwork_data or proposed.artwork_data
        artwork_mime = custom_artwork_mime if custom_artwork_data else proposed.artwork_mime

        if embed_artwork and artwork_bytes and not _artwork_unchanged(tags, artwork_bytes):
            for k in list(tags.keys()):
                if k.startswith("APIC"):
                    del tags[k]

            tags["APIC"] = APIC(
                encoding=ENC_UTF8,
                mime=artwork_mime,
                type=3,  # Cover (front)
                desc="Cover",
                data=artwork_bytes,
            )
            changed = True

    if changed:
        # Save as ID3v2.4 with UTF-8, then rename in the same task (atomic move).
        tags.save(active_file, v2_version=4)

    if rename_after is not None:
        os.replace(active_file, rename_after)
        active_file = str(rename_after)

    return active_file
