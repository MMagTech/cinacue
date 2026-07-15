"""Pydantic request/response schemas.

Public schemas are deliberately narrow: they never carry Plex tokens, server
URLs, filesystem paths, FFmpeg command lines, or any admin/session data.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .config import EncoderPreset, MaxResolution


# --- Health ----------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    time_utc: datetime


# --- Auth ------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool
    csrf_token: str


class WhoAmIResponse(BaseModel):
    authenticated: bool
    # Lets the SPA re-arm its in-memory CSRF token after a page reload.
    csrf_token: Optional[str] = None


# --- Encoding settings -----------------------------------------------------
class EncodingSettings(BaseModel):
    maximum_resolution: MaxResolution
    video_bitrate_kbps: int = Field(ge=500, le=100_000)
    audio_bitrate_kbps: int = Field(ge=64, le=512)
    encoder: str
    encoder_preset: EncoderPreset


class EncodingSettingsUpdate(BaseModel):
    maximum_resolution: Optional[MaxResolution] = None
    video_bitrate_kbps: Optional[int] = Field(default=None, ge=500, le=100_000)
    audio_bitrate_kbps: Optional[int] = Field(default=None, ge=64, le=512)
    encoder_preset: Optional[EncoderPreset] = None


# --- Public channel views --------------------------------------------------
class NowPlaying(BaseModel):
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    progress_seconds: int
    runtime_seconds: int


class UpcomingItem(BaseModel):
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    scheduled_start: datetime


class PublicStatus(BaseModel):
    state: str
    timezone: str
    now_playing: Optional[NowPlaying] = None
    next_up: Optional[UpcomingItem] = None


class PublicChannelConfig(BaseModel):
    timezone: str
    channel_name: str = "Movie Channel"


# --- Schedule (admin) ------------------------------------------------------
class ScheduledMovieOut(BaseModel):
    id: int
    plex_rating_key: str
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    runtime_ms: int
    # Daily slot: minutes from local midnight (channel timezone).
    start_minute: int


class ScheduleResponse(BaseModel):
    # The daily lineup (sorted by start time) plus which weekdays air.
    movies: List[ScheduledMovieOut]
    active_days: List[int]  # weekday numbers on air (0=Mon..6=Sun)
    timezone: str


# --- Plex (admin only) -----------------------------------------------------
class PlexStatus(BaseModel):
    configured: bool
    reachable: bool
    library_found: bool
    library_name: str


class PlexMovieOut(BaseModel):
    """Admin-facing Plex movie. Never includes the raw filesystem path or
    token — only a proxied poster URL and display-safe source details."""

    rating_key: str
    title: str
    year: Optional[int] = None
    summary: str = ""
    poster_url: Optional[str] = None
    runtime_ms: int
    runtime_minutes: int
    source_resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    container: Optional[str] = None
    source_available: bool = False


# --- Schedule mutation (admin) ---------------------------------------------
class ScheduleCreate(BaseModel):
    plex_rating_key: str
    # Daily slot: minutes from local midnight (0..1439).
    start_minute: int = Field(ge=0, le=1439)


class ScheduleUpdate(BaseModel):
    # New daily slot time.
    start_minute: int = Field(ge=0, le=1439)


class ActiveDaysUpdate(BaseModel):
    # Weekday numbers that should air (0=Mon..6=Sun); others go off air.
    active_days: List[int]
