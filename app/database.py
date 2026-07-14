"""Database engine, session management, and one-time seeding."""
from __future__ import annotations

from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings
from .models import Settings as SettingsRow

# check_same_thread=False is required because FastAPI may touch the SQLite
# connection from different threads. SQLite handles our low concurrency fine.
_connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=_connect_args,
)


def init_db() -> None:
    """Create tables and ensure the singleton settings row exists."""
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _seed_settings()


def _seed_settings() -> None:
    """Insert the single settings row from env defaults if absent."""
    with Session(engine) as session:
        existing = session.get(SettingsRow, 1)
        if existing is not None:
            return
        row = SettingsRow(
            id=1,
            timezone=settings.tz,
            plex_url=settings.plex_url,
            plex_library_name=settings.plex_library_name,
            plex_path_prefix=settings.plex_path_prefix,
            local_path_prefix=settings.local_path_prefix,
            maximum_resolution=settings.max_resolution,
            video_bitrate_kbps=settings.video_bitrate_kbps,
            audio_bitrate_kbps=settings.audio_bitrate_kbps,
            encoder=settings.encoder,
            encoder_preset=settings.encoder_preset,
        )
        session.add(row)
        session.commit()


def get_settings_row(session: Session) -> SettingsRow:
    """Return the singleton settings row, creating it if somehow missing."""
    row = session.get(SettingsRow, 1)
    if row is None:  # pragma: no cover - defensive
        row = SettingsRow(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    with Session(engine) as session:
        yield session
