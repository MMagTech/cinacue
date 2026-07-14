"""Glue between the Plex client, settings, and API schemas.

Kept separate from ``admin_api`` so the pure conversion logic (Plex metadata +
path translation -> API schema) can be unit-tested without HTTP.
"""
from __future__ import annotations

from typing import Optional

from .config import settings
from .media_probe import source_file_exists
from .models import Settings as SettingsRow
from .plex_client import PlexClient, PlexMovie, translate_plex_path
from .schemas import PlexMovieOut


def plex_configured() -> bool:
    return bool((settings.plex_url or "").strip() and (settings.plex_token or "").strip())


def make_client(row: SettingsRow) -> PlexClient:
    """Build a PlexClient from persisted settings + the env-only token."""
    base_url = row.plex_url or settings.plex_url
    return PlexClient(
        base_url=base_url,
        token=settings.plex_token,
        library_name=row.plex_library_name or settings.plex_library_name,
    )


def local_source_path(movie: PlexMovie, row: SettingsRow) -> Optional[str]:
    """Translate the Plex source path onto the mounted container path."""
    if not movie.source_path:
        return None
    return translate_plex_path(
        movie.source_path,
        row.plex_path_prefix or settings.plex_path_prefix,
        row.local_path_prefix or settings.local_path_prefix,
    )


def movie_to_out(movie: PlexMovie, row: SettingsRow) -> PlexMovieOut:
    """Convert a PlexMovie to the admin-facing schema.

    Deliberately omits the raw filesystem path; exposes only a proxied poster
    URL, display-safe source details, and whether the file is present.
    """
    local_path = local_source_path(movie, row)
    resolution = (
        f"{movie.width}x{movie.height}" if movie.width and movie.height else None
    )
    poster = (
        f"/api/admin/plex/poster/{movie.rating_key}" if movie.thumb_key else None
    )
    return PlexMovieOut(
        rating_key=movie.rating_key,
        title=movie.title,
        year=movie.year,
        summary=movie.summary,
        poster_url=poster,
        runtime_ms=movie.runtime_ms,
        runtime_minutes=round(movie.runtime_ms / 60000) if movie.runtime_ms else 0,
        source_resolution=resolution,
        video_codec=movie.video_codec,
        audio_codec=movie.audio_codec,
        container=movie.container,
        source_available=bool(local_path and source_file_exists(local_path)),
    )
