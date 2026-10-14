"""
Filesystem Routing, Destination Path Computation & Sanitization
"""

import re
from pathlib import Path
from .models import ProposedMetadata, TrackMetadata


def sanitize_filename(name: str, fallback: str = "Unknown") -> str:
    r"""
    Purges illegal filesystem characters for Windows, Linux, macOS:
    \ / : * ? " < > |

    :param fallback: value returned when nothing usable remains (pass ``""`` when
        the caller wants to detect that case instead of getting a placeholder).
    """
    if not name:
        return fallback
    # Replace illegal characters with underscore or hyphen
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name)
    # Strip leading/trailing spaces and dots
    sanitized = sanitized.strip(". ")
    return sanitized or fallback


def title_based_filename(current: TrackMetadata, proposed: ProposedMetadata, extension: str) -> str:
    """Return ``"<Title><ext>"`` for an in-place rename, or ``""`` when unusable.

    The song title tag is the single source for the name; when neither the proposed
    nor the current metadata carries a usable title (or it consists solely of
    characters that must be stripped) the original filename has to be kept.
    """
    title = sanitize_filename(proposed.title or current.title or "", fallback="")
    if not title:
        return ""
    return f"{title}{extension}"


def compute_destination_path(
    source_file: str,
    source_root: str,
    output_dir: str,
    rename_organize: bool,
    current: TrackMetadata,
    proposed: ProposedMetadata,
    rename_to_title: bool = False,
) -> str:
    """
    Calculates target file path according to business rules:
    1. No Output Directory Selected:
       1a. rename_to_title is TRUE -> rename in place to "<Title><ext>"
       1b. otherwise             -> in-place overwrite, source_file unchanged.
    2. Output Directory Selected AND rename_organize is FALSE:
       Compute relative path from source_root and recreate in output_dir.
    3. Output Directory Selected AND rename_organize is TRUE:
       Pattern: {Output_Dir}/{Artist}/{Year} - {Album}/{Track_Number}. {Title}.{ext}
    """
    src_path = Path(source_file).resolve()
    ext = src_path.suffix

    if not output_dir or not output_dir.strip():
        # In-place
        if rename_to_title:
            new_name = title_based_filename(current, proposed, ext)
            if new_name and new_name != src_path.name:
                return str(src_path.with_name(new_name))
        return str(src_path)

    out_base = Path(output_dir).resolve()

    if not rename_organize:
        # Preserve relative directory structure
        try:
            rel = src_path.relative_to(Path(source_root).resolve())
            return str(out_base / rel)
        except Exception:
            return str(out_base / src_path.name)

    # Rename & Organize is TRUE
    artist = sanitize_filename(proposed.artist or current.artist or "Unknown Artist")
    album = sanitize_filename(proposed.album or current.album or "Unknown Album")
    year = sanitize_filename(proposed.year or current.year or "")
    track_no = sanitize_filename(proposed.track_number or current.track_number or "")
    title = sanitize_filename(proposed.title or current.title or src_path.stem)

    # Zero pad track number if numeric
    if track_no.isdigit():
        track_no = f"{int(track_no):02d}"

    album_folder = f"{year} - {album}" if year else album
    track_prefix = f"{track_no}. " if track_no else ""
    final_filename = f"{track_prefix}{title}{ext}"

    dest_file = out_base / artist / album_folder / final_filename
    return str(dest_file)
