"""Schedule queries and timezone helpers.

The foundation needs read-side scheduling logic: which movie is active right
now, what is coming up, and how to build the rolling 7-day calendar. The
FFmpeg-driving stream loop arrives in a later milestone; these pure functions
are what it (and the public API) will build on, so they are unit-tested now.

Convention: everything persisted and compared internally is naive UTC. Display
happens only at the API edge, using the configured timezone.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .models import ScheduledMovie


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """Normalise any datetime to naive UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def local_day_bounds_utc(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """Return [start, end) of a local calendar day expressed in naive UTC."""
    tz = ZoneInfo(tz_name)
    start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def rolling_days(tz_name: str, count: int = 7, now: Optional[datetime] = None) -> List[date]:
    """List of ``count`` local dates starting today in the configured tz."""
    tz = ZoneInfo(tz_name)
    now = now or utcnow()
    today_local = now.replace(tzinfo=timezone.utc).astimezone(tz).date()
    return [today_local + timedelta(days=i) for i in range(count)]


def movies_for_day(
    session: Session, day: date, tz_name: str
) -> List[ScheduledMovie]:
    start_utc, end_utc = local_day_bounds_utc(day, tz_name)
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start >= start_utc)
        .where(ScheduledMovie.scheduled_start < end_utc)
        .order_by(ScheduledMovie.scheduled_start)
    )
    return list(session.exec(stmt))


def active_movie(
    session: Session, now: Optional[datetime] = None
) -> Optional[ScheduledMovie]:
    """The movie where ``scheduled_start <= now < scheduled_end``.

    Live-TV semantics: at most one movie is active. If schedules overlap (which
    the admin API prevents on write) we return the earliest-starting match.
    """
    now = now or utcnow()
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start <= now)
        .where(ScheduledMovie.scheduled_end > now)
        .order_by(ScheduledMovie.scheduled_start)
    )
    return session.exec(stmt).first()


def active_or_imminent_movie(
    session: Session,
    preroll_seconds: int = 0,
    now: Optional[datetime] = None,
) -> Optional[ScheduledMovie]:
    """The movie to have ffmpeg running for right now, including pre-roll.

    Like :func:`active_movie` but also returns a movie whose start is at most
    ``preroll_seconds`` in the future, so the encoder can warm up before air
    time. The playback offset is clamped to 0 for a not-yet-started movie by
    :func:`playback_offset_seconds`, so pre-roll simply begins the film at 0.
    """
    now = now or utcnow()
    horizon = now + timedelta(seconds=max(0, preroll_seconds))
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start <= horizon)
        .where(ScheduledMovie.scheduled_end > now)
        .order_by(ScheduledMovie.scheduled_start)
    )
    return session.exec(stmt).first()


def next_movie(
    session: Session, now: Optional[datetime] = None
) -> Optional[ScheduledMovie]:
    now = now or utcnow()
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start > now)
        .order_by(ScheduledMovie.scheduled_start)
    )
    return session.exec(stmt).first()


def upcoming_movies(
    session: Session, limit: int = 5, now: Optional[datetime] = None
) -> List[ScheduledMovie]:
    now = now or utcnow()
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start > now)
        .order_by(ScheduledMovie.scheduled_start)
        .limit(limit)
    )
    return list(session.exec(stmt))


def playback_offset_seconds(
    movie: ScheduledMovie, now: Optional[datetime] = None
) -> int:
    """Seconds elapsed since the movie's scheduled start, clamped to runtime."""
    now = now or utcnow()
    elapsed = int((now - movie.scheduled_start).total_seconds())
    runtime = int(movie.runtime_ms / 1000)
    if elapsed < 0:
        return 0
    if runtime and elapsed > runtime:
        return runtime
    return elapsed


def has_overlap(
    session: Session,
    start: datetime,
    end: datetime,
    exclude_id: Optional[int] = None,
) -> bool:
    """True if [start, end) overlaps any existing scheduled movie.

    Two intervals overlap iff ``a.start < b.end`` and ``b.start < a.end``.
    """
    stmt = (
        select(ScheduledMovie)
        .where(ScheduledMovie.scheduled_start < end)
        .where(ScheduledMovie.scheduled_end > start)
    )
    for existing in session.exec(stmt):
        if exclude_id is not None and existing.id == exclude_id:
            continue
        return True
    return False


def local_naive_to_utc(local_dt: datetime, tz_name: str) -> datetime:
    """Interpret a naive local datetime in ``tz_name`` and return naive UTC.

    Used when the admin picks a start time: the browser sends a wall-clock
    ``YYYY-MM-DDTHH:MM`` value which we anchor to the configured timezone before
    persisting in UTC. A naive input is assumed to be local; an aware input is
    respected.
    """
    tz = ZoneInfo(tz_name)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
