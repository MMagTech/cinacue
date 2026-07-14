"""FastAPI application entrypoint.

Wires the public and admin routers, exposes ``/health``, seeds the database and
admin account on startup, runs the channel controller loop, serves the RAM HLS
output at ``/stream``, applies baseline security headers, and serves the
compiled React frontend as a SPA.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, auth
from .admin_api import router as admin_router
from .config import settings
from .database import init_db
from .logging_config import get_logger, setup_logging
from .public_api import router as public_router
from .schemas import HealthResponse
from .stream_runtime import controller, manager

FRONTEND_DIR = Path(__file__).parent / "static"
log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    init_db()
    auth.seed_admin_from_env()
    log.info("starting up; timezone=%s", settings.tz)
    if not auth.admin_password_is_set():
        log.warning("no admin password set — set ADMIN_PASSWORD to enable login")
    manager.kill_orphans()
    manager.clean_stream_dir()
    controller.start_loop()
    if settings.channel_auto_start:
        log.info("channel auto-start enabled")
        controller.enable()
    try:
        yield
    finally:
        log.info("shutting down; stopping stream")
        controller.stop_loop()


app = FastAPI(title="Movie Channel", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers on every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-XSS-Protection", "0")
    return response


app.include_router(public_router)
app.include_router(admin_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Basic liveness. No auth, no sensitive data."""
    return HealthResponse(
        status="ok",
        version=__version__,
        time_utc=datetime.now(timezone.utc),
    )


# --- HLS output ------------------------------------------------------------
settings.stream_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/stream",
    StaticFiles(directory=str(settings.stream_dir), check_dir=False, html=False),
    name="stream",
)

# --- Static frontend (SPA) -------------------------------------------------
if (FRONTEND_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR / "assets"),
        name="assets",
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """Serve the SPA shell for any non-API, non-stream path."""
    if full_path.startswith(("api/", "health", "stream/", "assets/")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = FRONTEND_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        {
            "detail": "Frontend not built. Run `npm run build` in ./frontend "
            "or use the Docker image.",
        },
        status_code=200,
    )
