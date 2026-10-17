"""
Persistent SQLite Cache for FXsonic
Stores acoustic fingerprints and metadata caches across sessions.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional, Tuple
from .diagnostics import log_file_path

CACHE_FILE_NAME = "cache.db"
_cache_lock = threading.Lock()


def get_cache_db_path() -> Path:
    """Return the path to the persistent SQLite database."""
    log_path = log_file_path()
    if log_path:
        return log_path.parent / CACHE_FILE_NAME
    return Path.cwd() / CACHE_FILE_NAME


def init_cache_db() -> None:
    """Initialize database schema if it doesn't already exist."""
    db_path = get_cache_db_path()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock, sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fingerprints (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL,
                    file_size INTEGER,
                    duration REAL,
                    fingerprint TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fp_lookup ON fingerprints (file_path, mtime, file_size)"
            )
            conn.commit()
    except Exception as e:
        # Diagnostic logging or silent pass
        pass


def get_cached_fingerprint(file_path: str, mtime: float, file_size: int) -> Optional[Tuple[float, str]]:
    """
    Retrieve cached (duration, fingerprint) if mtime and file_size match.
    Returns None if cache miss or file modified.
    """
    db_path = get_cache_db_path()
    if not db_path.exists():
        return None
    try:
        with _cache_lock, sqlite3.connect(str(db_path), timeout=2.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT duration, fingerprint FROM fingerprints WHERE file_path = ? AND mtime = ? AND file_size = ?",
                (file_path, mtime, file_size),
            )
            row = cursor.fetchone()
            if row and row[1]:
                return float(row[0]), str(row[1])
    except Exception:
        pass
    return None


def store_cached_fingerprint(
    file_path: str, mtime: float, file_size: int, duration: float, fingerprint: str
) -> None:
    """Store or update acoustic fingerprint for an audio file."""
    if not file_path or not fingerprint:
        return
    init_cache_db()
    db_path = get_cache_db_path()
    try:
        with _cache_lock, sqlite3.connect(str(db_path), timeout=2.0) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fingerprints (file_path, mtime, file_size, duration, fingerprint)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_path, mtime, file_size, duration, fingerprint),
            )
            conn.commit()
    except Exception:
        pass
