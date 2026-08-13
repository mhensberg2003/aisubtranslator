"""Configuration and filesystem conventions.

Secrets come from the environment only; nothing here ever writes an API key to
disk. Style Preferences live at the XDG config path so they are edited once and
apply everywhere, with a per-Work override picked up from the Work directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "aisubtranslator"
WORK_DIR_NAME = ".aisubtranslator"
STYLE_FILENAME = "style.toml"

DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class Settings(BaseSettings):
    """Runtime settings, read from the environment.

    `openrouter_api_key` is intentionally the only secret and has no default -
    a missing key is reported as a configuration error with a hint, not a
    stack trace.
    """

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = DEFAULT_BASE_URL
    aisubtranslator_model: str = DEFAULT_MODEL

    # Chunking. These are the first numbers worth tuning once real output has
    # been read; they are not load-bearing for correctness.
    chunk_size: int = 60
    context_cues: int = 6
    max_concurrency: int = 4
    request_timeout_seconds: float = 180.0
    max_repair_attempts: int = 2


def config_dir() -> Path:
    """XDG config directory for this app."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


def global_style_path() -> Path:
    return config_dir() / STYLE_FILENAME


def work_dir_for(media_path: Path) -> Path:
    """The Work a media file belongs to: its containing directory."""
    return media_path.expanduser().resolve().parent


def work_state_dir(work_dir: Path) -> Path:
    return work_dir / WORK_DIR_NAME


def work_style_path(work_dir: Path) -> Path:
    return work_state_dir(work_dir) / STYLE_FILENAME
