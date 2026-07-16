"""Administrator API.

Every write action requires an authenticated session *and* a valid CSRF token,
enforced in the backend (never by hiding buttons in the UI). Authorization is
checked on the server for all routes below.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import Response as RawResponse
from sqlmodel import Session

from . import auth, plex_service, schedule_service, scheduler
from .database import get_session, get_settings_row
from .models import ScheduledMovie, utcnow
from .plex_client import PlexError
from .schedule_service import ScheduleError
from .schemas import (
    ActiveDaysUpdate,
    EncodingSettings,
    EncodingSettingsUpdate,
    LoginRequest,
    LoginResponse,
    PlexMovieOut,
    PlexStatus,
    ScheduleCreate,
    ScheduledMovieOut,
    ScheduleResponse,
    ScheduleUpdate,
    WhoAmIResponse,
)

from .logging_config import get_logger

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = get_logger("admin")


# --- Auth ------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, request: Request, response: Response
) -> LoginResponse:
    auth.check_rate_limit(request)
    if not auth.verify_password(payload.password):
        auth.record_failed_attempt(request)
        log.warning("failed admin login from %s", request.client.host if request.client else "?")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password.",
        )
    auth.reset_attempts(request)
    csrf = auth.start_session(response)
    return LoginResponse(ok=True, csrf_token=csrf)


@router.post("/logout")
def logout(response: Response, _: None = Depends(auth.require_admin)) -> dict:
    auth.clear_session(response)
    return {"ok": True}


@router.get("/whoami", response_model=WhoAmIResponse)
def whoami(request: Request) -> WhoAmIResponse:
    return WhoAmIResponse(
        authenticated=auth.is_authenticated(request),
        csrf_token=auth.session_csrf(request),
    )


# --- Encoding settings -----------------------------------------------------
@router.get("/encoding", response_model=EncodingSettings)
def get_encoding(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> EncodingSettings:
    row = get_settings_row(session)
    return EncodingSettings(
        maximum_resolution=row.maximum_resolution,
        video_bitrate_kbps=row.video_bitrate_kbps,
        audio_bitrate_kbps=row.audio_bitrate_kbps,
        encoder=row.encoder,
        encoder_preset=row.encoder_preset,
    )


@router.patch("/encoding", response_model=EncodingSettings)
def update_encoding(
    payload: EncodingSettingsUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> EncodingSettings:
    row = get_settings_row(session)
    if payload.maximum_resolution is not None:
        row.maximum_resolution = payload.maximum_resolution
    if payload.video_bitrate_kbps is not None:
        row.video_bitrate_kbps = payload.video_bitrate_kbps
    if payload.audio_bitrate_kbps is not None:
        row.audio_bitrate_kbps = payload.audio_bitrate_kbps
    if payload.encoder_preset is not None:
        row.encoder_preset = payload.encoder_preset
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return EncodingSettings(
        maximum_resolution=row.maximum_resolution,
        video_bitrate_kbps=row.video_bitrate_kbps,
        audio_bitrate_kbps=row.audio_bitrate_kbps,
        encoder=row.encoder,
        encoder_preset=row.encoder_preset,
    )


# --- Plex integration ------------------------------------------------------
@router.get("/plex/status", response_model=PlexStatus)
def plex_status(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> PlexStatus:
    row = get_settings_row(session)
    configured = plex_service.plex_configured()
    reachable = False
    library_found = False
    if configured:
        client = plex_service.make_client(row)
        reachable = client.ping()
        if reachable:
            try:
                client.movie_section_key()
                library_found = True
            except PlexError:
                library_found = False
    return PlexStatus(
        configured=configured,
        reachable=reachable,
        library_found=library_found,
        library_name=row.plex_library_name,
    )


@router.get("/plex/search", response_model=list[PlexMovieOut])
def plex_search(
    q: str,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> list[PlexMovieOut]:
    if not plex_service.plex_configured():
        raise HTTPException(status_code=503, detail="Plex is not configured.")
    row = get_settings_row(session)
    client = plex_service.make_client(row)
    try:
        movies = client.search_movies(q.strip()) if q.strip() else []
    except PlexError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return [plex_service.movie_to_out(m, row) for m in movies]


@router.get("/plex/movie/{rating_key}", response_model=PlexMovieOut)
def plex_movie(
    rating_key: str,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> PlexMovieOut:
    if not plex_service.plex_configured():
        raise HTTPException(status_code=503, detail="Plex is not configured.")
    row = get_settings_row(session)
    client = plex_service.make_client(row)
    try:
        movie = client.get_movie(rating_key)
    except PlexError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return plex_service.movie_to_out(movie, row)


@router.get("/plex/poster/{rating_key}")
def plex_poster(
    rating_key: str,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> RawResponse:
    """Proxy a movie poster from Plex so the token never reaches the browser."""
    if not plex_service.plex_configured():
        raise HTTPException(status_code=503, detail="Plex is not configured.")
    row = get_settings_row(session)
    client = plex_service.make_client(row)
    try:
        movie = client.get_movie(rating_key)
        if not movie.thumb_key:
            raise HTTPException(status_code=404, detail="No poster available.")
        upstream = client.fetch_image(movie.thumb_key)
    except PlexError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return RawResponse(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- Schedule: read --------------------------------------------------------
@router.get("/schedule", response_model=ScheduleResponse)
def get_schedule(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> ScheduleResponse:
    row = get_settings_row(session)
    return ScheduleResponse(
        movies=[_to_out(m) for m in scheduler.daily_lineup(session)],
        active_days=scheduler.mask_to_days(row.active_days_mask),
        timezone=row.timezone,
    )


@router.put("/schedule/active-days", response_model=ScheduleResponse)
def set_active_days(
    payload: ActiveDaysUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> ScheduleResponse:
    row = get_settings_row(session)
    row.active_days_mask = scheduler.days_to_mask(payload.active_days)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    log.info("active days set to %s", scheduler.mask_to_days(row.active_days_mask))
    return ScheduleResponse(
        movies=[_to_out(m) for m in scheduler.daily_lineup(session)],
        active_days=scheduler.mask_to_days(row.active_days_mask),
        timezone=row.timezone,
    )


# --- Schedule: mutate ------------------------------------------------------
@router.post("/schedule", response_model=ScheduledMovieOut, status_code=201)
def add_scheduled_movie(
    payload: ScheduleCreate,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> ScheduledMovieOut:
    if not plex_service.plex_configured():
        raise HTTPException(status_code=503, detail="Plex is not configured.")
    row = get_settings_row(session)

    client = plex_service.make_client(row)
    try:
        movie = client.get_movie(payload.plex_rating_key)
    except PlexError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        new_row = schedule_service.build_scheduled_movie(
            movie, payload.start_minute, row
        )
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if scheduler.has_overlap(session, new_row.start_minute, new_row.runtime_ms):
        raise HTTPException(
            status_code=409,
            detail="That time overlaps another movie in the daily lineup.",
        )

    session.add(new_row)
    session.commit()
    session.refresh(new_row)
    log.info(
        "schedule add id=%s '%s' minute=%s", new_row.id, new_row.title, new_row.start_minute
    )
    return _to_out(new_row)


@router.patch("/schedule/{movie_id}", response_model=ScheduledMovieOut)
def update_scheduled_movie(
    movie_id: int,
    payload: ScheduleUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> ScheduledMovieOut:
    existing = session.get(ScheduledMovie, movie_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled movie not found.")

    if scheduler.has_overlap(
        session, payload.start_minute, existing.runtime_ms, exclude_id=movie_id
    ):
        raise HTTPException(
            status_code=409,
            detail="That time overlaps another movie in the daily lineup.",
        )

    existing.start_minute = payload.start_minute
    existing.updated_at = utcnow()
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return _to_out(existing)


@router.delete("/schedule/{movie_id}")
def delete_scheduled_movie(
    movie_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> dict:
    existing = session.get(ScheduledMovie, movie_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled movie not found.")
    session.delete(existing)
    session.commit()
    log.info("schedule delete id=%s", movie_id)
    return {"ok": True}


def _to_out(m) -> ScheduledMovieOut:
    return ScheduledMovieOut(
        id=m.id,
        plex_rating_key=m.plex_rating_key,
        title=m.title,
        year=m.year,
        poster_url=m.poster_url,
        runtime_ms=m.runtime_ms,
        start_minute=m.start_minute,
    )


# --- Channel control & diagnostics (Milestone 5) ---------------------------
import time  # noqa: E402

from . import gpu  # noqa: E402
from .stream_runtime import app_started_at, controller, manager  # noqa: E402


def _channel_payload(session: Session) -> dict:
    """Manager status enriched with live schedule context."""
    row = get_settings_row(session)
    tz = row.timezone
    mask = row.active_days_mask
    st = manager.status()
    st["enabled"] = controller.enabled
    st["uptime_seconds"] = int(time.time() - app_started_at)
    gpu_stats = gpu.gpu_stats()
    st["gpu_name"] = gpu_stats["name"]
    st["gpu_encode_percent"] = gpu_stats["encode_percent"]
    active = scheduler.active_movie(session)
    if active is not None:
        bounds = scheduler.occurrence_bounds(active, tz, mask)
        st["live_offset_seconds"] = scheduler.playback_offset_seconds(active, tz, mask)
        st["scheduled_title"] = active.title
        st["scheduled_start"] = bounds[0].isoformat() + "Z" if bounds else None
        st["scheduled_end"] = bounds[1].isoformat() + "Z" if bounds else None
    else:
        st["live_offset_seconds"] = None
        st["scheduled_title"] = None
    nxt = scheduler.next_movie(session)
    st["next_title"] = nxt.title if nxt else None
    nxt_bounds = scheduler.occurrence_bounds(nxt, tz, mask) if nxt else None
    st["next_start"] = (nxt_bounds[0].isoformat() + "Z") if nxt_bounds else None
    return st


@router.post("/channel/start")
def channel_start(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> dict:
    controller.enable()
    log.info("channel started by admin")
    return _channel_payload(session)


@router.post("/channel/stop")
def channel_stop(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_csrf),
) -> dict:
    controller.disable()
    log.info("channel stopped by admin")
    return _channel_payload(session)


@router.get("/channel/status")
def channel_status(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> dict:
    return _channel_payload(session)


@router.get("/diagnostics")
def diagnostics(
    session: Session = Depends(get_session),
    _: None = Depends(auth.require_admin),
) -> dict:
    import os
    import shutil

    from sqlmodel import select

    from . import encoding
    from .config import settings as app_settings
    from .media_probe import source_file_exists

    row = get_settings_row(session)

    plex_reachable = False
    if plex_service.plex_configured():
        try:
            plex_reachable = plex_service.make_client(row).ping()
        except Exception:
            plex_reachable = False

    # "Movie mount" really means "can we read the library files". Playback reads
    # the source_path stored on each scheduled movie (translated once at schedule
    # time), so verify those directly. The path-prefix config is not a reliable
    # proxy: when Plex's paths already match the mount no translation is set, and
    # local_path_prefix may not point at a readable directory even though every
    # movie file is reachable. Fall back to the configured root only when there
    # is nothing scheduled to check.
    scheduled_paths = [
        m.source_path for m in session.exec(select(ScheduledMovie)).all() if m.source_path
    ]
    if scheduled_paths:
        mount_readable = any(source_file_exists(p) for p in scheduled_paths)
    else:
        local_root = row.local_path_prefix or app_settings.local_path_prefix
        mount_readable = (
            bool(local_root) and os.path.isdir(local_root) and os.access(local_root, os.R_OK)
        )

    stream_dir = app_settings.stream_dir
    try:
        stream_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    stream_writable = os.path.isdir(stream_dir) and os.access(stream_dir, os.W_OK)

    ffmpeg_installed = shutil.which("ffmpeg") is not None
    ffprobe_installed = shutil.which("ffprobe") is not None
    nvenc_is_listed = encoding.nvenc_listed() if ffmpeg_installed else False
    nvenc_ok, nvenc_detail = (
        encoding.verify_nvenc() if ffmpeg_installed else (False, "ffmpeg not installed")
    )

    return {
        "plex_reachable": plex_reachable,
        "database_reachable": True,
        "movie_mount_readable": mount_readable,
        "stream_dir_writable": stream_writable,
        "ffmpeg_installed": ffmpeg_installed,
        "ffprobe_installed": ffprobe_installed,
        "nvenc_listed": nvenc_is_listed,
        "nvenc_available": nvenc_ok,
        "nvenc_detail": nvenc_detail,
        "ffmpeg_process_alive": manager.is_process_alive(),
    }
