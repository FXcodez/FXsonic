# FXsonic Roadmap & Tasks

This document outlines architectural improvements and feature enhancements, tracking what was integrated in v0.2.0 and what is planned for v0.3.

---

## 0. UI Refinements & Fixes (Completed in v0.2.0)

- [x] **Button alignment and spacing for "Clean Track Titles"** (Fixed in staging table toolbar).
- [x] **Remove "Audio Workbench" name** (Cleaned to FXsonic v0.2.0).
- [x] **Theme toggle relocated** (Moved from navbar to bottom-left status footer).
- [x] **Help documentation** (Added `help.html` and options bar trigger).

---

## 1. Multi-Format Audio Support

- [x] **Accept additional audio containers in intake scanner:** (Implemented in v0.2.0)
  - Intake scanner in `state.py` recognizes `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`, `.wav`, and `.aiff`.
- [ ] **Metadata abstraction layer in `tagger.py`:** (Planned for v0.3)
  - Map tags dynamically across ID3 (MP3), Vorbis comments (FLAC/OGG), and MP4 atoms (M4A) using Mutagen.
  - Support embedding and extracting front cover art across Vorbis/FLAC blocks (`Picture`) and MP4 `covr` atoms.

---

## 2. Global Distance Matching Matrix (Beets Pattern) &mdash; Planned for v0.3

> *Assessment: Requires custom Munkres / Hungarian assignment solver without bloating dependencies with `scipy`. High code complexity; reserved for v0.3.*

- [ ] **Replace greedy single-pass matching with a distance penalty matrix:**
  - Calculate an error score for every `(local_track, release_track)` pair based on:
    - Duration delta in seconds (with higher penalty exceeding 3s).
    - String distance (Levenshtein similarity) on title and track artist.
    - Track number and disc number difference.
- [ ] **Bipartite minimum-weight assignment:**
  - Implement the Hungarian (Munkres) assignment algorithm or a linear-sum solver to resolve all tracks in the release simultaneously.
  - Avoid false locks where an earlier track erroneously consumes a later track's slot.

---

## 3. Multi-Disc Numbering Heuristics (Completed in v0.2.0)

- [x] **Sequential multi-disc offset detection:** (Implemented in v0.2.0)
  - Identifies releases where files are numbered continuously (for example, tracks 1 to 24 on a 2-CD release) and maps tracks 13+ to Disc 2.
- [x] **Prefixed track numbering parser:** (Implemented in v0.2.0)
  - Supports disc-prefixed numbers like `101`, `102` (Disc 1, Track 1/2) and `201`, `202` (Disc 2, Track 1/2), as well as hyphenated `1-01`, `2-01`.

---

## 4. Persistent Local SQLite Cache

- [x] **Persistent acoustic fingerprint cache:** (Implemented in v0.2.0)
  - Stores `(file_path, mtime, file_size) -> (duration, fingerprint)` in `cache.db` (`core/cache.py`).
  - Skips re-running `fpcalc.exe` on unmodified files during rescans.
- [ ] **HTTP response caching:** (Planned for v0.3)
  - Implement a lightweight local SQLite database (`cache.db`) storing MusicBrainz API responses, AcoustID lookups, and Cover Art Archive URLs with time-to-live (TTL) expiration.
  - Bypass the 1 req/sec MusicBrainz rate limit when rescanning previously identified albums or artists.

---

## 5. Release Disambiguation & Preference Scoring &mdash; Planned for v0.3

- [ ] **Configurable release preferences:**
  - Allow ranking by preferred media format: `Digital Media`, `CD`, `Vinyl`.
  - Allow preferred release countries (e.g., `Worldwide / XW`, `US`, `UK`).
  - Weight releases with matching track counts and official status higher during consensus evaluation.

---

## 6. Flexible Path Pattern Templating &mdash; Planned for v0.3

- [ ] **Token-based file renaming:**
  - Replace static renaming modes with customizable path template strings.
  - Supported tokens:
    - `%artist%`, `%albumartist%`, `%album%`, `%title%`
    - `%year%`, `%track%` (zero-padded), `%disc%`
  - Example default: `%albumartist%/%album% [%year%]/%track% - %title%`
- [x] **Collision and character safety checks:** (Implemented in v0.2.0)
  - Sanitizes reserved filesystem characters (`:`, `?`, `*`, `"`, `<`, `>`, `|`) for cross-platform safety.

---

## 7. Audio Loudness & Tagging Extras &mdash; Excluded / Not Useful

> *Assessment: ReplayGain and EBU R128 loudness calculation require full PCM decoding of audio streams, which introduces significant CPU/memory overhead and delay during library intake. Excluded as out of scope for a fast metadata tagger.*
