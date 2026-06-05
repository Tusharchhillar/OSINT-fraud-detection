"""Shared Playwright browser utilities for the M3 scrapers.

All M3 scrapers (Instagram, X, WhatsApp) need a headless Chromium with a sane
user agent. To avoid spinning up a fresh browser per scrape, we expose a
small context-manager helper that lazy-creates a single browser and reuses
it across calls inside the same Python process.

The scrapers themselves never call :mod:`playwright` directly — they go
through this module. That way:

* We can stub the browser out in tests with a fixture.
* Rate-limit / user-agent logic lives in one place.
* Swapping the backend (e.g. to ``httpx``) is a one-file change.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from osint.config import get_settings
from osint.logging_setup import get_logger

log = get_logger(__name__)

_BROWSER_SINGLETON: Any = None
_LAST_NAVIGATION_TS: float = 0.0


def _require_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "M3 scrapers require the `playwright` extra. "
            "Install with:  poetry install -E browser  (or  pip install playwright && playwright install chromium)"
        ) from exc
    from playwright.sync_api import sync_playwright

    return sync_playwright


def _throttle() -> None:
    """Honour the configured per-minute rate limit between page navigations."""
    global _LAST_NAVIGATION_TS
    settings = get_settings()
    rate = settings.rate_per_min
    if rate <= 0:
        return
    min_interval = 60.0 / rate
    elapsed = time.monotonic() - _LAST_NAVIGATION_TS
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _LAST_NAVIGATION_TS = time.monotonic()


@contextmanager
def browser_page(url: str, *, wait_ms: int = 1500) -> Iterator[Any]:
    """Open ``url`` in a headless Chromium page and yield the Playwright ``Page``.

    The browser is created lazily and reused across calls (singleton). The
    caller is responsible for calling ``page.close()`` — the context manager
    only tears down the browser when the process exits.
    """
    settings = get_settings()
    pw_factory = _require_playwright()
    _throttle()

    global _BROWSER_SINGLETON
    if _BROWSER_SINGLETON is None:
        pw = pw_factory().start()
        _BROWSER_SINGLETON = pw.chromium.launch(headless=True)
        log.info("osint.scraper.browser.launched")
    ctx = _BROWSER_SINGLETON.new_context(user_agent=settings.user_agent)
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(wait_ms)
        yield page
    finally:
        page.close()
        ctx.close()


def close_browser() -> None:
    """Tear down the singleton browser (call on process exit for cleanliness)."""
    global _BROWSER_SINGLETON
    if _BROWSER_SINGLETON is not None:
        try:
            _BROWSER_SINGLETON.close()
        except Exception:  # pragma: no cover
            pass
        _BROWSER_SINGLETON = None
