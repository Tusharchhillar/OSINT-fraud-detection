"""Structured JSON logging via ``structlog``.

Every module in the pipeline gets a logger like::

    from osint.logging_setup import get_logger
    log = get_logger(__name__)
    log.info("osint.scraper.telegram.message", platform="telegram", event_id="...")

All log events are namespaced under ``osint.*`` and every line carries a static
``service: osint`` field so the same line can be filtered in a multi-service
log aggregator.

Output is one JSON object per line on stdout *and* mirrored to the raw NDJSON audit
log so the same record is available to downstream consumers without re-parsing.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

from osint.config import get_settings

_CONFIGURED = False
_SERVICE = "osint"


def _add_static(
    _: Any, __: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Stamp every event with the static service field."""
    event_dict.setdefault("service", _SERVICE)
    return event_dict


def _prefix_event_name(
    _: Any, __: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Prefix the ``event`` field with ``osint.`` if it isn't already.

    Callers can still pass fully-qualified names like ``osint.scraper.telegram.x``;
    we only add the prefix when the user wrote a short name like ``"store.upsert"``.
    """
    name = event_dict.get("event")
    if isinstance(name, str) and not name.startswith("osint."):
        event_dict["event"] = f"osint.{name}"
    return event_dict


def _build_processors() -> list[Any]:
    """The processor chain shared by every logger."""
    return [
        structlog.contextvars.merge_contextvars,
        _add_static,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _prefix_event_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Final step: render as a single-line JSON string.
        structlog.processors.JSONRenderer(sort_keys=True),
    ]


def configure_logging() -> None:
    """Idempotently wire up stdout + file JSON logging.

    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    log_path: Path = settings.raw_log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) stdlib logging: route everything to stdout at the requested level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    # 2) Mirror the same JSON lines to the audit file via a dedicated handler.
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    # Attach to the root logger so structlog's final string lands there too.
    logging.getLogger().addHandler(file_handler)

    structlog.configure(
        processors=_build_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured logger. Configures logging on first use."""
    configure_logging()
    return structlog.get_logger(name)
