"""Tests for schedule logic: end-time, overlap, active/next lookup, offset."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import scheduler
from app.media_probe import calculate_end_time
from app.models import ScheduledMovie


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _add(session, title, start, runtime_ms):
    m = ScheduledMovie(
        plex_rating_key=title,
        title=title,
        runtime_ms=runtime_ms,
        scheduled_start=start,
        scheduled_end=calculate_end_time(start, runtime_ms),
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


# --- End time --------------------------------------------------------------
def test_calculate_end_time_uses_runtime():
    start = datetime(2026, 7, 17, 19, 0, 0)
    # Back to the Future ~ 116 min
    end = calculate_end_time(start, 116 * 60 * 1000)
    assert end == datetime(2026, 7, 17, 20, 56, 0)


def test_calculate_end_time_rejects_negative():
    with pytest.raises(ValueError):
        calculate_end_time(datetime(2026, 1, 1), -1)


# --- Overlap detection -----------------------------------------------------
def test_overlap_detected(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    _add(session, "A", base, 120 * 60 * 1000)  # 19:00-21:00
    # 20:00-21:00 overlaps A
    assert scheduler.has_overlap(session, base + timedelta(hours=1), base + timedelta(hours=2))


def test_no_overlap_for_adjacent(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    a = _add(session, "A", base, 60 * 60 * 1000)  # 19:00-20:00
    # 20:00-21:00 is adjacent, not overlapping
    assert not scheduler.has_overlap(session, a.scheduled_end, a.scheduled_end + timedelta(hours=1))


def test_overlap_excludes_self(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    a = _add(session, "A", base, 60 * 60 * 1000)
    # Editing A itself should not conflict with its own row.
    assert not scheduler.has_overlap(
        session, a.scheduled_start, a.scheduled_end, exclude_id=a.id
    )


# --- Active / next / offset ------------------------------------------------
def test_active_movie_lookup(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    a = _add(session, "A", base, 120 * 60 * 1000)  # 19:00-21:00
    now = base + timedelta(minutes=35)
    active = scheduler.active_movie(session, now=now)
    assert active is not None and active.id == a.id


def test_no_active_movie_in_gap(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    _add(session, "A", base, 60 * 60 * 1000)  # 19:00-20:00
    now = base + timedelta(hours=1, minutes=30)  # 20:30 gap
    assert scheduler.active_movie(session, now=now) is None


def test_next_movie(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    _add(session, "A", base, 60 * 60 * 1000)
    b = _add(session, "B", base + timedelta(hours=2), 60 * 60 * 1000)
    now = base + timedelta(minutes=30)
    nxt = scheduler.next_movie(session, now=now)
    assert nxt is not None and nxt.id == b.id


def test_playback_offset(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    a = _add(session, "A", base, 120 * 60 * 1000)
    now = base + timedelta(minutes=35)
    assert scheduler.playback_offset_seconds(a, now=now) == 35 * 60


def test_playback_offset_clamped_to_runtime(session):
    base = datetime(2026, 7, 17, 19, 0, 0)
    a = _add(session, "A", base, 60 * 60 * 1000)  # 1h runtime
    now = base + timedelta(hours=5)
    assert scheduler.playback_offset_seconds(a, now=now) == 60 * 60


def test_rolling_days_length():
    days = scheduler.rolling_days("America/New_York", count=7)
    assert len(days) == 7
    # strictly increasing
    assert all(days[i] < days[i + 1] for i in range(len(days) - 1))
