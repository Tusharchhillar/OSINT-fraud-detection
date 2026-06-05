"""X / Twitter scraper (public-only, nitter-first with x.com fallback).

Strategy:

1. **Try nitter instances first.** Nitter is an anonymous, no-login proxy
   for public X content. We cycle through a configurable list of
   instances; the first one that responds wins. Set via
   ``OSINT_NITTER_INSTANCES`` (comma-separated) in ``.env`` or the
   ``nitter_instances`` constructor arg.

2. **Fall back to x.com public search** if all nitter instances fail.
   Heavier fingerprinting, may rate-limit, but more reliable long-term.

3. **Never log in.** Public content only.

Target shapes:

* ``--channel "@handle"``    → profile timeline
* ``--channel "#keyword"``   → keyword search
* ``--channel "https://x.com/..."`` → raw URL pass-through
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

from osint.config import get_settings
from osint.logging_setup import get_logger
from osint.schemas import RawEvent
from osint.scrapers.base import BaseScraper, register
from osint.scrapers.browser import browser_page

log = get_logger(__name__)

DEFAULT_NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]


def _nitter_instances() -> list[str]:
    raw = os.getenv("OSINT_NITTER_INSTANCES", "")
    if raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    return list(DEFAULT_NITTER_INSTANCES)


# ---------- URL building ----------


_HASHTAG_RE = re.compile(r"^#?(\w{1,80})$")
_PROFILE_RE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")


def _detect_target_type(target: str) -> tuple[str, str, str]:
    """Return ``(kind, nitter_url, x_url)``.

    ``kind`` ∈ {hashtag, profile, raw}.
    """
    target = target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        return "raw", target, target
    m = _HASHTAG_RE.match(target)
    if m and target.startswith("#"):
        tag = m.group(1)
        return (
            "hashtag",
            f"/search?q=%23{tag}",
            f"https://x.com/search?q=%23{tag}&src=typed_query&f=live",
        )
    m = _PROFILE_RE.match(target)
    if m and (target.startswith("@") or "_" in target):
        handle = m.group(1)
        return (
            "profile",
            f"/{handle}",
            f"https://x.com/{handle}",
        )
    # Bare keyword: treat as a hashtag-style search.
    keyword = target.lstrip("#")
    return (
        "hashtag",
        f"/search?q={keyword}",
        f"https://x.com/search?q={keyword}&src=typed_query&f=live",
    )


# ---------- HTML → RawEvent ----------


_NITTER_TWEET_RE = re.compile(
    r'<div class="timeline-item[^"]*">(.*?)<span class="tweet-date',
    re.DOTALL,
)
_NITTER_TEXT_RE = re.compile(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
_NITTER_AUTHOR_RE = re.compile(r'<a class="fullname[^"]*"[^>]*title="([^"]+)"', re.DOTALL)
_NITTER_HANDLE_RE = re.compile(r'<a class="username[^"]*"[^>]*>@?([A-Za-z0-9_]+)</a>', re.DOTALL)
_NITTER_DATE_RE = re.compile(r'<span class="tweet-date[^"]*"><a[^>]+title="([^"]+)"', re.DOTALL)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_nitter(html: str, *, limit: int) -> list[RawEvent]:
    """Best-effort parser for the nitter HTML structure.

    Nitter's DOM is small and stable (no JavaScript required). If nitter's
    markup ever changes, this parser returns an empty list rather than
    raising — the x.com fallback will pick up the slack.
    """
    events: list[RawEvent] = []
    for chunk_match in _NITTER_TWEET_RE.finditer(html):
        chunk = chunk_match.group(0)
        text_m = _NITTER_TEXT_RE.search(chunk)
        text = _strip_html(text_m.group(1)) if text_m else ""
        if not text:
            continue
        author_m = _NITTER_AUTHOR_RE.search(chunk)
        handle_m = _NITTER_HANDLE_RE.search(chunk)
        date_m = _NITTER_DATE_RE.search(chunk)
        author = author_m.group(1) if author_m else None
        handle = handle_m.group(1) if handle_m else None
        source = f"@{handle}" if handle else "x:unknown"
        events.append(
            RawEvent.from_scraped(
                platform="x",
                source=source,
                text=text,
                author=author or handle,
                raw={"tweet_date": date_m.group(1) if date_m else None},
            )
        )
        if len(events) >= limit:
            break
    return events


# ---------- scraper class ----------


@register
class XScraper(BaseScraper):
    platform = "x"

    def __init__(self, nitter_instances: list[str] | None = None) -> None:
        self._instances = nitter_instances or _nitter_instances()

    def _try_nitter(self, path: str, *, limit: int) -> list[RawEvent]:
        for inst in self._instances:
            url = inst.rstrip("/") + path
            log.info("osint.scraper.x.try_nitter", instance=inst, path=path)
            try:
                with browser_page(url, wait_ms=1500) as page:
                    html = page.content()
                events = _parse_nitter(html, limit=limit)
                if events:
                    log.info("osint.scraper.x.nitter_ok", instance=inst, count=len(events))
                    return events
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "osint.scraper.x.nitter_failed", instance=inst, error=str(exc)
                )
                continue
        return []

    def _try_xcom(self, url: str, *, limit: int) -> list[RawEvent]:
        log.info("osint.scraper.x.fallback_xcom", url=url)
        try:
            with browser_page(url, wait_ms=2500) as page:
                # x.com is JS-heavy. We can't easily parse tweets from the
                # raw HTML anymore (Twitter moved to a SPA in 2023). The
                # best we can do without an API is record the page title
                # and any visible <meta> description. Analysts can layer
                # in a paid API client later.
                title = page.title()
                desc = page.evaluate(
                    "() => { const m = document.querySelector('meta[name=\"description\"]'); return m ? m.content : ''; }"
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("osint.scraper.x.xcom_failed", url=url, error=str(exc))
            return []
        if not (title or desc):
            return []
        return [
            RawEvent.from_scraped(
                platform="x",
                source="x.com",
                text=f"{title} — {desc}".strip(" —"),
                raw={"url": url, "title": title, "description": desc},
            )
        ]

    def run(self, target: str, *, limit: int = 100) -> Iterator[RawEvent]:
        kind, nitter_path, x_url = _detect_target_type(target)
        events = self._try_nitter(nitter_path, limit=limit)
        if not events:
            events = self._try_xcom(x_url, limit=limit)
        log.info("osint.scraper.x.done", target=target, count=len(events))
        yield from events
