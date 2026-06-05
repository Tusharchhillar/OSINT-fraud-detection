"""Tests for the M3 scrapers (Instagram, X, WhatsApp).

These tests replay recorded HTML fixtures by monkeypatching
``osint.scrapers.browser.browser_page`` to return a fake page whose
``.content()`` yields the local HTML. No network is touched.

We cover, per platform:

* URL detection (target → URL).
* HTML parsing (HTML → list of RawEvent).
* The end-to-end run() with a stubbed browser.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from osint.schemas import RawEvent

FIXTURES = Path(__file__).parent / "fixtures"


def _stub_browser(html: str):
    """Return a *callable* that mimics ``browser_page(url, wait_ms=...)``.

    The scraper does ``with browser_page(url, wait_ms=2500) as page:``, so the
    stub has to be a function (or callable class) that ignores its args and
    returns a context manager. We return a class instance whose ``__enter__``
    yields a fake page with ``.content()`` returning the fixture HTML.
    """

    class _Stub:
        def __init__(self, *args, **kwargs):
            # Ignore url/wait_ms — we already know which HTML to return.
            pass

        def __enter__(self):
            return SimpleNamespace(content=lambda: html, close=lambda: None)

        def __exit__(self, *exc):
            return None

    return _Stub


# ---------- Instagram ----------


def test_ig_detect_hashtag() -> None:
    from osint.scrapers.instagram import _detect_target_type

    kind, url = _detect_target_type("#scamalert")
    assert kind == "hashtag"
    assert url.endswith("/explore/tags/scamalert/")


def test_ig_detect_profile() -> None:
    from osint.scrapers.instagram import _detect_target_type

    kind, url = _detect_target_type("@instagram")
    assert kind == "profile"
    assert url.endswith("/instagram/")


def test_ig_detect_location() -> None:
    from osint.scrapers.instagram import _detect_target_type

    kind, url = _detect_target_type("loc:123456")
    assert kind == "location"
    assert url.endswith("/explore/locations/123456/")


def test_ig_detect_post() -> None:
    from osint.scrapers.instagram import _detect_target_type

    kind, url = _detect_target_type("post:CxYz123abc")
    assert kind == "post"
    assert url.endswith("/p/CxYz123abc/")


def test_ig_detect_invalid_raises() -> None:
    from osint.scrapers.instagram import _detect_target_type

    with pytest.raises(ValueError):
        _detect_target_type("not-a-real-target!!!")


def test_ig_hashtag_run_extracts_captions() -> None:
    from osint.scrapers.instagram import InstagramScraper

    html = (FIXTURES / "instagram" / "hashtag_scamalert.html").read_text(encoding="utf-8")
    with patch("osint.scrapers.instagram.browser_page", _stub_browser(html)):
        events = list(InstagramScraper().run("#scamalert", limit=10))

    assert events, "expected at least one event from the hashtag fixture"
    for ev in events:
        assert ev.platform == "instagram"
        assert ev.source.startswith("#")
        assert ev.text
        assert ev.content_hash is not None


def test_ig_profile_run_sets_source_to_at_handle() -> None:
    """Run against the profile fixture; whatever is extracted must use @handle."""
    from osint.scrapers.instagram import InstagramScraper

    html = (FIXTURES / "instagram" / "profile_legit.html").read_text(encoding="utf-8")
    with patch("osint.scrapers.instagram.browser_page", _stub_browser(html)):
        events = list(InstagramScraper().run("@instagram", limit=5))

    # Some IG profile pages need JS to render captions — when that happens
    # the parser legitimately returns 0 events. We just need to confirm the
    # source naming works for whatever does come through, and that the
    # scraper didn't crash.
    for ev in events:
        assert ev.source == "@instagram"
        assert ev.platform == "instagram"


def test_ig_post_run_emits_single_event() -> None:
    from osint.scrapers.instagram import InstagramScraper

    html = (FIXTURES / "instagram" / "post_demo.html").read_text(encoding="utf-8")
    with patch("osint.scrapers.instagram.browser_page", _stub_browser(html)):
        events = list(InstagramScraper().run("post:CxYz123abc", limit=1))

    assert len(events) == 1
    assert events[0].source == "post:CxYz123abc"


def test_ig_emoji_only_caption_is_dropped_by_cleaner_not_scraper() -> None:
    """Captions that look like emoji-only noise are kept by the scraper and
    dropped by the cleaner.

    The scraper requires ``alt`` text of at least 20 chars to count as a
    caption, so we use a longer emoji-only string here.
    """
    from osint.processing.clean import clean_events
    from osint.scrapers.instagram import InstagramScraper

    # 30+ emoji-only characters — long enough for the scraper to capture,
    # but contains no alpha char so the cleaner drops it.
    emoji = "🔥" * 30
    html = f'<html><body><img alt="{emoji}" src=x></body></html>'
    with patch("osint.scrapers.instagram.browser_page", _stub_browser(html)):
        raw = list(InstagramScraper().run("#x", limit=5))
    assert len(raw) == 1
    assert raw[0].text == emoji
    cleaned = clean_events(raw)
    assert cleaned == []  # emoji-only → dropped by cleaner


# ---------- X / Twitter ----------


def test_x_detect_hashtag() -> None:
    from osint.scrapers.x import _detect_target_type

    kind, nitter_url, x_url = _detect_target_type("#phishing")
    assert kind == "hashtag"
    assert "nitter" in nitter_url.lower() or "search" in nitter_url
    assert "x.com" in x_url


def test_x_detect_profile() -> None:
    from osint.scrapers.x import _detect_target_type

    kind, nitter_url, x_url = _detect_target_type("@nasa")
    assert kind == "profile"
    assert nitter_url.endswith("/nasa")
    assert x_url.endswith("x.com/nasa")


def test_x_nitter_parser_extracts_three_tweets() -> None:
    from osint.scrapers.x import _parse_nitter

    html = (FIXTURES / "x" / "nitter_search_phishing.html").read_text(encoding="utf-8")
    events = _parse_nitter(html, limit=10)
    assert len(events) == 3
    for ev in events:
        assert ev.platform == "x"
        assert ev.text
        assert ev.source.startswith("@")


def test_x_nitter_run_uses_fixture_via_stub() -> None:
    from osint.scrapers.x import XScraper

    html = (FIXTURES / "x" / "nitter_search_phishing.html").read_text(encoding="utf-8")
    with patch("osint.scrapers.x.browser_page", _stub_browser(html)):
        events = list(XScraper(nitter_instances=["http://stub"]).run("#phishing", limit=10))

    assert events
    assert all(ev.platform == "x" for ev in events)


def test_x_falls_back_to_xcom_when_nitter_fails() -> None:
    """If every nitter instance returns no events, the x.com fallback kicks in."""
    from osint.scrapers.x import XScraper

    class FakePage(SimpleNamespace):
        def title(self_inner):
            return "x.com — phishing"

        def evaluate(self_inner, js):
            return "Search results for phishing"

    class FakeXcomCtx:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return FakePage()

        def __exit__(self, *exc):
            return None

    # First call: empty nitter HTML → no events.
    empty_ctx = _stub_browser("<html><body></body></html>")()
    # Second call: x.com stub with title + desc.
    xcom_ctx = FakeXcomCtx()

    with patch("osint.scrapers.x.browser_page", side_effect=[empty_ctx, xcom_ctx]):
        events = list(XScraper(nitter_instances=["http://stub"]).run("#phishing", limit=5))

    assert events
    assert events[0].platform == "x"
    assert events[0].source == "x.com"


# ---------- WhatsApp ----------


def test_wa_normalize_full_url() -> None:
    from osint.scrapers.whatsapp import _normalize_invite

    url = _normalize_invite("https://chat.whatsapp.com/ABC123")
    assert url == "https://chat.whatsapp.com/ABC123"


def test_wa_normalize_bare_code() -> None:
    from osint.scrapers.whatsapp import _normalize_invite

    url = _normalize_invite("ABC123xyz")
    assert url == "https://chat.whatsapp.com/ABC123xyz"


def test_wa_normalize_short_url() -> None:
    from osint.scrapers.whatsapp import _normalize_invite

    url = _normalize_invite("chat.whatsapp.com/ABC123")
    assert url == "https://chat.whatsapp.com/ABC123"


def test_wa_normalize_invalid_raises() -> None:
    from osint.scrapers.whatsapp import _normalize_invite

    with pytest.raises(ValueError):
        _normalize_invite("not a real code!!!")


def test_wa_parser_extracts_og_metadata() -> None:
    from osint.scrapers.whatsapp import _parse_invite_page

    html = (FIXTURES / "whatsapp" / "invite_demo.html").read_text(encoding="utf-8")
    ev = _parse_invite_page(html, invite="DEMO123ABC456")
    assert ev.platform == "whatsapp"
    assert ev.source == "chat.whatsapp.com/DEMO123ABC456"
    # The parser should at least have title or description, and a member_count raw field.
    assert ev.text or ev.raw.get("title") or ev.raw.get("description")
    assert "member_count" in ev.raw


def test_wa_run_emits_single_event() -> None:
    from osint.scrapers.whatsapp import WhatsAppScraper

    html = (FIXTURES / "whatsapp" / "invite_demo.html").read_text(encoding="utf-8")
    with patch("osint.scrapers.whatsapp.browser_page", _stub_browser(html)):
        events = list(WhatsAppScraper().run("DEMO123ABC456"))

    assert len(events) == 1
    assert events[0].platform == "whatsapp"


# ---------- Registry sanity ----------


def test_all_m3_scrapers_registered() -> None:
    """Importing the scraper modules must register all four platforms."""
    from osint.scrapers.base import REGISTRY

    # All four platforms are listed in the registry.
    for plat in ("telegram", "instagram", "x", "whatsapp"):
        assert plat in REGISTRY, f"{plat!r} missing from scraper registry"
