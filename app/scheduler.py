"""Daily-repeating schedule with per-weekday on/off, plus timezone helpers.

The schedule is a single daily lineup: each movie sits at a time-of-day
(``start_minute``, in the channel timezone) and airs every day at that slot.
Which weekdays actually air is a channel setting (a 7-bit mask); on inactive
days the channel is off air. A movie is governed by the day it *starts*, so a
late film that begins on an active day plays through past midnight even if the
next day is off.

Convention: absolute times are naive UTC; the daily slot is wall-clock local.
Occurrences are computed against the timezone each day, so DST is handled at
read time.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .database import get_settings_row
from .models import ScheduledMovie

DAY_MINUTES = 24 * 60
ALL_DAYS_MASK = 127  # bits 0..6 set
WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- active-days mask helpers ----------------------------------------------
def mask_to_days(mask: int) -> List[int]:
    """Active weekday numbers (0=Mon..6=Sun) from a 7-bit mask, sorted."""
    return [d for d in range(7) if mask & (1 << d)]


def days_to_mask(days: List[int]) -> int:
    """7-bit mask from a list of weekday numbers (0=Mon..6=Sun)."""
    mask = 0
    for d in days:
        if 0 <= d <= 6:
            mask |= 1 << d
    return mask


def _day_active(weekday: int, mask: int) -> bool:
    return bool(mask & (1 << weekday))


# --- timezone helpers ------------------------------------------------------
def _settings(session: Session):
    return get_settings_row(session)


def _local_now(now: datetime, tz_name: str) -> datetime:
    """Convert naive-UTC ``now`` to an aware datetime in the channel tz."""
    return now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))


def _to_utc_naive(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def runtime_minutes(movie: ScheduledMovie) -> int:
    return max(1, ceil(movie.runtime_ms / 60000)) if movie.runtime_ms else 1


def _slot_start(local_day: date, start_minute: int, tz: ZoneInfo) -> datetime:
    """Aware local datetime for a slot on a given local date (DST-correct)."""
    naive = datetime(local_day.year, local_day.month, local_day.day) + timedelta(
        minutes=start_minute
    )
    return naive.replace(tzinfo=tz)


def _most_recent_start(movie: ScheduledMovie, now_local: datetime, tz: ZoneInfo) -> datetime:
    """Aware local datetime of this movie's latest daily start at or before now."""
    start = _slot_start(now_local.date(), movie.start_minute, tz)
    if start > now_local:
        start = _slot_start(now_local.date() - timedelta(days=1), movie.start_minute, tz)
    return start


def _next_active_start(
    movie: ScheduledMovie, now_local: datetime, tz: ZoneInfo, mask: int
) -> Optional[datetime]:
    """Aware local datetime of this movie's next start after now on an active day."""
    for i in range(0, 8):
        day = now_local.date() + timedelta(days=i)
        if not _day_active(day.weekday(), mask):
            continue
        start = _slot_start(day, movie.start_minute, tz)
        if start > now_local:
            return start
    return None


# --- occurrence resolution -------------------------------------------------
def _all(session: Session) -> List[ScheduledMovie]:
    return list(session.exec(select(ScheduledMovie)))


def current_occurrence_start(
    movie: ScheduledMovie, tz_name: str, mask: int, now: Optional[datetime] = None
) -> Optional[datetime]:
    """Naive-UTC start of the occurrence containing ``now``, or None if off.

    The occurrence airs only if the weekday it *started on* is active.
    """
    now = now or utcnow()
    tz = ZoneInfo(tz_name)
    now_local = _local_now(now, tz_name)
    start = _most_recent_start(movie, now_local, tz)
    end = start + timedelta(minutes=runtime_minutes(movie))
    if start <= now_local < end and _day_active(start.weekday(), mask):
        return _to_utc_naive(start)
    return None


def occurrence_bounds(
    movie: ScheduledMovie, tz_name: str, mask: int, now: Optional[datetime] = None
) -> Optional[Tuple[datetime, datetime]]:
    """Naive-UTC (start, end) of the current occurrence, else the next one.

    Returns None if the movie has no upcoming airing (e.g. all days inactive).
    """
    now = now or utcnow()
    tz = ZoneInfo(tz_name)
    now_local = _local_now(now, tz_name)
    start = _most_recent_start(movie, now_local, tz)
    end = start + timedelta(minutes=runtime_minutes(movie))
    if start <= now_local < end and _day_active(start.weekday(), mask):
        return _to_utc_naive(start), _to_utc_naive(end)
    nxt = _next_active_start(movie, now_local, tz, mask)
    if nxt is None:
        return None
    return _to_utc_naive(nxt), _to_utc_naive(nxt + timedelta(minutes=runtime_minutes(movie)))


def _run_start(
    movie: ScheduledMovie, tz_name: str, mask: int, now: datetime, preroll_seconds: int
) -> Optional[datetime]:
    """Naive-UTC start the encoder should use now (active, or within pre-roll)."""
    current = current_occurrence_start(movie, tz_name, mask, now)
    if current is not None:
        return current
    if preroll_seconds > 0:
        tz = ZoneInfo(tz_name)
        now_local = _local_now(now, tz_name)
        nxt = _next_active_start(movie, now_local, tz, mask)
        if nxt is not None and nxt <= now_local + timedelta(seconds=preroll_seconds):
            return _to_utc_naive(nxt)
    return None


def active_movie(
    session: Session, now: Optional[datetime] = None
) -> Optional[ScheduledMovie]:
    """The movie airing right now (live-TV semantics: at most one)."""
    now = now or utcnow()
    row = _settings(session)
    for movie in _all(session):
        if current_occurrence_start(movie, row.timezone, row.active_days_mask, now) is not None:
            return movie
    return None


def active_or_imminent_movie(
    session: Session, preroll_seconds: int = 0, now: Optional[datetime] = None
) -> Optional[ScheduledMovie]:
    """The movie to have ffmpeg running for now, including pre-roll warm-up."""
    now = now or utcnow()
    row = _settings(session)
    for movie in _all(session):
        if _run_start(movie, row.timezone, row.active_days_mask, now, preroll_seconds) is not None:
            return movie
    return None


def next_movie(
    session: Session, now: Optional[datetime] = None
) -> Optional[ScheduledMovie]:
    """The next movie to air after now (soonest upcoming active-day slot)."""
    now = now or utcnow()
    row = _settings(session)
    tz = ZoneInfo(row.timezone)
    now_local = _local_now(now, row.timezone)
    best: Optional[ScheduledMovie] = None
    best_start: Optional[datetime] = None
    for movie in _all(session):
        start = _next_active_start(movie, now_local, tz, row.active_days_mask)
        if start is None:
            continue
        if best_start is None or start < best_start:
            best_start = start
            best = movie
    return best


def upcoming_movies(
    session: Session, limit: int = 5, now: Optional[datetime] = None
) -> List[ScheduledMovie]:
    """The next ``limit`` airings in chronological order over coming days."""
    now = now or utcnow()
    row = _settings(session)
    tz = ZoneInfo(row.timezone)
    now_local = _local_now(now, row.timezone)
    dated: List[Tuple[datetime, ScheduledMovie]] = []
    for movie in _all(session):
        start = _next_active_start(movie, now_local, tz, row.active_days_mask)
        if start is not None:
            dated.append((start, movie))
    dated.sort(key=lambda pair: pair[0])
    return [movie for _, movie in dated[:limit]]


def playback_offset_seconds(
    movie: ScheduledMovie, tz_name: str, mask: int, now: Optional[datetime] = None
) -> int:
    """Seconds since the current occurrence's start, clamped to the runtime."""
    now = now or utcnow()
    start = current_occurrence_start(movie, tz_name, mask, now)
    if start is None:
        return 0
    elapsed = int((now - start).total_seconds())
    runtime = int(movie.runtime_ms / 1000)
    if elapsed < 0:
        return 0
    if runtime and elapsed > runtime:
        return runtime
    return elapsed


# --- lineup + overlap ------------------------------------------------------
def daily_lineup(session: Session) -> List[ScheduledMovie]:
    """All movies in the daily lineup, sorted by start time."""
    return sorted(_all(session), key=lambda m: m.start_minute)


def has_overlap(
    session: Session,
    start_minute: int,
    runtime_ms: int,
    exclude_id: Optional[int] = None,
) -> bool:
    """True if a daily slot overlaps another, on the circular 24-hour timeline.

    A late movie may spill past midnight, so each existing slot is tested at
    -1/0/+1 day offsets to catch wraparound against the next day's lineup.
    """
    a = start_minute
    ra = max(1, ceil(runtime_ms / 60000))
    for movie in _all(session):
        if exclude_id is not None and movie.id == exclude_id:
            continue
        b = movie.start_minute
        rb = max(1, ceil(movie.runtime_ms / 60000))
        for k in (-DAY_MINUTES, 0, DAY_MINUTES):
            if a < b + k + rb and b + k < a + ra:
                return True
    return False


def local_naive_to_utc(local_dt: datetime, tz_name: str) -> datetime:
    """Interpret a naive local datetime in ``tz_name`` and return naive UTC."""
    tz = ZoneInfo(tz_name)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
