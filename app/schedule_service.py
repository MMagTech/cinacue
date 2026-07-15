"""Building scheduled-movie rows from Plex metadata.

Kept pure and separate from the API layer so end-time calculation, path
translation, and poster wiring can be unit-tested without HTTP or a database.
"""
from __future__ import annotations

from .models import ScheduledMovie
from .models import Settings as SettingsRow
from .plex_client import PlexMovie
from .plex_service import local_source_path


class ScheduleError(Exception):
    """Raised when a movie cannot be scheduled (e.g. unknown runtime)."""


def public_poster_url(rating_key: str) -> str:
    """Poster path served by the public API (no token, schedule-gated)."""
    return f"/api/public/poster/{rating_key}"


def build_scheduled_movie(
    movie: PlexMovie,
    start_minute: int,
    row: SettingsRow,
) -> ScheduledMovie:
    """Create an (uncommitted) ScheduledMovie for a daily slot.

    The runtime (from Plex) defines how long the airing runs; the source path
    is the translated container path FFmpeg will later read.
    """
    if not movie.runtime_ms or movie.runtime_ms <= 0:
        raise ScheduleError(
            f"'{movie.title}' has no known runtime in Plex; cannot schedule it."
        )

    local_path = local_source_path(movie, row) or ""

    return ScheduledMovie(
        plex_rating_key=movie.rating_key,
        title=movie.title,
        year=movie.year,
        poster_url=public_poster_url(movie.rating_key) if movie.thumb_key else None,
        runtime_ms=movie.runtime_ms,
        source_path=local_path,
        start_minute=start_minute,
    )
