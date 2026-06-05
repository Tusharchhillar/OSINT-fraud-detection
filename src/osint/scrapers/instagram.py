"""Instagram scraper (Playwright-based, public-only).

Four target types are supported; the dispatcher picks one based on the URL shape:

* ``--channel "#hashtag"``        → ``https://www.instagram.com/explore/tags/<hashtag>/``
* ``--channel "@username"``       → ``https://www.instagram.com/<username>/``
* ``--channel "loc:<id>"``        → ``https://www.instagram.com/explore/locations/<id>/``
* ``--channel "post:<shortcode>"`` → ``https://www.instagram.com/p/<shortcode>/``

In all cases we only read **public** pages. No login, no cookies, no
session reuse beyond what Playwright does by default. Rate-limited to
``Settings.rate_per_min`` (default 20/min).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from osint.logging_setup import get_logger
from osint.schemas import RawEvent
from osint.scrapers.base import BaseScraper, register
from osint.scrapers.browser import browser_page

log = get_logger(__name__)


# ---------- URL detection ----------


_HASHTAG_RE = re.compile(r"^#?([A-Za-z0-9_]{1,100})$")
_PROFILE_RE = re.compile(r"^@?([A-Za-z0-9_.]{1,30})$")
_LOCATION_RE = re.compile(r"^(?:loc:)?(\d{1,15})$")
_POST_RE = re.compile(r"^(?:post:)?([A-Za-z0-9_-]{8,15})$")


def _detect_target_type(target: str) -> tuple[str, str]:
    """Return ``(kind, url)`` for a free-form ``--channel`` argument.

    ``kind`` is one of ``hashtag`` / ``profile`` / ``location`` / ``post``.
    Raises ``ValueError`` if the target matches none of the supported shapes.
    """
    target = target.strip()
    # Allow callers to pass a full URL.
    if target.startswith("http://") or target.startswith("https://"):
        if "/explore/tags/" in target:
            return "hashtag", target
        if "/explore/locations/" in target:
            return "location", target
        if "/p/" in target:
            return "post", target
        if "instagram.com/" in target:
            return "profile", target
    m = _LOCATION_RE.match(target)
    if m and not _PROFILE_RE.match(target):
        return "location", f"https://www.instagram.com/explore/locations/{m.group(1)}/"
    m = _POST_RE.match(target)
    if m and not _PROFILE_RE.match(target):
        return "post", f"https://www.instagram.com/p/{m.group(1)}/"
    m = _HASHTAG_RE.match(target)
    if m and target.startswith("#"):
        return "hashtag", f"https://www.instagram.com/explore/tags/{m.group(1)}/"
    m = _PROFILE_RE.match(target)
    if m and (target.startswith("@") or "." in target or "_" in target):
        return "profile", f"https://www.instagram.com/{m.group(1)}/"
    raise ValueError(
        f"Could not interpret {target!r} as a hashtag, profile, location, or post. "
        f"Try '#hashtag', '@username', 'loc:<id>', or 'post:<shortcode>'."
    )


# ---------- HTML → RawEvent ----------


def _caption_from_alt(html: str, limit: int = 10) -> list[str]:
    """Extract post captions from ``alt=`` attributes on post images.

    IG uses the caption as the ``alt`` text of the post thumbnail — a
    surprisingly stable hook even after class names change.
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'alt="([^"]{20,500})"', html):
        text = m.group(1).strip()
        if text in seen or text.endswith("'s profile picture"):
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _usernames_from_html(html: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'href="/([A-Za-z0-9_.]{3,30})/"', html):
        u = m.group(1)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def _parse_hashtag(html: str, *, limit: int) -> list[RawEvent]:
    """Extract post captions from a hashtag page.

    Note: the ``source`` field is set to a placeholder here and overwritten
    with the real hashtag in :meth:`InstagramScraper.run` once the URL is
    known. This function only knows the captions and authors.
    """
    captions = _caption_from_alt(html, limit=limit)
    users = _usernames_from_html(html, limit=limit)
    out: list[RawEvent] = []
    for i, caption in enumerate(captions):
        author = users[i] if i < len(users) else None
        out.append(
            RawEvent.from_scraped(
                platform="instagram",
                source="hashtag:pending",  # overwritten by run() with "#<tag>"
                text=caption,
                author=author,
                raw={"hashtag_index": i, "caption": caption},
            )
        )
    return out


def _parse_profile(html: str, username: str, *, limit: int) -> list[RawEvent]:
    captions = _caption_from_alt(html, limit=limit)
    out: list[RawEvent] = []
    for i, caption in enumerate(captions):
        out.append(
            RawEvent.from_scraped(
                platform="instagram",
                source=f"@{username}",
                text=caption,
                author=username,
                raw={"post_index": i, "caption": caption},
            )
        )
    return out


def _parse_post(html: str, shortcode: str) -> list[RawEvent]:
    captions = _caption_from_alt(html, limit=1)
    text = captions[0] if captions else ""
    # First username in the page is the author.
    users = _usernames_from_html(html, limit=1)
    return [
        RawEvent.from_scraped(
            platform="instagram",
            source=f"post:{shortcode}",
            text=text,
            author=users[0] if users else None,
            raw={"shortcode": shortcode, "caption": text},
        )
    ]


def _parse_location(html: str, location_id: str, *, limit: int) -> list[RawEvent]:
    captions = _caption_from_alt(html, limit=limit)
    users = _usernames_from_html(html, limit=limit)
    out: list[RawEvent] = []
    for i, caption in enumerate(captions):
        out.append(
            RawEvent.from_scraped(
                platform="instagram",
                source=f"loc:{location_id}",
                text=caption,
                author=users[i] if i < len(users) else None,
                raw={"location_id": location_id, "post_index": i, "caption": caption},
            )
        )
    return out


# ---------- scraper class ----------


@register
class InstagramScraper(BaseScraper):
    platform = "instagram"

    def __init__(self) -> None:
        # No network setup needed — Playwright launches lazily on first .run().
        pass

    def run(self, target: str, *, limit: int = 100) -> Iterator[RawEvent]:
        kind, url = _detect_target_type(target)
        log.info("osint.scraper.instagram.fetch", kind=kind, url=url, limit=limit)
        with browser_page(url, wait_ms=2500) as page:
            html = page.content()
        if kind == "hashtag":
            tag = url.rstrip("/").split("/")[-1]
            events = _parse_hashtag(html, limit=limit)
            for ev in events:
                ev.source = f"#{tag}"
                # re-hash so the content_hash is consistent across re-runs
                ev.content_hash = None
            events = _rehash(events)
            yield from events
        elif kind == "profile":
            username = url.rstrip("/").split("/")[-1]
            yield from _parse_profile(html, username=username, limit=limit)
        elif kind == "post":
            shortcode = url.rstrip("/").split("/")[-1]
            yield from _parse_post(html, shortcode=shortcode)
        elif kind == "location":
            loc_id = url.rstrip("/").split("/")[-1]
            yield from _parse_location(html, location_id=loc_id, limit=limit)
        else:  # pragma: no cover
            raise ValueError(f"Unknown target kind: {kind!r}")


def _rehash(events: list[RawEvent]) -> list[RawEvent]:
    """Re-populate ``content_hash`` for a list of events."""
    from osint.schemas import make_content_hash

    for ev in events:
        ev.content_hash = make_content_hash(ev.text, ev.urls)
    return events
