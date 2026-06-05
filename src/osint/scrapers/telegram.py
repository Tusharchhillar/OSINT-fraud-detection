"""Telethon-based Telegram scraper.

Three run modes, all yielding :class:`~osint.schemas.RawEvent` records:

1. **Single channel**: ``TelegramScraper.run("@channel", limit=50)``
2. **Batch from file**: see :func:`run_from_file`
3. **Discovery by keyword**: ``TelegramScraper.discover("crypto giveaway", limit=5)``

Telegram credentials come from :class:`~osint.config.Settings`. If
``TELEGRAM_API_ID`` / ``TELEGRAM_API_HASH`` are not set, the scraper raises a
clear error on first use (and the live integration test in ``tests/test_telegram.py``
is skipped automatically).

The scraper is intentionally conservative: it only reads **public** content and
honors Telethon's flood-wait guidance. Rate-limiting between batch fetches is
controlled by ``Settings.rate_per_min`` (default: 20/min → ~3s between batches).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from osint.config import get_settings
from osint.logging_setup import get_logger
from osint.schemas import RawEvent
from osint.scrapers.base import BaseScraper, register

log = get_logger(__name__)

# Telethon's "Message" class is imported lazily inside methods so that
# `import osint.scrapers.telegram` doesn't fail when telethon isn't installed
# (it's an optional extra).


def _require_telethon() -> Any:
    """Import telethon lazily, with a friendly error if it's not installed."""
    try:
        from telethon import TelegramClient  # noqa: F401  (used by callers)
        from telethon.errors import FloodWaitError
        from telethon.tl.types import (  # noqa: F401
            Channel,
            Chat,
            Message,
            User,
        )

        return {
            "TelegramClient": TelegramClient,
            "Channel": Channel,
            "Chat": Chat,
            "Message": Message,
            "User": User,
            "FloodWaitError": FloodWaitError,
        }
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Telegram scraping requires the `telethon` extra. "
            "Install with:  poetry install -E telegram"
        ) from exc


def _author_name(sender: Any) -> str | None:
    """Best-effort display name for a message sender.

    Priority: real human name (first+last) > channel/group title > username >
    numeric id. A username alone is a weaker signal than a name, so we keep it
    as a fallback.
    """
    if sender is None:
        return None
    full_name = " ".join(
        part
        for part in (getattr(sender, "first_name", None), getattr(sender, "last_name", None))
        if part
    ).strip()
    name = (
        full_name
        or getattr(sender, "title", None)
        or getattr(sender, "username", None)
        or None
    )
    if name:
        return str(name)
    if getattr(sender, "id", None) is not None:
        return f"id:{sender.id}"
    return None


def _channel_source(entity: Any) -> str:
    """Stable source identifier for a channel/chat: ``@username`` or ``id:<n>``."""
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    return f"id:{getattr(entity, 'id', '?')}"


def _message_to_event(message: Any, entity: Any) -> RawEvent:
    """Convert a Telethon ``Message`` (already fetched) into a ``RawEvent``."""
    text = message.message or ""
    media_urls: list[str] = []
    media = getattr(message, "media", None)
    if media is not None:
        # Telethon objects expose the concrete type name on the `._` discriminator
        # (e.g. `MessageMediaPhoto`). The `type(...).__name__` fallback handles
        # duck-typed objects used in tests/fixtures.
        media_type = getattr(media, "_", None) or type(media).__name__
        media_urls.append(f"media:{media_type}")

    raw: dict[str, Any] = {
        "message_id": getattr(message, "id", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "reply_to_msg_id": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
        "post_author": getattr(message, "post_author", None),
    }
    return RawEvent.from_scraped(
        platform="telegram",
        source=_channel_source(entity),
        text=text,
        author=_author_name(getattr(message, "sender", None)),
        raw_id=str(getattr(message, "id", "")),
        media=media_urls or None,
        timestamp=getattr(message, "date", None),
        raw=raw,
    )


@register
class TelegramScraper(BaseScraper):
    """Scrape public Telegram channels/chats using the Telethon client.

    Parameters
    ----------
    session_name:
        Name of the on-disk Telethon session. Defaults to
        ``Settings.telegram_session``.
    rate_per_min:
        Maximum number of message-fetch RPCs per minute. The scraper sleeps
        between fetches to honor this. Use 0 to disable.
    """

    platform = "telegram"

    def __init__(
        self,
        session_name: str | None = None,
        rate_per_min: int | None = None,
    ) -> None:
        self._settings = get_settings()
        if not self._settings.telegram_api_id or not self._settings.telegram_api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env. "
                "Get them at https://my.telegram.org → API development tools."
            )
        self._session_name = session_name or self._settings.telegram_session
        self._rate_per_min = (
            rate_per_min if rate_per_min is not None else self._settings.rate_per_min
        )
        self._min_interval = (60.0 / self._rate_per_min) if self._rate_per_min > 0 else 0.0
        self._client: Any = None
        self._last_fetch_ts: float = 0.0

    # ---------- lifecycle ----------

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        telethon = _require_telethon()
        self._client = telethon["TelegramClient"](
            self._session_name,
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash,
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            # On first run, the user is prompted for phone + code here.
            await self._client.start()
        log.info("osint.scraper.telegram.connected", session=self._session_name)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    def close(self) -> None:
        if self._client is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():  # pragma: no cover
                    loop.create_task(self.aclose())
                else:
                    loop.run_until_complete(self.aclose())
            except RuntimeError:
                asyncio.run(self.aclose())

    # ---------- helpers ----------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_fetch_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_fetch_ts = time.monotonic()

    # ---------- public run methods ----------

    async def _arun_channel(self, target: str, *, limit: int) -> list[RawEvent]:
        client = await self._ensure_client()
        telethon = _require_telethon()
        # Accept "@handle", "handle", "t.me/handle", or numeric id.
        cleaned = target.lstrip("@").strip()
        if cleaned.startswith("https://t.me/"):
            cleaned = cleaned.removeprefix("https://t.me/").rstrip("/")
        try:
            entity = await client.get_entity(cleaned)
        except telethon["FloodWaitError"]:
            # Rate-limit is an operational signal — let the caller decide
            # whether to back off, skip, or fail. Swallowing it would leave
            # callers (and the live integration test) silently seeing `[]`.
            raise
        except Exception as exc:  # Telethon raises various types
            log.warning("osint.scraper.telegram.entity_not_found", target=target, error=str(exc))
            return []

        if not isinstance(entity, (telethon["Channel"], telethon["Chat"])):
            log.warning(
                "osint.scraper.telegram.not_a_channel",
                target=target,
                entity_type=type(entity).__name__,
            )
            return []

        out: list[RawEvent] = []
        async for message in client.iter_messages(entity, limit=limit):
            self._throttle()
            if message is None or getattr(message, "empty", False):
                continue
            out.append(_message_to_event(message, entity))
        log.info("osint.scraper.telegram.channel_done", target=target, count=len(out))
        return out

    async def _adiscover(self, keyword: str, *, discover_limit: int) -> list[str]:
        """Resolve a search keyword to a list of public channel usernames.

        Uses Telegram's ``SearchGlobalRequest`` to find public channels whose
        title or username matches ``keyword``. Only public channels are
        returned — no private content is touched.
        """
        client = await self._ensure_client()
        telethon = _require_telethon()
        from telethon.tl.functions.contacts import SearchRequest  # type: ignore

        result = await client(SearchRequest(q=keyword, limit=max(discover_limit * 5, 20)))
        usernames: list[str] = []
        for chat in getattr(result, "chats", []):
            if not isinstance(chat, telethon["Channel"]):
                continue
            if not getattr(chat, "username", None):
                continue
            # ``broadcast=True`` ⇒ channel (not group). ``megagroup`` is allowed too.
            usernames.append(f"@{chat.username}")
            if len(usernames) >= discover_limit:
                break
        log.info("osint.scraper.telegram.discover_done", keyword=keyword, found=len(usernames))
        return usernames

    def run(self, target: str, *, limit: int = 100) -> Iterator[RawEvent]:
        """Synchronous entry point used by the CLI. Delegates to the async path."""
        return asyncio.run(self._arun_channel(target, limit=limit))

    # ---------- high-level helpers ----------

    async def arun(self, target: str, *, limit: int = 100) -> list[RawEvent]:
        return await self._arun_channel(target, limit=limit)

    async def arun_many(self, targets: list[str], *, limit: int = 100) -> list[RawEvent]:
        out: list[RawEvent] = []
        for t in targets:
            out.extend(await self._arun_channel(t, limit=limit))
        return out

    async def adiscover_and_run(
        self, keyword: str, *, discover_limit: int = 5, per_channel_limit: int = 20
    ) -> list[RawEvent]:
        usernames = await self._adiscover(keyword, discover_limit=discover_limit)
        return await self.arun_many(usernames, limit=per_channel_limit)


# ---------- module-level helpers (used by the CLI) ----------


def run_from_file(
    path: str | Path, *, limit: int = 100, session_name: str | None = None
) -> Iterator[RawEvent]:
    """Read a text file with one channel per line, scrape each, yield events."""
    p = Path(path)
    targets = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    log.info("osint.scraper.telegram.batch_start", file=str(p), count=len(targets), limit=limit)
    scraper = TelegramScraper(session_name=session_name)
    try:
        events = asyncio.run(scraper.arun_many(targets, limit=limit))
    finally:
        scraper.close()
    yield from events


def discover_and_run(
    keyword: str, *, discover_limit: int = 5, per_channel_limit: int = 20
) -> Iterator[RawEvent]:
    """Search Telegram for ``keyword``, then scrape the top discovered channels."""
    scraper = TelegramScraper()
    try:
        events = asyncio.run(
            scraper.adiscover_and_run(
                keyword, discover_limit=discover_limit, per_channel_limit=per_channel_limit
            )
        )
    finally:
        scraper.close()
    yield from events
