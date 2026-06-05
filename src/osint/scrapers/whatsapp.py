"""WhatsApp invite-link scraper (public-only, metadata only).

The only thing you can read from WhatsApp without a session is the public
preview metadata for a ``chat.whatsapp.com/<invite>`` link. This scraper
extracts:

* Group name (``og:title``)
* Group description (``og:description``)
* Approximate member count (parsed from the description)
* Preview image URL (``og:image``)

No message content. No member list. The single emitted event per invite link
encodes the metadata as the event's text and raw fields.

Target shapes:

* ``--channel "https://chat.whatsapp.com/ABC123xyz"``  → full URL
* ``--channel "ABC123xyz"``                            → bare invite code
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from osint.logging_setup import get_logger
from osint.schemas import RawEvent
from osint.scrapers.base import BaseScraper, register
from osint.scrapers.browser import browser_page

log = get_logger(__name__)

_INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_MEMBER_COUNT_RE = re.compile(r"(\d[\d,]*)", re.IGNORECASE)


def _normalize_invite(target: str) -> str:
    """Return ``https://chat.whatsapp.com/<code>`` for any reasonable input."""
    target = target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        return target
    if target.startswith("chat.whatsapp.com/"):
        return f"https://{target}"
    if _INVITE_RE.match(target):
        return f"https://chat.whatsapp.com/{target}"
    raise ValueError(
        f"Could not interpret {target!r} as a WhatsApp invite code or URL."
    )


def _parse_og(html: str) -> dict[str, str]:
    """Extract OpenGraph meta tags. Returns empty dict for missing fields."""
    out: dict[str, str] = {}
    for m in re.finditer(
        r'<meta\s+(?:property|name)="og:(\w+)"\s+content="([^"]+)"', html
    ):
        out[m.group(1)] = m.group(2)
    # Some pages use the reverse attribute order; handle that too.
    for m in re.finditer(
        r'<meta\s+content="([^"]+)"\s+(?:property|name)="og:(\w+)"', html
    ):
        out.setdefault(m.group(2), m.group(1))
    return out


def _parse_invite_page(html: str, invite: str) -> RawEvent:
    og = _parse_og(html)
    title = og.get("title", "").strip()
    description = og.get("description", "").strip()
    image = og.get("image", "").strip()

    # WhatsApp's description typically ends with "X members". Try to extract.
    member_count: int | None = None
    if description:
        nums = _MEMBER_COUNT_RE.findall(description)
        if nums:
            try:
                member_count = int(nums[-1].replace(",", ""))
            except ValueError:
                member_count = None

    text = "\n".join(filter(None, [title, description]))
    if not text:
        text = f"WhatsApp invite {invite}"

    return RawEvent.from_scraped(
        platform="whatsapp",
        source=f"chat.whatsapp.com/{invite}",
        text=text,
        media=[image] if image else None,
        raw={
            "invite": invite,
            "title": title,
            "description": description,
            "image": image,
            "member_count": member_count,
        },
    )


@register
class WhatsAppScraper(BaseScraper):
    platform = "whatsapp"

    def __init__(self) -> None:
        pass

    def run(self, target: str, *, limit: int = 100) -> Iterator[RawEvent]:
        url = _normalize_invite(target)
        invite = url.rstrip("/").split("/")[-1]
        log.info("osint.scraper.whatsapp.fetch", url=url, limit=limit)
        with browser_page(url, wait_ms=1500) as page:
            html = page.content()
        ev = _parse_invite_page(html, invite=invite)
        log.info("osint.scraper.whatsapp.done", invite=invite, member_count=ev.raw.get("member_count"))
        yield ev
