"""Application configuration loaded from environment variables."""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class MaxResolution(str, Enum):
    """Channel-wide maximum output resolution (a ceiling, never forced)."""

    original = "original"
    p1080 = "1080p"
    p720 = "720p"
    p480 = "480p"


class EncoderPreset(str, Enum):
    fast = "fast"
    balanced = "balanced"
    quality = "quality"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Timezone -----------------------------------------------------------
    tz: str = "America/New_York"

    # --- Plex ---------------------------------------------------------------
    plex_url: str = "http://192.168.1.10:32400"
    plex_token: str = ""
    plex_library_name: str = "Movies"
    plex_path_prefix: str = "/movies"
    local_path_prefix: str = "/media/movies"

    # --- Directories --------------------------------------------------------
    config_dir: Path = Path("/config")
    stream_dir: Path = Path("/stream")

    # --- Admin auth ---------------------------------------------------------
    admin_password: str = ""
    # Set true when served over HTTPS / behind a TLS-terminating reverse proxy
    # so the session cookie is only sent over secure connections.
    session_cookie_secure: bool = False

    # --- Encoding defaults --------------------------------------------------
    max_resolution: MaxResolution = MaxResolution.p1080
    video_bitrate_kbps: int = 8000
    audio_bitrate_kbps: int = 192
    encoder: str = "h264_nvenc"
    encoder_preset: EncoderPreset = EncoderPreset.balanced

    # --- Channel behaviour --------------------------------------------------
    # When true, the channel auto-enables on startup (resumes streaming from the
    # schedule after a restart). When false, the admin must press Start.
    channel_auto_start: bool = False

    # --- Server / logging ---------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # --- Derived paths ------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.config_dir / "movie-channel.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def secret_path(self) -> Path:
        return self.config_dir / "app_secret.key"

    @property
    def admin_hash_path(self) -> Path:
        return self.config_dir / "admin_password.hash"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
