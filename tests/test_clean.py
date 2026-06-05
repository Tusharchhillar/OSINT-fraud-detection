"""Tests for the cleaning layer."""

from __future__ import annotations

from osint.processing.clean import clean_events
from osint.schemas import RawEvent


def test_dedupes_by_event_id() -> None:
    a = RawEvent.from_scraped(platform="x", source="@h", text="hello")
    b = RawEvent.from_scraped(platform="x", source="@h", text="hello")  # same id
    c = RawEvent.from_scraped(platform="x", source="@h", text="world")
    out = clean_events([a, b, c])
    assert len(out) == 2
    assert {e.text for e in out} == {"hello", "world"}


def test_drops_empty_rows() -> None:
    a = RawEvent.from_scraped(platform="x", source="@h", text="")
    b = RawEvent.from_scraped(platform="x", source="@h", text="   ")
    c = RawEvent.from_scraped(platform="x", source="@h", text="real content")
    out = clean_events([a, b, c])
    assert len(out) == 1
    assert out[0].text == "real content"


def test_drops_emoji_only_noise() -> None:
    a = RawEvent.from_scraped(platform="instagram", source="@p", text="🔥🔥🔥")
    b = RawEvent.from_scraped(platform="instagram", source="@p", text="🔥 promo 🔥")
    out = clean_events([a, b])
    assert len(out) == 1
    assert out[0].text == "🔥 promo 🔥"


def test_normalizes_url_trackers() -> None:
    ev = RawEvent.from_scraped(
        platform="telegram",
        source="@c",
        text="join https://Example.com/path?utm_source=tw&id=1",
    )
    out = clean_events([ev])
    assert len(out) == 1
    # Host lowercased, utm_source stripped, id kept.
    url = out[0].urls[0]
    assert url.startswith("https://example.com/path")
    assert "utm_source" not in url
    assert "id=1" in url


def test_drops_too_short_messages_without_payload() -> None:
    a = RawEvent.from_scraped(platform="x", source="@h", text="ok")
    b = RawEvent.from_scraped(platform="x", source="@h", text="real text here")
    out = clean_events([a, b])
    assert len(out) == 1
    assert out[0].text == "real text here"


def test_keeps_short_message_with_url() -> None:
    """A 2-char message is fine if it carries a URL."""
    ev = RawEvent.from_scraped(platform="telegram", source="@c", text="hi https://example.com")
    out = clean_events([ev])
    assert len(out) == 1
    assert "example.com" in out[0].urls[0]


def test_flags_known_shortener_hosts() -> None:
    ev = RawEvent.from_scraped(
        platform="telegram",
        source="@c",
        text="click https://bit.ly/abc and https://t.co/xyz",
    )
    out = clean_events([ev])
    assert len(out) == 1
    # Real URLs preserved.
    real = [u for u in out[0].urls if not u.startswith("*.")]
    flagged = [u for u in out[0].urls if u.startswith("*.")]
    assert "https://bit.ly/abc" in real
    assert "https://t.co/xyz" in real
    assert "*.bit.ly" in flagged
    assert "*.t.co" in flagged


def test_does_not_flag_non_shortener_hosts() -> None:
    ev = RawEvent.from_scraped(platform="telegram", source="@c", text="see https://example.com/x")
    out = clean_events([ev])
    assert len(out) == 1
    assert not any(u.startswith("*.") for u in out[0].urls)
