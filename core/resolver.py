"""
Metadata Resolver via MusicBrainz, AcoustID & Cover Art Archive

Zero-account / zero-configuration pipeline. FXsonic ships with AcoustID's public
client key and MusicBrainz' documented user-agent, so a fresh install can
identify tracks without the user creating an account, logging in or pasting a key.

Resolution runs in three stages:
    Stage 1 - MusicBrainz text search (fast, key-less) when local Artist/Title tags exist.
    Stage 2 - Chromaprint fingerprint (fpcalc) -> AcoustID lookup -> MusicBrainz release.
    Stage 3 - Front cover art from the Cover Art Archive for the resolved release MBID.

Every step emits a clear terminal log (mirrored into the UI ticker) so network or
parsing problems are immediately visible.
"""

import asyncio
import collections
import difflib
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable

import httpx
import musicbrainzngs
from PIL import Image

from . import control
from .control import AbortController, OperationAborted
from .models import AudioTrack, TrackMetadata, ProposedMetadata, TrackStatus
from .fingerprint import (
    FPCALC_ANALYSIS_LENGTH_SECONDS,
    compute_audio_fingerprint,
    fingerprint_tracks_parallel,
    recommended_fpcalc_workers,
)

PROMO_PATTERNS = [
    re.compile(r'(?i)\s*[\(\[\{]?(?:https?:\/\/)?(?:www\.)?[\w\.-]+\.(?:com|info|org|net|me|in|co|cc|vip|biz|xyz|top|site|link)[\)\]\}]?'),
    re.compile(r'(?i)\|\s*[\w\.-]+\.(?:info|com|net|org|in|me|cc|vip)'),
    re.compile(r'(?i)[\(\[\{]?(?:mp3wale|songspk|pagalworld|pagalsongs|djmaza|wapking|pendujatt|freshmaza|indiamp3|webmusic)[\)\]\}]?'),
    re.compile(r'\s*[\(\[\{]\s*[\)\]\}]'),
]


def sanitize_metadata_text(text: str) -> str:
    """Scrubs promotional site tags, bracketed URLs, and domain watermarks."""
    if not text:
        return ""
    result = text
    for pattern in PROMO_PATTERNS:
        result = pattern.sub('', result)
    result = re.sub(r'\s*[\|\-–—]+\s*$', '', result)
    result = re.sub(r'^\s*[\|\-–—]+\s*', '', result)
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


LOWERCASE_WORDS = {
    "a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to",
    "from", "by", "with", "in", "of", "as", "into", "vs", "v"
}

ROMAN_NUMERALS = {
    "i": "I", "ii": "II", "iii": "III", "iv": "IV", "v": "V", "vi": "VI",
    "vii": "VII", "viii": "VIII", "ix": "IX", "x": "X", "xi": "XI", "xii": "XII"
}

SPECIAL_ACRONYMS = {
    "dj": "DJ", "ep": "EP", "lp": "LP", "vip": "VIP", "ost": "OST",
    "tv": "TV", "fm": "FM", "am": "AM", "cd": "CD", "uk": "UK", "us": "US", "usa": "USA"
}


def smart_capitalize_word(word: str, is_first: bool = False, is_last: bool = False) -> str:
    if not word:
        return ""
    lower = word.lower()

    # Check Roman numerals or special acronyms (strip punctuation surrounding word)
    clean_w = re.sub(r"^[^\w]+|[^\w]+$", "", lower)
    if clean_w in ROMAN_NUMERALS:
        return word.replace(clean_w, ROMAN_NUMERALS[clean_w])
    if clean_w in SPECIAL_ACRONYMS:
        return word.replace(clean_w, SPECIAL_ACRONYMS[clean_w])

    if not is_first and not is_last and lower in LOWERCASE_WORDS:
        return lower

    # Handle contractions: don't, can't, it's, you're, etc.
    if "'" in word or "’" in word:
        parts = re.split(r"(['’])", word)
        res = []
        for i, p in enumerate(parts):
            if i == 0:
                res.append(p.capitalize())
            elif p in ("'", "’"):
                res.append(p)
            else:
                if p.lower() in ("s", "t", "d", "re", "ll", "ve", "m"):
                    res.append(p.lower())
                elif p.lower() == "clock":
                    res.append("Clock")
                else:
                    res.append(p.lower())
        return "".join(res)

    return word.capitalize()


def smart_title_case(text: str) -> str:
    if not text:
        return ""
    # Split text while preserving spaces and delimiter characters
    tokens = re.split(r"(\s+|[-–—:()\[\]/])", text)
    processed = []

    # Identify indices of meaningful words
    delimiters = {"-", "–", "—", ":", "(", ")", "[", "]", "/"}
    word_indices = [
        i for i, t in enumerate(tokens)
        if t and not t.isspace() and t not in delimiters
    ]
    first_idx = word_indices[0] if word_indices else -1
    last_idx = word_indices[-1] if word_indices else -1

    for i, token in enumerate(tokens):
        if not token or token.isspace() or token in delimiters:
            processed.append(token)
            continue

        # Check if preceding delimiter triggers capitalization (colon, dash, open paren/bracket)
        prev_is_boundary = False
        j = i - 1
        while j >= 0:
            if tokens[j] and not tokens[j].isspace():
                if tokens[j] in (":", "-", "–", "—", "(", "["):
                    prev_is_boundary = True
                break
            j -= 1

        is_first = (i == first_idx) or prev_is_boundary
        is_last = (i == last_idx)
        processed.append(smart_capitalize_word(token, is_first, is_last))

    return "".join(processed)


def clean_track_title(title: str, album: str = "") -> str:
    """
    Cleans a track title:
    1. Strips leading track numbers like '02 - ', '01. ', '1 - ', 'Track 01 '
    2. Strips trailing (Album Name) tags, [Album Name] tags, or common trailing tags
    3. Applies Smart Title Case
    """
    if not title:
        return ""
    t = title.strip()

    # 1. Strip leading track numbers
    t = re.sub(
        r"^(?:track\s*)?(?:[a-zA-Z]?\d{1,3}(?:-\d{1,3})?[\s._\-–—:]+|\d{1,3}\s+)",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = t.strip(" ._-–—:")

    # 2. Strip trailing (Album Name) tags
    if album and len(album.strip()) > 1:
        alb = album.strip()
        pat = (
            r"(?i)\s*[\(\[\-–—]\s*(?:from\s+)?[\"'\s]*"
            + re.escape(alb)
            + r"[\"'\s]*[\)\]]?\s*$"
        )
        t = re.sub(pat, "", t)

    # Strip common trailing junk tags
    t = re.sub(
        r"(?i)\s*[\(\[]\s*(?:official\s*(?:music\s*)?video|official\s*audio|album\s*version|single\s*version|lyrics?\s*video|audio|full\s*album|remaster(?:ed)?(?:\s*\d{4})?)\s*[\)\]]\s*$",
        "",
        t,
    )
    t = t.strip(" ._-–—:")

    # 3. Apply smart title case
    return smart_title_case(t)


def optimize_cover_art(image_bytes: bytes, max_size: int = 1000) -> Tuple[bytes, str]:
    """Resizes in-memory image to max 1000x1000 using Pillow to save memory/storage."""
    if not image_bytes:
        return image_bytes, "image/jpeg"
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img_format = img.format or "JPEG"
            if img_format.upper() not in ("JPEG", "PNG", "WEBP"):
                img_format = "JPEG"
            if img.width > max_size or img.height > max_size:
                if img.mode in ("RGBA", "LA", "P") and img_format.upper() == "JPEG":
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                    img = rgb_img
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                buf = BytesIO()
                img.save(buf, format=img_format, quality=85)
                mime = "image/png" if img_format.upper() == "PNG" else "image/jpeg"
                return buf.getvalue(), mime
            mime = "image/png" if img_format.upper() == "PNG" else "image/jpeg"
            return image_bytes, mime
    except Exception:
        return image_bytes, "image/jpeg"

# --------------------------------------------------------------------------- #
# Public, zero-configuration credentials
# --------------------------------------------------------------------------- #
# AcoustID's official public client key (the application key used throughout the
# AcoustID API documentation). No user account, login or key entry required.
ACOUSTID_CLIENT_KEY = "cSpUJKpD"

APP_NAME = "FXsonic"
APP_VERSION = "0.1.5"
APP_CONTACT = "https://github.com/fxdesignz/fxsonic"

# MusicBrainz text search scoring at or above this threshold is high confidence and
# lets FXsonic skip the (slower) acoustic fingerprint stage entirely.
MIN_TEXT_SCORE = 0.60

#: How many AcoustID lookups the fingerprint fallback runs at once.  AcoustID is a
#: public HTTP API with a generous per-second budget, so a small window keeps the
#: fallback from serialising one request per track without hammering the service.
NETWORK_LOOKUP_CONCURRENCY = 6

ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"

# Optional callback used to mirror terminal logs into the UI (FXsonicState.log).
LogFn = Optional[Callable[[str], None]]

# Optional progress reporter: called with a fraction (0.0 - 1.0) and a phase label,
# so the footer bar can follow the identification pipeline track by track.
ProgressFn = Optional[Callable[[float, str], None]]


def _report(progress: ProgressFn, value: float, phase: str) -> None:
    """Hand a progress update to the caller without ever breaking identification."""
    if progress is None:
        return
    try:
        progress(max(0.0, min(1.0, float(value))), phase)
    except Exception:
        pass



def _configure_musicbrainz() -> None:
    """
    Initializes the musicbrainzngs User-Agent and rate limit.

    Idempotent: invoked at import time *and* before every lookup call so the
    required User-Agent and the strict 1 request / second limit are always active.
    """
    musicbrainzngs.set_useragent(APP_NAME, APP_VERSION, APP_CONTACT)
    musicbrainzngs.set_rate_limit(limit_or_interval=1.0, new_requests=1)


# Configure as early as possible - module import happens before any lookup.
_configure_musicbrainz()


def _emit(message: str, log: LogFn = None) -> None:
    """
    Emits a clear terminal log line for one pipeline step.

    When a UI log callback is supplied (``FXsonicState.log``) it is used, and that
    method is responsible for printing to the terminal. Otherwise the message is
    printed directly so headless/CLI usage still gets full visibility.
    """
    if log is not None:
        try:
            log(message)
            return
        except Exception:
            pass
    print(message, flush=True)


class MusicBrainzRateLimiter:
    """
    Enforces the strict 1 request per second MusicBrainz rate limit on top of the
    limit built into ``musicbrainzngs`` (belt-and-braces for batched scans).

    The wait is interruptible: it re-checks the run's abort token every 100 ms, so a
    CANCEL / ABORT during a rate-limit pause is honoured immediately instead of after
    the full interval.  The signature deliberately stays ``wait()`` - the token is read
    from the active run (see :mod:`core.control`).
    """

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.last_call = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        token = control.bound()
        async with self.lock:
            if token is not None:
                token.check()
            while True:
                elapsed = time.time() - self.last_call
                if elapsed >= self.interval:
                    break
                await asyncio.sleep(min(self.interval - elapsed, 0.1))
                if token is not None:
                    token.check()
            self.last_call = time.time()


mb_limiter = MusicBrainzRateLimiter(1.1)

# Latin letters + Latin-1 Supplement, Latin Extended-A/B and Latin Extended
# Additional (used to detect native vs. romanized script aliases).
_LATIN_ONLY_RE = re.compile(r"^[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]*$")


def is_latin_script(text: str) -> bool:
    """
    Checks whether the alphabetic characters of ``text`` are all Latin script.
    """
    if not text:
        return True
    letters = "".join(ch for ch in text if ch.isalpha())
    return bool(_LATIN_ONLY_RE.match(letters))


def select_script_alias(aliases: List[Dict[str, Any]], prefer_romanized: bool, default_val: str) -> str:
    """
    Selects either a native-script alias or a Latin / romanized alias.
    """
    if not aliases:
        return default_val

    if prefer_romanized:
        # Prefer a transliteration / search hint, otherwise any Latin alias.
        for a in aliases:
            name = a.get("alias", "")
            a_type = a.get("type", "")
            if a_type in ("transliteration", "search hint") or is_latin_script(name):
                return name
        return default_val
    else:
        # Prioritize the primary non-Latin native-script alias.
        for a in aliases:
            if a.get("primary") or a.get("type") == "Artist name":
                return a.get("alias", default_val)
        return default_val


# --------------------------------------------------------------------------- #
# MusicBrainz / AcoustID payload helpers
# --------------------------------------------------------------------------- #
def _text_score(recording: Dict[str, Any]) -> int:
    """Extracts the MusicBrainz search relevance score (0-100) from a recording."""
    try:
        return int(recording.get("ext:score", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _release_year(release: Dict[str, Any]) -> str:
    """
    Extracts a 4-digit year from either MusicBrainz (``"date": "1997-01-20"``) or
    AcoustID (``"date": {"year": 1997}``) release payloads.
    """
    date = release.get("date")
    if isinstance(date, dict):
        year = date.get("year")
        return str(year) if year else ""
    if isinstance(date, str):
        return date[:4]
    return ""


def parse_full_artist_credit(
    credit_list: Optional[Any],
    prefer_romanized: bool = True,
    fallback: str = "",
) -> str:
    """
    Combines all collaborating or featured artists from artist-credit using native join phrases.
    Preserves multi-artist credits like 'Mellow D | Mika Singh' or 'Artist A feat. Artist B'.
    """
    if not credit_list:
        return fallback
    if isinstance(credit_list, str):
        return credit_list.strip() or fallback
    if isinstance(credit_list, dict):
        credit_list = [credit_list]
    parts = []
    for credit in credit_list:
        if isinstance(credit, dict):
            artist_obj = credit.get("artist") or {}
            if isinstance(artist_obj, dict):
                canonical = artist_obj.get("name", "")
                aliases = artist_obj.get("alias-list") or []
            elif isinstance(artist_obj, str):
                canonical = artist_obj
                aliases = []
            else:
                canonical = ""
                aliases = []
            credited = credit.get("name", "")
            if aliases:
                name = select_script_alias(aliases, prefer_romanized, canonical or credited)
            else:
                name = (canonical or credited) if prefer_romanized else (credited or canonical)
            join_phrase = credit.get("joinphrase", "")
            parts.append(name + join_phrase)
        elif isinstance(credit, str):
            parts.append(credit)
    res = "".join(parts).strip()
    return res or fallback


# Backward-compatible alias
_first_artist_name = parse_full_artist_credit


def _release_mediums(release: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalizes the ``medium-list`` (MusicBrainz) / ``mediums`` (AcoustID) shapes."""
    mediums = release.get("medium-list")
    if not mediums:
        mediums = release.get("mediums")
    return mediums or []


def _medium_tracks(medium: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalizes the ``track-list`` (MusicBrainz) / ``tracks`` (AcoustID) shapes."""
    tracks = medium.get("track-list")
    if not tracks:
        tracks = medium.get("tracks")
    return tracks or []


def _pick_release(
    release_list: Optional[List[Dict[str, Any]]],
    recording_title: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Chooses the most useful release: the first one that actually contains the
    matched recording title, otherwise the first release carrying a date,
    otherwise the first release with an MBID.
    """
    candidates = [
        r for r in (release_list or [])
        if isinstance(r, dict) and r.get("id")
    ]
    if not candidates:
        return None

    target = (recording_title or "").strip().lower()
    if target:
        for release in candidates:
            for medium in _release_mediums(release):
                for track in _medium_tracks(medium):
                    if (track.get("title") or "").strip().lower() == target:
                        return release

    for release in candidates:
        if _release_year(release):
            return release
    return candidates[0]


def _track_number_from_release(release: Dict[str, Any], recording_title: str = "") -> Tuple[str, str]:
    """
    Returns ``(track_number, disc_number)`` for the matched recording title,
    falling back to the first track of the first medium.
    """
    target = (recording_title or "").strip().lower()
    fallback: Tuple[str, str] = ("", "1")

    for medium in _release_mediums(release):
        disc_no = str(medium.get("position") or "1")
        tracks = _medium_tracks(medium)
        for track in tracks:
            number = str(track.get("number") or track.get("position") or "")
            if target and (track.get("title") or "").strip().lower() == target:
                return number, disc_no
        if fallback == ("", "1") and tracks:
            first = tracks[0]
            fallback = (str(first.get("number") or first.get("position") or ""), disc_no)

    return fallback


def _seed_from_current(current: Optional[TrackMetadata]) -> ProposedMetadata:
    """
    Seeds the proposal with the file's existing tags so a failed lookup never
    destroys local metadata (matches the previous pipeline behavior).
    """
    if current is None:
        return ProposedMetadata()
    return ProposedMetadata(
        title=current.title,
        artist=current.artist,
        album=current.album,
        album_artist=current.album_artist,
        year=current.year,
        track_number=current.track_number,
        disc_number=current.disc_number,
        genre=current.genre,
    )


_PROPOSED_FIELDS = (
    "title",
    "artist",
    "album",
    "album_artist",
    "year",
    "track_number",
    "disc_number",
    "genre",
    "mbid_recording",
    "mbid_release",
    "acoustid_id",
)


def _merge(destination: ProposedMetadata, source: ProposedMetadata) -> None:
    """Overlays every non-empty field of ``source`` onto ``destination``."""
    for field_name in _PROPOSED_FIELDS:
        value = getattr(source, field_name, "")
        if value:
            setattr(destination, field_name, value)
    if source.score:
        destination.score = source.score
    if source.artwork_data:
        destination.artwork_data = source.artwork_data
        destination.artwork_mime = source.artwork_mime
        destination.artwork_url = source.artwork_url
        destination.artwork_info = source.artwork_info


async def _enrich_from_musicbrainz(
    proposed: ProposedMetadata,
    prefer_romanized: bool,
    log: LogFn = None,
) -> None:
    """
    Pulls genre tags and script aliases from the detailed recording entity
    (a rate-limited MusicBrainz request).
    """
    if not proposed.mbid_recording:
        return
    try:
        await mb_limiter.wait()
        detail = await asyncio.to_thread(
            musicbrainzngs.get_recording_by_id,
            proposed.mbid_recording,
            includes=["artists", "releases", "tags", "artist-rels", "aliases"],
        )
    except Exception as exc:
        _emit(f"[MusicBrainz] Detail lookup failed for {proposed.mbid_recording}: {exc}", log)
        return

    info = detail.get("recording", {}) or {}

    tags = info.get("tag-list") or []
    if tags and not proposed.genre:
        ranked = sorted(tags, key=lambda t: int(t.get("count", 0) or 0), reverse=True)
        proposed.genre = (ranked[0].get("name") or "").title()
        if proposed.genre:
            _emit(f"[MusicBrainz] Genre resolved: {proposed.genre}", log)

    name = _first_artist_name(info.get("artist-credit"), prefer_romanized, proposed.artist)
    if name:
        proposed.artist = name
        proposed.album_artist = name


async def _resolve_release_via_musicbrainz(
    recording_id: str,
    log: LogFn = None,
) -> Tuple[str, str, str]:
    """
    Resolves ``(release_mbid, album_title, year)`` through MusicBrainz when the
    AcoustID payload did not carry a release for the matched recording.
    """
    try:
        await mb_limiter.wait()
        result = await asyncio.to_thread(
            musicbrainzngs.browse_releases,
            recording=recording_id,
            limit=5,
        )
    except Exception as exc:
        _emit(f"[MusicBrainz] Release browse failed for recording {recording_id}: {exc}", log)
        return "", "", ""

    release = _pick_release(result.get("release-list"))
    if not release:
        return "", "", ""

    release_id = release.get("id", "") or ""
    _emit(
        f"[MusicBrainz] Release resolved from recording: '{release.get('title', '')}' ({release_id})",
        log,
    )
    return release_id, release.get("title", "") or "", _release_year(release)


# --------------------------------------------------------------------------- #
# Stage 1 - MusicBrainz text search (no keys required)
# --------------------------------------------------------------------------- #
async def search_musicbrainz_text(
    title: str,
    artist: str,
    limit: int = 3,
    prefer_romanized: bool = False,
    log: LogFn = None,
) -> ProposedMetadata:
    """
    Stage 1: Key-less MusicBrainz recording search using the file's existing
    Artist / Title tags. Returns an empty ``ProposedMetadata`` when nothing matches.
    """
    _configure_musicbrainz()
    proposed = ProposedMetadata()

    query_title = (title or "").strip()
    query_artist = (artist or "").strip()
    if not query_title or not query_artist:
        return proposed

    _emit(
        f"[Search] MusicBrainz text query: recording='{query_title}' artist='{query_artist}' (limit {limit})",
        log,
    )

    try:
        await mb_limiter.wait()
        result = await asyncio.to_thread(
            musicbrainzngs.search_recordings,
            recording=query_title,
            artist=query_artist,
            limit=limit,
        )
    except Exception as exc:
        _emit(f"[Search] MusicBrainz text query failed: {exc}", log)
        return proposed

    recordings = result.get("recording-list") or []
    if not recordings:
        _emit(f"[Search] No MusicBrainz recording for '{query_title}' by '{query_artist}'", log)
        return proposed

    best = max(recordings, key=_text_score)
    score = _text_score(best)
    if score <= 0:
        _emit(f"[Search] MusicBrainz returned no ranked result for '{query_title}'", log)
        return proposed

    proposed.score = score / 100.0
    proposed.mbid_recording = best.get("id", "") or ""
    proposed.title = best.get("title", "") or query_title
    proposed.artist = _first_artist_name(best.get("artist-credit"), prefer_romanized, query_artist)
    proposed.album_artist = proposed.artist

    release = _pick_release(best.get("release-list"), proposed.title)
    if release:
        proposed.mbid_release = release.get("id", "") or ""
        proposed.album = release.get("title", "") or ""
        proposed.year = _release_year(release)
        proposed.track_number, proposed.disc_number = _track_number_from_release(release, proposed.title)

    _emit(f"[Search] Found '{proposed.title}' by {proposed.artist} on MusicBrainz (Score: {score}%)", log)
    return proposed


# --------------------------------------------------------------------------- #
# Stage 2 - AcoustID acoustic fingerprint lookup (public client key)
# --------------------------------------------------------------------------- #
async def query_acoustid_metadata(
    duration: float,
    fingerprint: str,
    prefer_romanized: bool = False,
    auto_fetch_artwork: bool = True,
    log: LogFn = None,
    abort: Optional[AbortController] = None,
) -> ProposedMetadata:
    """
    Stage 2: Queries the AcoustID API with the public client key and the Chromaprint
    fingerprint + duration, then resolves the matching release via MusicBrainz.

    No user account, login or personal key is required.
    """
    _configure_musicbrainz()
    proposed = ProposedMetadata()
    token = control.resolve(abort)

    if not fingerprint:
        _emit("[AcoustID] Skipped: empty fingerprint", log)
        return proposed

    if token is not None:
        token.check()

    params = {
        "client": ACOUSTID_CLIENT_KEY,
        "meta": "recordings releases releasegroups tracks sources",
        "duration": int(duration),
        "fingerprint": fingerprint,
    }
    _emit(f"[AcoustID] Lookup request (client key {ACOUSTID_CLIENT_KEY}, duration {int(duration)}s)", log)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ACOUSTID_LOOKUP_URL, params=params)
        if resp.status_code != 200:
            _emit(f"[AcoustID] HTTP {resp.status_code} from AcoustID", log)
            return proposed
        data = resp.json()
    except OperationAborted:
        raise
    except Exception as exc:
        _emit(f"[AcoustID] Request failed: {exc}", log)
        return proposed

    if token is not None:
        token.check()

    if data.get("status") != "ok":
        error = (data.get("error") or {}).get("message", "unknown error")
        _emit(f"[AcoustID] API error: {error}", log)
        return proposed

    results = data.get("results") or []
    if not results:
        _emit("[AcoustID] No acoustic match found", log)
        return proposed

    best_result = results[0]
    proposed.score = float(best_result.get("score", 0.0) or 0.0)
    proposed.acoustid_id = best_result.get("id", "") or ""
    _emit(f"[AcoustID] Best match: AcoustID {proposed.acoustid_id} (Score: {int(proposed.score * 100)}%)", log)

    recordings = best_result.get("recordings") or []
    if not recordings:
        _emit("[AcoustID] Match has no linked recordings", log)
        return proposed

    best_rec = recordings[0]
    proposed.mbid_recording = best_rec.get("id", "") or ""
    proposed.title = best_rec.get("title", "") or ""

    if best_rec.get("artist-credit"):
        proposed.artist = parse_full_artist_credit(best_rec.get("artist-credit"), prefer_romanized, "")
        proposed.album_artist = proposed.artist
    elif best_rec.get("artists"):
        proposed.artist = parse_full_artist_credit(best_rec.get("artists"), prefer_romanized, "")
        proposed.album_artist = proposed.artist

    release = _pick_release(best_rec.get("releases"), proposed.title)
    if release:
        proposed.mbid_release = release.get("id", "") or ""
        proposed.album = release.get("title", "") or ""
        proposed.year = _release_year(release)
        proposed.track_number, proposed.disc_number = _track_number_from_release(release, proposed.title)

    # AcoustID sometimes returns the recording without a release - resolve via MusicBrainz.
    if proposed.mbid_recording and not proposed.mbid_release:
        release_id, album, year = await _resolve_release_via_musicbrainz(proposed.mbid_recording, log)
        proposed.mbid_release = release_id
        proposed.album = proposed.album or album
        proposed.year = proposed.year or year

    if auto_fetch_artwork and proposed.mbid_release:
        await fetch_cover_art_archive(proposed, log=log)

    return proposed


# --------------------------------------------------------------------------- #
# Stage 3 - Cover Art Archive
# --------------------------------------------------------------------------- #
async def fetch_cover_art_archive(
    proposed: ProposedMetadata,
    log: LogFn = None,
    abort: Optional[AbortController] = None,
) -> None:
    """
    Fetches the front cover from the public Cover Art Archive for the release MBID.
    Populates ``artwork_data`` / ``artwork_mime`` / ``artwork_url`` / ``artwork_info``.

    The standard ``front-500`` thumbnail is requested first (a few hundred KB) and the
    master scan is only a fallback; either way the bytes pass through
    :func:`optimize_cover_art`, which caps the image at 1000x1000 px in memory.
    """
    if not proposed.mbid_release:
        return

    token = control.resolve(abort)
    if token is not None:
        token.check()

    caa_urls = [
        f"https://coverartarchive.org/release/{proposed.mbid_release}/front-500",
        f"https://coverartarchive.org/release/{proposed.mbid_release}/front",
    ]
    _emit(f"[CoverArt] Requesting front cover for release {proposed.mbid_release}", log)

    resp = None
    for url in caa_urls:
        if token is not None:
            token.check()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url)
                if r.status_code == 200 and r.content:
                    resp = r
                    break
        except OperationAborted:
            raise
        except Exception:
            continue

    if resp is None or not resp.content:
        _emit(
            f"[CoverArt] No front cover available for release {proposed.mbid_release}",
            log,
        )
        return

    data, mime = optimize_cover_art(resp.content, max_size=1000)
    proposed.artwork_data = data
    proposed.artwork_mime = mime
    proposed.artwork_url = caa_urls[0]
    size_kb = len(data) // 1024
    proposed.artwork_info = f"MusicBrainz Cover Art Archive • {size_kb} KB {mime.split('/')[-1].upper()}"
    _emit(f"[CoverArt] Front cover downloaded from Cover Art Archive ({size_kb} KB)", log)


# --------------------------------------------------------------------------- #
# Dual-stage orchestrator
# --------------------------------------------------------------------------- #
async def resolve_via_fingerprint(
    track: AudioTrack,
    prefer_romanized: bool = False,
    log: LogFn = None,
) -> ProposedMetadata:
    """
    Stage 2 entry point: generates the Chromaprint fingerprint with fpcalc, stores
    it on the track, then runs the AcoustID -> MusicBrainz lookup.

    A fingerprint that is already on the track is reused, so the batch path (which
    fingerprints every unmatched file up front, in parallel) never decodes a file
    twice.
    """
    token = control.bound()
    if token is not None:
        token.check()

    fingerprint = track.fingerprint
    if fingerprint:
        duration = float(track.duration or 0.0)
        _emit(f"[Fingerprint] Reusing cached fingerprint for {track.file_name}", log)
    else:
        _emit(f"[Fingerprint] Generating Chromaprint with fpcalc: {track.file_name}", log)
        try:
            # The token is handed over explicitly: the thread-local run binding is not
            # inherited by the worker thread, and fpcalc must still be killable.
            duration, fingerprint = await asyncio.to_thread(
                compute_audio_fingerprint,
                track.file_path,
                FPCALC_ANALYSIS_LENGTH_SECONDS,
                token,
            )
        except OperationAborted:
            raise
        except Exception as exc:
            _emit(f"[Fingerprint] fpcalc failed for {track.file_name}: {exc}", log)
            return ProposedMetadata()

        if not fingerprint:
            _emit(f"[Fingerprint] fpcalc returned an empty fingerprint for {track.file_name}", log)
            return ProposedMetadata()

        track.duration = duration
        track.fingerprint = fingerprint
        _emit(f"[Fingerprint] {track.file_name}: {duration:.0f}s / {len(fingerprint)}-char fingerprint", log)

    return await query_acoustid_metadata(
        duration=duration,
        fingerprint=fingerprint,
        prefer_romanized=prefer_romanized,
        auto_fetch_artwork=False,  # Stage 3 runs once, after the best match is chosen.
        log=log,
    )


async def resolve_track(
    track: AudioTrack,
    prefer_romanized: bool = False,
    auto_fetch_artwork: bool = True,
    log: LogFn = None,
    abort: Optional[AbortController] = None,
) -> ProposedMetadata:
    """
    Runs the complete zero-configuration identification pipeline for one track:

      Stage 1  MusicBrainz text search from the file's own Artist/Title tags.
      Stage 2  fpcalc fingerprint -> AcoustID (public key) -> MusicBrainz release,
               used when tags are missing, mangled, or the text match is weak.
      Stage 3  Front cover art from the public Cover Art Archive.

    Always returns a proposal seeded with the file's existing tags so a failed
    lookup never blanks out local metadata.
    """
    _configure_musicbrainz()
    token = control.resolve(abort)

    current = track.current
    proposed = _seed_from_current(current)

    title = (current.title or "").strip()
    artist = (current.artist or "").strip()
    best: Optional[ProposedMetadata] = None

    if token is not None:
        token.check()

    # ---- Stage 1: MusicBrainz text search (only when local tags are usable) ----
    if title and artist:
        text_match = await search_musicbrainz_text(
            title,
            artist,
            limit=3,
            prefer_romanized=prefer_romanized,
            log=log,
        )
        if text_match.score > 0.0:
            best = text_match
            if text_match.score >= MIN_TEXT_SCORE:
                _emit(
                    f"[Resolve] High-confidence text match for {track.file_name} "
                    f"- skipping acoustic fingerprint.",
                    log,
                )
    else:
        _emit(
            f"[Resolve] {track.file_name}: missing Artist/Title tags - using acoustic fingerprint.",
            log,
        )

    # ---- Stage 2: Acoustic fingerprint fallback ----
    if best is None or best.score < MIN_TEXT_SCORE:
        if best is not None:
            _emit(
                f"[Resolve] Text score {int(best.score * 100)}% below "
                f"{int(MIN_TEXT_SCORE * 100)}% for {track.file_name} - falling back to fingerprint.",
                log,
            )
        fingerprint_match = await resolve_via_fingerprint(
            track,
            prefer_romanized=prefer_romanized,
            log=log,
        )
        if fingerprint_match.score > 0.0 and (best is None or fingerprint_match.score > best.score):
            best = fingerprint_match
            _emit(
                f"[Resolve] Acoustic fingerprint accepted for {track.file_name} "
                f"(Score: {int(best.score * 100)}%).",
                log,
            )

    if best is not None and best.score > 0.0:
        _merge(proposed, best)
        if proposed.mbid_recording:
            _emit(
                f"[MusicBrainz] Resolved '{proposed.title}' by {proposed.artist} "
                f"(recording MBID {proposed.mbid_recording})",
                log,
            )
            await _enrich_from_musicbrainz(proposed, prefer_romanized, log)
    else:
        _emit(f"[Resolve] No MusicBrainz/AcoustID match for {track.file_name} - keeping existing tags.", log)

    # ---- Stage 3: Cover Art Archive ----
    if auto_fetch_artwork and proposed.mbid_release and not proposed.artwork_data:
        await fetch_cover_art_archive(proposed, log=log)

    return proposed


# --------------------------------------------------------------------------- #
# Consensus-Based Album Processing Engine
# --------------------------------------------------------------------------- #
def _normalize_track_num(val: Any) -> Optional[int]:
    if not val:
        return None
    s = str(val).split("/")[0].strip()
    m = re.search(r"\d+", s)
    if m:
        try:
            return int(m.group(0))
        except ValueError:
            return None
    return None


def _extract_track_num_from_filename(name: str) -> Optional[int]:
    m = re.match(r"^\s*(\d+)[\s._\-]", name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _title_similarity(s1: str, s2: str) -> float:
    c1 = re.sub(r"[^\w\s]", "", (s1 or "").lower()).strip()
    c2 = re.sub(r"[^\w\s]", "", (s2 or "").lower()).strip()
    if not c1 or not c2:
        return 0.0
    if c1 == c2:
        return 1.0
    return difflib.SequenceMatcher(None, c1, c2).ratio()


async def resolve_album_consensus(
    tracks: List[AudioTrack],
    source_dir: str = "",
    prefer_romanized: bool = False,
    auto_fetch_artwork: bool = True,
    log: LogFn = None,
    progress: ProgressFn = None,
    abort: Optional[AbortController] = None,
) -> Tuple[Optional[bytes], str]:
    """
    Consensus-Based Resolution for an album batch:
      1. Inspect loaded tracks to find dominant Artist and Album tags (or folder name).
      2. Single MusicBrainz release query: search_releases(release=..., artist=..., limit=5).
      3. Fetch full tracklist and release MBID with single API call: get_release_by_id(release_mbid).
      4. Download front cover art from Cover Art Archive ONCE.
      5. Map staged local tracks to release tracklist (track number matching + title fuzzy-similarity).
      6. Fingerprint (fpcalc / AcoustID) ONLY if a track fails to match or has ambiguous numbering.

    ``progress`` (optional) is called as ``progress(fraction, phase)`` while the batch
    advances.  Each phase reports its *own* 0 -> 1 fraction (one sweep of the bar per
    phase) and every track is accounted for exactly once per phase: stage 5 reports
    "Identifying", and a track that cannot be matched to the release tracklist is
    reported once in "Pre-fingerprinting" (the parallel fpcalc decode) and once in
    "Fingerprinting" (the AcoustID lookup that follows).

    Returns:
      (album_cover_bytes, album_cover_mime)
    """
    _configure_musicbrainz()
    token = control.resolve(abort)

    if not tracks:
        return None, "image/jpeg"

    if token is not None:
        token.check()

    total_tracks = len(tracks)
    finalized = 0
    _report(progress, 0.0, "Searching release")

    # 1. Dominant tags inspection
    artists = []
    albums = []
    for t in tracks:
        art = (t.current.album_artist or t.current.artist or "").strip()
        if art:
            artists.append(art)
        alb = (t.current.album or "").strip()
        if alb:
            albums.append(alb)

    consensus_artist = collections.Counter(artists).most_common(1)[0][0] if artists else ""
    consensus_album = collections.Counter(albums).most_common(1)[0][0] if albums else ""

    folder_name = Path(source_dir).name if source_dir else ""
    if not folder_name and tracks:
        folder_name = Path(tracks[0].file_path).parent.name

    if (not consensus_artist or not consensus_album) and folder_name:
        if " - " in folder_name:
            parts = folder_name.split(" - ", 1)
            if not consensus_artist:
                consensus_artist = parts[0].strip()
            if not consensus_album:
                consensus_album = re.sub(r"\s*\(\d{4}\)$", "", parts[1].strip()).strip()
        else:
            if not consensus_album:
                consensus_album = re.sub(r"\s*\(\d{4}\)$", "", folder_name).strip()

    _emit(
        f"[Consensus] Identified consensus tags: Artist='{consensus_artist}' • Album='{consensus_album}'",
        log,
    )

    releases: List[Dict[str, Any]] = []

    # 2. Single MusicBrainz release search query
    if consensus_album or consensus_artist:
        control.check(token)
        await mb_limiter.wait()
        q: Dict[str, Any] = {"limit": 3}
        if consensus_album:
            q["release"] = consensus_album
        if consensus_artist:
            q["artist"] = consensus_artist
        _emit(f"[MusicBrainz] Release query: {q}", log)
        try:
            res = await asyncio.to_thread(musicbrainzngs.search_releases, **q)
            releases = res.get("release-list", []) or []
        except Exception as exc:
            _emit(f"[MusicBrainz] Release query failed: {exc}", log)

        # Fallback to searching album only if combination yielded zero results
        if not releases and consensus_album and consensus_artist:
            await mb_limiter.wait()
            try:
                _emit(f"[MusicBrainz] Fallback release query: release='{consensus_album}'", log)
                res = await asyncio.to_thread(musicbrainzngs.search_releases, release=consensus_album, limit=3)
                releases = res.get("release-list", []) or []
            except Exception as exc:
                _emit(f"[MusicBrainz] Fallback query failed: {exc}", log)

    album_cover_bytes: Optional[bytes] = None
    album_cover_mime: str = "image/jpeg"
    release_mbid: str = ""

    if releases:
        def _score_release(rel: Dict[str, Any]) -> int:
            sc = int(rel.get("ext:score", 0) or 0)
            trk_count = int(rel.get("track-count", 0) or 0)
            if trk_count == len(tracks):
                sc += 30
            elif abs(trk_count - len(tracks)) <= 2:
                sc += 15
            if rel.get("status") == "Official":
                sc += 10
            return sc

        best_release = max(releases, key=_score_release)
        release_mbid = best_release.get("id", "")
        _emit(
            f"[MusicBrainz] Consensus selected release: '{best_release.get('title')}' (MBID: {release_mbid})",
            log,
        )

        # 3. Fetch full tracklist and release MBID with a single API call
        release_dict: Dict[str, Any] = {}
        try:
            control.check(token)
            await mb_limiter.wait()
            rel_detail = await asyncio.to_thread(
                musicbrainzngs.get_release_by_id,
                release_mbid,
                includes=["recordings", "artists", "media"],
            )
            release_dict = rel_detail.get("release", {}) or {}
        except Exception as exc:
            _emit(f"[MusicBrainz] Release details lookup failed: {exc}", log)

        album_title = release_dict.get("title") or consensus_album
        album_artist = parse_full_artist_credit(release_dict.get("artist-credit"), prefer_romanized, consensus_artist)
        release_year = _release_year(release_dict)

        # Parse release tracklist
        rel_tracks: List[Dict[str, Any]] = []
        for medium in release_dict.get("medium-list", []):
            disc_no = str(medium.get("position") or "1")
            for trk in medium.get("track-list", []):
                trk_num_str = str(trk.get("number") or trk.get("position") or "")
                recording = trk.get("recording", {}) or {}
                rec_artist = parse_full_artist_credit(
                    trk.get("artist-credit") or recording.get("artist-credit"),
                    prefer_romanized,
                    album_artist,
                )
                length_ms = trk.get("length") or recording.get("length")
                duration_sec: Optional[float] = None
                if length_ms is not None:
                    try:
                        duration_sec = float(length_ms) / 1000.0
                    except (ValueError, TypeError):
                        duration_sec = None

                rel_tracks.append({
                    "number_str": trk_num_str,
                    "number_int": _normalize_track_num(trk_num_str),
                    "disc": disc_no,
                    "title": trk.get("title") or recording.get("title") or "",
                    "artist": rec_artist,
                    "duration": duration_sec,
                    "recording_id": recording.get("id", ""),
                })

        _emit(f"[MusicBrainz] Release contains {len(rel_tracks)} tracks across medium(s)", log)

        # 4. Download front cover art from Cover Art Archive ONCE
        if auto_fetch_artwork and release_mbid:
            caa_urls = [
                f"https://coverartarchive.org/release/{release_mbid}/front-500",
                f"https://coverartarchive.org/release/{release_mbid}/front",
            ]
            _emit(f"[CoverArt] Downloading front cover from Cover Art Archive for release {release_mbid}...", log)
            for caa_url in caa_urls:
                control.check(token)
                try:
                    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                        resp = await client.get(caa_url)
                        if resp.status_code == 200 and resp.content:
                            data, mime = optimize_cover_art(resp.content, max_size=1000)
                            album_cover_bytes = data
                            album_cover_mime = mime
                            size_kb = len(album_cover_bytes) // 1024
                            _emit(f"[CoverArt] Downloaded and optimized album art ({size_kb} KB)", log)
                            break
                        else:
                            _emit(f"[CoverArt] No front cover available at {caa_url} (HTTP {resp.status_code})", log)
                except Exception as exc:
                    _emit(f"[CoverArt] Error fetching {caa_url}: {exc}", log)

        # 5. Map staged local tracks to the release tracklist
        matched_rel_indices = set()
        _report(progress, finalized / total_tracks, "Identifying")
        for track in tracks:
            control.check(token)
            local_num = _normalize_track_num(track.current.track_number)
            if local_num == 0:
                local_num = None
            if local_num is None:
                local_num = _extract_track_num_from_filename(track.file_name)
                if local_num == 0:
                    local_num = None

            local_dur = float(track.duration or 0.0)
            local_disc = _normalize_track_num(track.current.disc_number)
            clean_local_title = sanitize_metadata_text(track.current.title)

            matched_item = None
            matched_idx = None

            # First priority: Match by Track Number (TRCK) and duration tolerance (+/- 3 seconds)
            if local_num is not None and local_num > 0:
                candidates = [
                    (idx, item) for idx, item in enumerate(rel_tracks)
                    if item["number_int"] == local_num and idx not in matched_rel_indices
                ]
                valid_candidates = []
                for idx, item in candidates:
                    rel_dur = item.get("duration")
                    item_disc = _normalize_track_num(item.get("disc"))

                    # Disc matching if local disc is known
                    disc_match = True
                    if local_disc is not None and item_disc is not None and local_disc > 0 and item_disc > 0:
                        disc_match = (local_disc == item_disc)

                    # Duration tolerance (+/- 3 seconds)
                    dur_match = False
                    if local_dur > 0 and rel_dur is not None and rel_dur > 0:
                        dur_match = (abs(local_dur - rel_dur) <= 3.0)
                    elif rel_dur is None or local_dur <= 0:
                        dur_match = True

                    if dur_match and disc_match:
                        sim = _title_similarity(clean_local_title or track.file_name, item["title"])
                        if not clean_local_title or sim >= 0.20:
                            valid_candidates.append((idx, item, sim, dur_match))

                if len(valid_candidates) == 1:
                    matched_idx, matched_item, _, _ = valid_candidates[0]
                    matched_rel_indices.add(matched_idx)
                elif len(valid_candidates) > 1:
                    def _rank_cand(c):
                        idx, item, sim, dur_match = c
                        rel_dur = item.get("duration")
                        dur_err = abs(local_dur - rel_dur) if (local_dur > 0 and rel_dur) else 999.0
                        return (1 if dur_match else 0, sim, -dur_err)
                    best_c = max(valid_candidates, key=_rank_cand)
                    matched_idx, matched_item = best_c[0], best_c[1]
                    matched_rel_indices.add(matched_idx)

            # Second priority: Fallback to fuzzy title similarity if track numbers are missing or zero
            if matched_item is None:
                title_query = clean_local_title
                if not title_query:
                    stem = Path(track.file_name).stem
                    stem = re.sub(r"^\d+[\s._\-]+", "", stem)
                    title_query = sanitize_metadata_text(stem)

                best_item = None
                best_sim = 0.0
                best_idx = None
                for idx, item in enumerate(rel_tracks):
                    if idx in matched_rel_indices:
                        continue
                    sim = _title_similarity(title_query, item["title"])
                    rel_dur = item.get("duration")

                    dur_match = False
                    if local_dur > 0 and rel_dur is not None and rel_dur > 0:
                        dur_match = (abs(local_dur - rel_dur) <= 3.0)

                    score = sim + (0.15 if dur_match else 0.0)
                    if (sim >= 0.60 or (dur_match and sim >= 0.40)) and score > best_sim:
                        best_sim = score
                        best_item = item
                        best_idx = idx

                if best_item and best_idx is not None:
                    matched_item = best_item
                    matched_idx = best_idx
                    matched_rel_indices.add(best_idx)

            if matched_item:
                track.proposed.title = sanitize_metadata_text(matched_item["title"])
                track.proposed.artist = sanitize_metadata_text(matched_item["artist"] or album_artist)
                track.proposed.album = sanitize_metadata_text(album_title)
                track.proposed.album_artist = sanitize_metadata_text(album_artist)
                track.proposed.year = release_year
                track.proposed.track_number = str(matched_item["number_str"])
                track.proposed.disc_number = str(matched_item["disc"])
                track.proposed.mbid_recording = matched_item["recording_id"]
                track.proposed.mbid_release = release_mbid
                track.proposed.score = 0.95
                if album_cover_bytes:
                    track.proposed.artwork_data = album_cover_bytes
                    track.proposed.artwork_mime = album_cover_mime
                    track.proposed.artwork_url = f"https://coverartarchive.org/release/{release_mbid}/front-500"
                    size_kb = len(album_cover_bytes) // 1024
                    track.proposed.artwork_info = (
                        f"MusicBrainz Cover Art Archive • {size_kb} KB "
                        f"{album_cover_mime.split('/')[-1].upper()}"
                    )
                track.status = TrackStatus.VERIFIED
                _emit(
                    f"[Tracklist Match] Track #{matched_item['number_str']} '{matched_item['title']}' -> {track.file_name}",
                    log,
                )

            if track.status in (TrackStatus.VERIFIED, TrackStatus.AMBIGUOUS):
                finalized += 1
                _report(progress, finalized / total_tracks, "Identifying")

    # 6. Fingerprint (fpcalc / AcoustID) ONLY if a track fails to match or has
    #    ambiguous numbering.
    #
    #    The stage is presented as TWO sweeps of the same progress bar, because it is
    #    two different kinds of work:
    #      * "Pre-fingerprinting" - the CPU-bound fpcalc batch that decodes every
    #        unmatched file in parallel (the footer paints this sweep GREEN);
    #      * "Fingerprinting"     - the AcoustID lookup/matching pass that follows
    #        (painted in the usual crimson).
    #    Each sweep reports its own 0..1 fraction, so the bar fills 0 -> 100% twice
    #    instead of crawling to 50% and then inching through the second half.
    unmatched_tracks = [t for t in tracks if t.status not in (TrackStatus.VERIFIED, TrackStatus.AMBIGUOUS)]
    if unmatched_tracks:
        unmatched_total = len(unmatched_tracks)
        decode_done = 0

        def _advance_pre_fingerprint(_trk: AudioTrack) -> None:
            """One decoded file: advance the green pre-fingerprint sweep."""
            nonlocal decode_done
            decode_done += 1
            _report(progress, decode_done / unmatched_total, "Pre-fingerprinting")

        _report(progress, 0.0, "Pre-fingerprinting")
        workers = recommended_fpcalc_workers(unmatched_total)
        _emit(
            f"[Fallback] Pre-fingerprinting {unmatched_total} unmatched track(s) with "
            f"{workers} parallel fpcalc worker(s), first {FPCALC_ANALYSIS_LENGTH_SECONDS}s "
            f"of each file...",
            log,
        )

        loop = asyncio.get_running_loop()

        def _on_fpcalc_done(trk: AudioTrack) -> None:
            # Called from an fpcalc worker thread, so hop back onto the event loop
            # before touching the UI (NiceGUI elements are loop-thread only).
            loop.call_soon_threadsafe(_advance_pre_fingerprint, trk)

        # ``fingerprint_tracks_parallel`` blocks while it babysits up to 32 fpcalc
        # subprocesses.  Running it in a thread keeps the event loop - and therefore
        # the websocket heartbeat - free; on the loop it would freeze the whole UI for
        # the length of the batch and the client would report a lost connection.
        await asyncio.to_thread(
            fingerprint_tracks_parallel,
            unmatched_tracks,
            abort=token,
            log=log,
            on_complete=_on_fpcalc_done,
        )

        if token is not None:
            token.check()

        # Second sweep: the bar restarts from 0% and fills again while AcoustID and
        # MusicBrainz answer.
        match_done = 0

        def _advance_fingerprint() -> None:
            nonlocal match_done
            match_done += 1
            _report(progress, match_done / unmatched_total, "Fingerprinting")

        _report(progress, 0.0, "Fingerprinting")
        _emit(
            f"[Fallback] Fingerprinting {unmatched_total} track(s): "
            f"matching fingerprints against AcoustID...",
            log,
        )

        semaphore = asyncio.Semaphore(max(1, min(NETWORK_LOOKUP_CONCURRENCY, len(unmatched_tracks))))

        async def _lookup(trk: AudioTrack):
            async with semaphore:
                return await resolve_via_fingerprint(trk, prefer_romanized=prefer_romanized, log=log)

        def _apply_outcome(trk: AudioTrack, outcome: Any) -> None:
            """Store one lookup result on its track."""
            if isinstance(outcome, BaseException):
                trk.error_message = str(outcome)
                trk.status = TrackStatus.UNMATCHED
                return
            fp_prop = outcome
            if fp_prop.score > 0.0:
                trk.proposed = fp_prop
                if fp_prop.score >= 0.80:
                    trk.status = TrackStatus.VERIFIED
                else:
                    trk.status = TrackStatus.AMBIGUOUS
                if album_cover_bytes and not trk.proposed.artwork_data:
                    trk.proposed.artwork_data = album_cover_bytes
                    trk.proposed.artwork_mime = album_cover_mime
                    if release_mbid:
                        trk.proposed.artwork_url = f"https://coverartarchive.org/release/{release_mbid}/front-500"
                    size_kb = len(album_cover_bytes) // 1024
                    trk.proposed.artwork_info = (
                        f"MusicBrainz Cover Art Archive • {size_kb} KB "
                        f"{album_cover_mime.split('/')[-1].upper()}"
                    )
            else:
                trk.status = TrackStatus.UNMATCHED

        # Each lookup is painted the moment it lands (not in one burst at the end), so
        # the bar advances through the matching half while AcoustID is still answering.
        # Cancelling the in-flight requests as soon as CANCEL / ABORT lands keeps a slow
        # network lookup from holding the UI back.
        tasks: Dict[asyncio.Future, AudioTrack] = {
            asyncio.ensure_future(_lookup(trk)): trk for trk in unmatched_tracks
        }
        try:
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=0.2, return_when=asyncio.FIRST_COMPLETED
                )
                if token is not None and token.is_aborted:
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    raise OperationAborted("album identification aborted by user")
                for task in done:
                    trk = tasks[task]
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    _apply_outcome(trk, exc if exc is not None else task.result())
                    _advance_fingerprint()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    return album_cover_bytes, album_cover_mime

