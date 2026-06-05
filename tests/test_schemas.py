"""Tests for the event schemas."""

from __future__ import annotations

from datetime import datetime, timezone

from osint.schemas import EnrichedEvent, RawEvent, make_content_hash, make_event_id


def test_event_id_is_stable() -> None:
    a = make_event_id("telegram", "@chan", "42", "hello world")
    b = make_event_id("telegram", "@chan", "42", "hello world")
    assert a == b
    assert a.startswith("telegram-")


def test_event_id_differs_on_text() -> None:
    a = make_event_id("telegram", "@chan", "42", "hello")
    b = make_event_id("telegram", "@chan", "42", "HELLO")
    assert a != b


def test_from_scraped_extracts_urls() -> None:
    ev = RawEvent.from_scraped(
        platform="instagram",
        source="@promo",
        text="Check https://example.com/a and http://bit.ly/x",
    )
    assert ev.urls == ["https://example.com/a", "http://bit.ly/x"]
    assert ev.platform == "instagram"
    assert ev.timestamp.tzinfo is not None


def test_ndjson_roundtrip() -> None:
    ev = RawEvent.from_scraped(platform="x", source="@h", text="hi", author="alice")
    line = ev.to_ndjson()
    again = RawEvent.from_ndjson(line)
    assert again.event_id == ev.event_id
    assert again.platform == "x"
    assert again.text == "hi"


def test_enriched_event_extends_raw() -> None:
    base = RawEvent.from_scraped(platform="telegram", source="@c", text="x")
    enriched = EnrichedEvent(
        **base.model_dump(),
        intent="scam",
        risk_score=87.5,
        category="crypto-pump",
        indicators=["promises high returns", "external invite link"],
        reasoning="Classic pig-butchering template.",
    )
    assert enriched.risk_score == 87.5
    assert enriched.intent == "scam"
    assert enriched.event_id == base.event_id


def test_enriched_event_score_clamped() -> None:
    base = RawEvent.from_scraped(platform="x", source="@h", text="x")
    try:
        EnrichedEvent(**base.model_dump(), risk_score=150.0)  # type: ignore[arg-type]
    except Exception:
        return
    raise AssertionError("expected validation error for risk_score > 100")


def test_content_hash_is_stable_across_trackers() -> None:
    """Two messages that differ only by utm_* should share a content_hash."""
    a = make_content_hash("Join us", ["https://example.com/x?utm_source=tw"])
    b = make_content_hash("Join us", ["https://example.com/x"])
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_content_hash_differs_on_text() -> None:
    """Distinct messages must produce distinct hashes."""
    a = make_content_hash("hello", ["https://example.com/x"])
    b = make_content_hash("world", ["https://example.com/x"])
    assert a != b


def test_content_hash_is_case_insensitive() -> None:
    """Paraphrase-tolerance: 'hello' and 'HELLO' share a content_hash."""
    a = make_content_hash("hello", ["https://example.com/x"])
    b = make_content_hash("HELLO", ["https://example.com/x"])
    assert a == b


def test_from_scraped_populates_content_hash() -> None:
    ev = RawEvent.from_scraped(platform="x", source="@h", text="hello world")
    assert ev.content_hash is not None
    assert len(ev.content_hash) == 64


def test_from_scraped_accepts_language() -> None:
    ev = RawEvent.from_scraped(platform="x", source="@h", text="hola", language="es")
    assert ev.language == "es"
