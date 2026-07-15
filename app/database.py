"""Database engine, session management, and one-time seeding."""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import inspect, text
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
    _drop_legacy_schedule()
    SQLModel.metadata.create_all(engine)
    _ensure_settings_columns()
    _seed_settings()


def _drop_legacy_schedule() -> None:
    """Drop a pre-daily ``scheduled_movies`` table so the new schema is created.

    The schedule moved from absolute dates to a repeating daily lineup, a
    breaking column change SQLite cannot migrate in place. If the existing
    table predates ``start_minute``, drop it (schedule is rebuilt by the admin).
    Runs once — after recreation the column exists and this is a no-op.
    """
    inspector = inspect(engine)
    if "scheduled_movies" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("scheduled_movies")}
    if "start_minute" not in columns:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE scheduled_movies"))


def _ensure_settings_columns() -> None:
    """Add columns introduced after the settings table was first created.

    SQLite can't do this via ``create_all``; add them in place so an existing
    deployment keeps its settings (timezone, Plex, encoding) across the upgrade.
    """
    inspector = inspect(engine)
    if "settings" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("settings")}
    if "active_days_mask" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE settings ADD COLUMN active_days_mask INTEGER DEFAULT 127")
            )


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
