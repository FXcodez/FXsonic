"""
Data Models for FXsonic Workbench
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class TrackStatus(str, Enum):
    STAGED = "STAGED"
    UNVERIFIED = "UNVERIFIED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    VERIFIED = "VERIFIED"


@dataclass
class TrackMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track_number: str = ""
    disc_number: str = ""
    genre: str = ""
    has_artwork: bool = False
    raw_frames: Dict[str, Any] = field(default_factory=dict)
    junk_frames: List[str] = field(default_factory=list)


@dataclass
class ProposedMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track_number: str = ""
    disc_number: str = ""
    genre: str = ""
    score: float = 0.0  # 0.0 to 1.0 (or percentage)
    mbid_recording: str = ""
    mbid_release: str = ""
    acoustid_id: str = ""
    artwork_url: Optional[str] = None
    artwork_data: Optional[bytes] = None
    artwork_mime: str = "image/jpeg"
    artwork_info: str = ""


@dataclass
class AudioTrack:
    id: str  # Unique track ID (e.g. str(uuid4()) or str index)
    file_path: str  # Absolute path on disk
    file_name: str
    file_size: int
    duration: float = 0.0
    fingerprint: Optional[str] = None
    
    # Metadata states
    current: TrackMetadata = field(default_factory=TrackMetadata)
    proposed: ProposedMetadata = field(default_factory=ProposedMetadata)
    
    # Processing states
    status: TrackStatus = TrackStatus.UNMATCHED
    selected: bool = True  # For batch Apply
    is_processing: bool = False
    error_message: Optional[str] = None
    
    # Destination transformation
    target_path: str = ""

    # Duplicate tracking
    is_duplicate: bool = False
    duplicate_group_id: Optional[str] = None
