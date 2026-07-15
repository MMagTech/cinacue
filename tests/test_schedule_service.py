"""Unit tests for building daily-lineup rows and local->UTC conversion."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models import Settings as SettingsRow
from app.plex_client import PlexMovie
from app.schedule_service import ScheduleError, build_scheduled_movie, public_poster_url
from app.scheduler import local_naive_to_utc


def _movie(runtime_min=116, rk="42", thumb="/library/metadata/42/thumb/9"):
    return PlexMovie(
        rating_key=rk,
        title="Back to the Future",
        year=1985,
        summary="",
        thumb_key=thumb,
        runtime_ms=runtime_min * 60_000,
        source_path="/movies/Back to the Future (1985)/movie.mkv",
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        container="mkv",
    )


def _row():
    return SettingsRow(
        id=1,
        timezone="America/New_York",
        plex_path_prefix="/movies",
        local_path_prefix="/media/movies",
    )


def test_build_sets_slot_and_translates_path():
    m = build_scheduled_movie(_movie(116), 19 * 60, _row())  # 19:00
    assert m.start_minute == 19 * 60
    assert m.source_path == "/media/movies/Back to the Future (1985)/movie.mkv"
    assert m.poster_url == public_poster_url("42")
    assert m.runtime_ms == 116 * 60_000


def test_build_without_thumb_has_no_poster():
    m = build_scheduled_movie(_movie(thumb=None), 19 * 60, _row())
    assert m.poster_url is None


def test_build_rejects_zero_runtime():
    with pytest.raises(ScheduleError):
        build_scheduled_movie(_movie(runtime_min=0), 19 * 60, _row())


def test_local_naive_to_utc_new_york_summer():
    # EDT is UTC-4 in July. 19:00 local -> 23:00 UTC.
    local = datetime(2026, 7, 17, 19, 0, 0)
    assert local_naive_to_utc(local, "America/New_York") == datetime(2026, 7, 17, 23, 0, 0)


def test_local_naive_to_utc_utc_zone_identity():
    local = datetime(2026, 1, 1, 12, 0, 0)
    assert local_naive_to_utc(local, "UTC") == datetime(2026, 1, 1, 12, 0, 0)
