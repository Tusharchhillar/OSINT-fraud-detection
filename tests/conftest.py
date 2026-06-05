"""Shared pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from osint.config import get_settings


@pytest.fixture
def temp_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the package at a fresh temp dir so tests don't touch the real DB."""
    monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OSINT_RAW_LOG", str(tmp_path / "raw" / "events.ndjson"))
    monkeypatch.setenv("OSINT_DB_PATH", str(tmp_path / "osint.db"))
    # The Settings object is cached; clear it so the new env vars take effect.
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
