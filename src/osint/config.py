"""Runtime configuration loaded from environment variables.

We read `.env` once at import time and expose a small, typed `Settings` object so
downstream code never reaches into ``os.environ`` directly. This makes tests trivial
(monkeypatch the env) and keeps secrets out of the source tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present. ``override=False`` means real env vars
# always win, which is what we want in CI / containers.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)


def _get_str(key: str, default: str) -> str:
    value = os.getenv(key)
    return value if value is not None and value != "" else default


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {key}={raw!r} is not a valid int") from exc


@dataclass(frozen=True)
class Settings:
    """Immutable, lazily-loaded runtime configuration."""

    # Logging / runtime
    env: str
    log_level: str

    # Paths
    data_dir: Path
    raw_log_path: Path
    db_path: Path

    # Ollama
    ollama_host: str
    ollama_model: str
    ollama_timeout_s: int

    # Risk
    alert_threshold: int

    # Telegram
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session: str

    # Scraping
    user_agent: str
    rate_per_min: int

    @property
    def is_dev(self) -> bool:
        return self.env.lower() == "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    ``lru_cache`` gives us a process-wide singleton without module-level mutation.
    Tests that need a fresh config can call ``get_settings.cache_clear()``.
    """
    data_dir = Path(_get_str("OSINT_DATA_DIR", "./data")).resolve()
    return Settings(
        env=_get_str("OSINT_ENV", "dev"),
        log_level=_get_str("OSINT_LOG_LEVEL", "INFO"),
        data_dir=data_dir,
        raw_log_path=Path(_get_str("OSINT_RAW_LOG", str(data_dir / "raw" / "events.ndjson"))).resolve(),
        db_path=Path(_get_str("OSINT_DB_PATH", str(data_dir / "osint.db"))).resolve(),
        ollama_host=_get_str("OSINT_OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=_get_str("OSINT_OLLAMA_MODEL", "llama3.1"),
        ollama_timeout_s=_get_int("OSINT_OLLAMA_TIMEOUT_S", 60),
        alert_threshold=_get_int("OSINT_ALERT_THRESHOLD", 70),
        telegram_api_id=_get_int("TELEGRAM_API_ID", 0) or None,
        telegram_api_hash=_get_str("TELEGRAM_API_HASH", "") or None,
        telegram_session=_get_str("TELEGRAM_SESSION", "osint_session"),
        user_agent=_get_str(
            "SCRAPER_USER_AGENT",
            "Mozilla/5.0 (compatible; OSINT-Research/0.1; +contact-email)",
        ),
        rate_per_min=_get_int("SCRAPER_RATE_PER_MIN", 20),
    )
