"""SQLModel database models.

Two persisted tables for the foundation:

* ``settings``          — single row of channel-wide configuration.
* ``scheduled_movies``  — one row per movie placed on the calendar.

``stream_state`` is intentionally *not* a table; it is transient runtime state
held in memory by the stream manager in a later milestone.

All timestamps are stored in UTC (naive UTC datetimes) and rendered in the
configured timezone at the edge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

from .config import EncoderPreset, MaxResolution


def utcnow() -> datetime:
    """Timezone-naive UTC timestamp (what we persist)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Settings(SQLModel, table=True):
    """Channel-wide settings. Enforced single row via ``id == 1``."""

    __tablename__ = "settings"

    id: Optional[int] = Field(default=1, primary_key=True)

    timezone: str = "America/New_York"

    # Which weekdays the channel airs, as a 7-bit mask (bit 0 = Monday ...
    # bit 6 = Sunday). Default 127 = all days on. Inactive days are off air.
    active_days_mask: int = 127

    # Plex (populated in a later milestone)
    plex_url: str = ""
    plex_library_name: str = "Movies"
    plex_path_prefix: str = "/movies"
    local_path_prefix: str = "/media/movies"
    # NOTE: the Plex *token* is never stored here in plaintext. It is kept
    # encrypted alongside the app secret and never returned by the public API.

    # Encoding (channel-wide, never per-movie)
    maximum_resolution: MaxResolution = Field(default=MaxResolution.p1080)
    video_bitrate_kbps: int = 8000
    audio_bitrate_kbps: int = 192
    encoder: str = "h264_nvenc"
    encoder_preset: EncoderPreset = Field(default=EncoderPreset.balanced)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScheduledMovie(SQLModel, table=True):
    """A movie in the repeating daily lineup.

    The schedule is a single daily lineup that repeats every day: a movie sits
    at a time-of-day (``start_minute``, in the channel timezone) and airs each
    day at that slot. Which weekdays actually air is a channel-level setting
    (:attr:`Settings.active_days_mask`); on inactive days the channel is off.
    Absolute air times and the live offset are computed against the timezone at
    read time, so DST is handled correctly.
    """

    __tablename__ = "scheduled_movies"

    id: Optional[int] = Field(default=None, primary_key=True)

    plex_rating_key: str = Field(index=True)
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    runtime_ms: int = 0
    source_path: str = ""

    # Daily slot: minutes from local midnight (0..1439), channel timezone.
    start_minute: int = Field(index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
