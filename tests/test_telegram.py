"""Tests for the Telegram scraper.

Two test layers:

* **Fixture replay** (always runs): reads recorded message dicts from
  ``tests/fixtures/telegram/messages.json`` and exercises the
  ``_message_to_event`` converter. No network, no Telethon install required.

* **Live integration test** (auto-skipped if Telegram creds are unset): signs into
  Telegram via Telethon, scrapes a few public messages from ``@telegram``, and
  asserts the resulting ``RawEvent`` shape. To enable, set in ``.env``:

      TELEGRAM_API_ID=...
      TELEGRAM_API_HASH=...
      TELEGRAM_SESSION=osint_test_session
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from osint.config import get_settings
from osint.schemas import RawEvent
from osint.scrapers.telegram import _message_to_event

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "telegram" / "messages.json"


def _to_ns(obj):
    """Recursively turn a dict into a SimpleNamespace tree.

    Lets the test pass plain JSON to the same code that expects Telethon's
    attribute-style objects.
    """
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(v) for v in obj]
    return obj


def _load_fixture_messages():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [_to_ns(m) for m in raw]


# ---------- fixture-replay tests (no network, always run) ----------


def test_message_to_event_extracts_url_and_source() -> None:
    [msg] = _load_fixture_messages()[:1]
    entity = msg.entity
    ev = _message_to_event(msg, entity)
    assert isinstance(ev, RawEvent)
    assert ev.platform == "telegram"
    assert ev.source == "@scam_promos"
    assert ev.author == "Promo Bot"
    assert ev.text.startswith("Join our VIP channel")
    assert "https://t.me/joinchat/abc123" in ev.urls
    assert ev.timestamp.tzinfo is not None
    assert ev.content_hash is not None


def test_message_to_event_records_media_marker() -> None:
    [msg] = _load_fixture_messages()[1:2]
    ev = _message_to_event(msg, msg.entity)
    assert ev.media == ["media:MessageMediaPhoto"]


def test_message_to_event_handles_null_sender() -> None:
    [msg] = _load_fixture_messages()[2:3]  # the emoji-only line, sender=null
    ev = _message_to_event(msg, msg.entity)
    assert ev.author is None
    # The emoji-only line is preserved at the scraper level; the cleaner drops it later.
    assert ev.text == "🔥🔥🔥"


def test_message_to_event_keeps_reply_to_metadata() -> None:
    [msg] = _load_fixture_messages()[3:4]
    ev = _message_to_event(msg, msg.entity)
    assert ev.raw.get("reply_to_msg_id") == 1001
    assert ev.raw.get("views") == 2500


def test_entity_without_username_falls_back_to_id() -> None:
    msg = _load_fixture_messages()[0]
    msg.entity.username = None
    ev = _message_to_event(msg, msg.entity)
    assert ev.source.startswith("id:")
    assert ev.source == f"id:{msg.entity.id}"


def test_flood_wait_propagates_from_get_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A FloodWaitError from get_entity must propagate, not be swallowed.

    The live integration test's skip-on-flood logic depends on this — if
    the scraper silently returns [] on a flood-wait, the test asserts on
    the empty list and fails instead of skipping. We verify the re-raise
    by injecting a fake client whose get_entity raises a stand-in
    FloodWaitError, and by patching _require_telethon so the scraper
    matches the stand-in class.
    """
    from osint.scrapers import telegram as tg_mod
    from osint.scrapers.telegram import TelegramScraper

    class _FakeFloodWaitError(Exception):
        pass

    class _FakeClient:
        async def get_entity(self, _target: str) -> None:
            raise _FakeFloodWaitError("A wait of 209 seconds is required")

    scraper = TelegramScraper.__new__(TelegramScraper)
    scraper._client = _FakeClient()

    monkeypatch.setattr(
        tg_mod,
        "_require_telethon",
        lambda: {
            "FloodWaitError": _FakeFloodWaitError,
            "Channel": (),
            "Chat": (),
        },
    )

    with pytest.raises(_FakeFloodWaitError, match="wait of 209 seconds"):
        asyncio.run(scraper._arun_channel("telegram", limit=3))


# ---------- live integration test (gated by env) ----------


def _telegram_creds_present() -> bool:
    s = get_settings()
    return bool(s.telegram_api_id and s.telegram_api_hash)


@pytest.mark.skipif(
    not _telegram_creds_present(),
    reason="TELEGRAM_API_ID / TELEGRAM_API_HASH not set; live integration test skipped",
)
def test_live_scrape_public_channel() -> None:
    """Scrape a few messages from @telegram and confirm the event shape.

    This is a real network call. It is auto-skipped unless Telegram creds are
    in the environment. If Telegram returns a FloodWaitError (rate-limit), the
    test is skipped rather than failed — the test isn't about hitting the API
    hard, it's about confirming the round-trip works.
    """
    from osint.scrapers.telegram import TelegramScraper

    scraper = TelegramScraper(session_name="osint_test_session")
    try:
        try:
            events = asyncio.run(scraper.arun("telegram", limit=3))
        except Exception as exc:
            msg = str(exc).lower()
            if "flood" in msg or "wait of" in msg or "seconds is required" in msg:
                pytest.skip(f"Telegram rate-limited the live test: {exc}")
            raise
    finally:
        scraper.close()

    assert events, "expected at least one message from @telegram"
    for ev in events:
        assert ev.platform == "telegram"
        assert ev.source  # non-empty
        assert ev.text or ev.media  # payload-bearing
        assert ev.event_id.startswith("telegram-")
