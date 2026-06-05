"""Tests for the structured logging setup."""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import structlog

from osint.logging_setup import configure_logging, get_logger


def _capture_stdout(fn) -> str:
    """Run ``fn`` and return whatever was written to stdout."""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old_stdout
    return buf.getvalue()


def test_event_names_are_prefixed_with_osint() -> None:
    captured = _capture_stdout(lambda: get_logger("test").info("store.upsert", inserted=3))
    line = captured.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "osint.store.upsert"
    assert record["service"] == "osint"
    assert record["level"] == "info"
    assert "timestamp" in record
    assert record["inserted"] == 3


def test_already_prefixed_names_are_not_double_prefixed() -> None:
    captured = _capture_stdout(
        lambda: get_logger("test").info("osint.scraper.telegram.message", event_id="abc")
    )
    line = captured.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "osint.scraper.telegram.message"
    assert record["event_id"] == "abc"


def test_configure_logging_is_idempotent(temp_data_dir) -> None:
    """Multiple calls don't stack handlers or reconfigure."""
    configure_logging()
    initial_handlers = list(logging.getLogger().handlers)
    configure_logging()
    configure_logging()
    assert list(logging.getLogger().handlers) == initial_handlers
