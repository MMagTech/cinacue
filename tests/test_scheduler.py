"""Tests for the daily-lineup schedule logic: overlap, active/next, offset,
per-weekday on/off, midnight spill, and pre-roll."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import scheduler
from app.database import get_settings_row
from app.models import ScheduledMovie
from app.models import Settings as SettingsRow

TZ = "America/New_York"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SettingsRow(id=1, timezone=TZ, active_days_mask=scheduler.ALL_DAYS_MASK))
        s.commit()
        yield s


def _min(h: int, m: int = 0) -> int:
    return h * 60 + m


def _utc(y, mo, d, h, mi, sec=0) -> datetime:
    """Naive-UTC instant for a wall-clock time in the channel timezone."""
    local = datetime(y, mo, d, h, mi, sec, tzinfo=ZoneInfo(TZ))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _add(session, title, start_minute, runtime_ms):
    m = ScheduledMovie(
        plex_rating_key=title,
        title=title,
        runtime_ms=runtime_ms,
        start_minute=start_minute,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _set_days(session, days):
    row = get_settings_row(session)
    row.active_days_mask = scheduler.days_to_mask(days)
    session.add(row)
    session.commit()


# --- Overlap detection (circular 24h) --------------------------------------
def test_overlap_detected(session):
    _add(session, "A", _min(19), 120 * 60 * 1000)  # 19:00-21:00
    assert scheduler.has_overlap(session, _min(20), 60 * 60 * 1000)  # 20:00 inside


def test_no_overlap_for_adjacent(session):
    _add(session, "A", _min(19), 60 * 60 * 1000)  # 19:00-20:00
    assert not scheduler.has_overlap(session, _min(20), 60 * 60 * 1000)  # 20:00-21:00


def test_overlap_excludes_self(session):
    a = _add(session, "A", _min(19), 60 * 60 * 1000)
    assert not scheduler.has_overlap(
        session, a.start_minute, a.runtime_ms, exclude_id=a.id
    )


def test_overlap_wraps_past_midnight(session):
    _add(session, "Late", _min(23), 120 * 60 * 1000)  # 23:00 -> 01:00 next day
    # A 00:30 movie collides with the previous day's spill.
    assert scheduler.has_overlap(session, _min(0, 30), 60 * 60 * 1000)


# --- Active / next / offset ------------------------------------------------
def test_active_movie_lookup(session):
    a = _add(session, "A", _min(19), 120 * 60 * 1000)  # 19:00-21:00
    now = _utc(2026, 7, 17, 19, 35)  # Friday
    active = scheduler.active_movie(session, now=now)
    assert active is not None and active.id == a.id


def test_no_active_movie_in_gap(session):
    _add(session, "A", _min(19), 60 * 60 * 1000)  # 19:00-20:00
    now = _utc(2026, 7, 17, 20, 30)  # gap
    assert scheduler.active_movie(session, now=now) is None


def test_next_movie(session):
    _add(session, "A", _min(19), 60 * 60 * 1000)
    b = _add(session, "B", _min(21), 60 * 60 * 1000)
    now = _utc(2026, 7, 17, 19, 30)
    nxt = scheduler.next_movie(session, now=now)
    assert nxt is not None and nxt.id == b.id


def test_playback_offset(session):
    a = _add(session, "A", _min(19), 120 * 60 * 1000)
    now = _utc(2026, 7, 17, 19, 35)
    assert (
        scheduler.playback_offset_seconds(a, TZ, scheduler.ALL_DAYS_MASK, now=now)
        == 35 * 60
    )


def test_offset_zero_when_not_airing(session):
    a = _add(session, "A", _min(19), 60 * 60 * 1000)  # ends 20:00
    now = _utc(2026, 7, 17, 23, 0)
    assert scheduler.playback_offset_seconds(a, TZ, scheduler.ALL_DAYS_MASK, now=now) == 0


# --- Per-weekday on/off ----------------------------------------------------
def test_inactive_day_is_off_air(session):
    _add(session, "A", _min(19), 60 * 60 * 1000)
    _set_days(session, [0, 1, 2, 3, 4])  # Mon-Fri on; Sat/Sun off
    assert scheduler.active_movie(session, now=_utc(2026, 7, 17, 19, 30)) is not None  # Fri
    assert scheduler.active_movie(session, now=_utc(2026, 7, 18, 19, 30)) is None  # Sat


def test_next_skips_inactive_days(session):
    a = _add(session, "A", _min(19), 60 * 60 * 1000)
    _set_days(session, [0, 1, 2, 3, 4])  # Mon-Fri
    now = _utc(2026, 7, 17, 20, 0)  # Friday, after it aired
    nxt = scheduler.next_movie(session, now=now)
    bounds = scheduler.occurrence_bounds(a, TZ, scheduler.days_to_mask([0, 1, 2, 3, 4]), now=now)
    assert nxt is not None and nxt.id == a.id
    assert bounds is not None and bounds[0] == _utc(2026, 7, 20, 19, 0)  # next Monday


def test_midnight_spill_plays_into_off_day(session):
    a = _add(session, "Late", _min(23), 120 * 60 * 1000)  # Fri 23:00 -> Sat 01:00
    _set_days(session, [0, 1, 2, 3, 4])  # Sat is OFF
    now = _utc(2026, 7, 18, 0, 30)  # Saturday 00:30, mid-film
    active = scheduler.active_movie(session, now=now)
    assert active is not None and active.id == a.id  # started Friday, keeps playing
    assert (
        scheduler.playback_offset_seconds(a, TZ, scheduler.days_to_mask([0, 1, 2, 3, 4]), now=now)
        == 90 * 60
    )


# --- Pre-roll --------------------------------------------------------------
def test_active_or_imminent_covers_preroll(session):
    a = _add(session, "A", _min(19), 60 * 60 * 1000)
    now = _utc(2026, 7, 17, 18, 59, 40)  # 20s before start
    assert scheduler.active_movie(session, now=now) is None
    imminent = scheduler.active_or_imminent_movie(session, preroll_seconds=30, now=now)
    assert imminent is not None and imminent.id == a.id
