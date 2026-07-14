"""Public, strictly read-only API.

These routes never modify state and never return sensitive data (Plex token,
server URL, filesystem paths, FFmpeg commands, env, session info). There are
deliberately no public write routes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response as RawResponse
from sqlmodel import Session, select

from . import plex_service, scheduler
from .database import get_session, get_settings_row
from .models import ScheduledMovie
from .plex_client import PlexError
from .schemas import (
    NowPlaying,
    PublicChannelConfig,
    PublicStatus,
    UpcomingItem,
)

router = APIRouter(prefix="/api/public", tags=["public"])


def _utc(dt: datetime) -> datetime:
    """Tag a stored naive-UTC datetime as UTC so its JSON carries +00:00 and the
    browser converts to the channel timezone rather than assuming local time."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _now_playing(session: Session) -> NowPlaying | None:
    movie = scheduler.active_movie(session)
    if movie is None:
        return None
    return NowPlaying(
        title=movie.title,
        year=movie.year,
        poster_url=movie.poster_url,
        scheduled_start=_utc(movie.scheduled_start),
        scheduled_end=_utc(movie.scheduled_end),
        progress_seconds=scheduler.playback_offset_seconds(movie),
        runtime_seconds=int(movie.runtime_ms / 1000),
    )


@router.get("/status", response_model=PublicStatus)
def status(session: Session = Depends(get_session)) -> PublicStatus:
    row = get_settings_row(session)
    playing = _now_playing(session)
    nxt = scheduler.next_movie(session)
    next_up = (
        UpcomingItem(
            title=nxt.title,
            year=nxt.year,
            poster_url=nxt.poster_url,
            scheduled_start=_utc(nxt.scheduled_start),
        )
        if nxt
        else None
    )
    return PublicStatus(
        state="on_air" if playing else "off_air",
        timezone=row.timezone,
        now_playing=playing,
        next_up=next_up,
    )


@router.get("/now-playing", response_model=NowPlaying | None)
def now_playing(session: Session = Depends(get_session)) -> NowPlaying | None:
    return _now_playing(session)


@router.get("/upcoming", response_model=list[UpcomingItem])
def upcoming(session: Session = Depends(get_session)) -> list[UpcomingItem]:
    return [
        UpcomingItem(
            title=m.title,
            year=m.year,
            poster_url=m.poster_url,
            scheduled_start=_utc(m.scheduled_start),
        )
        for m in scheduler.upcoming_movies(session, limit=10)
    ]


@router.get("/channel-config", response_model=PublicChannelConfig)
def channel_config(session: Session = Depends(get_session)) -> PublicChannelConfig:
    row = get_settings_row(session)
    # Only non-sensitive display config. No Plex URL/token, no paths.
    return PublicChannelConfig(timezone=row.timezone)


@router.get("/poster/{rating_key}")
def poster(
    rating_key: str, session: Session = Depends(get_session)
) -> RawResponse:
    """Serve a poster for a *scheduled* movie only.

    Gated on the schedule so this is not an open proxy to arbitrary Plex keys.
    The Plex token is used server-side and never sent to the browser.
    """
    exists = session.exec(
        select(ScheduledMovie).where(
            ScheduledMovie.plex_rating_key == rating_key
        )
    ).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="Not found.")

    if not plex_service.plex_configured():
        raise HTTPException(status_code=404, detail="Poster unavailable.")

    row = get_settings_row(session)
    client = plex_service.make_client(row)
    try:
        movie = client.get_movie(rating_key)
        if not movie.thumb_key:
            raise HTTPException(status_code=404, detail="No poster.")
        upstream = client.fetch_image(movie.thumb_key)
    except PlexError:
        raise HTTPException(status_code=404, detail="Poster unavailable.")
    return RawResponse(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )
