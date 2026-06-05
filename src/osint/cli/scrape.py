"""``osint-scrape`` — dispatch to a platform scraper and persist results.

Supported platforms:

* ``telegram``  — M2 (Telethon, optional extra).
* ``instagram`` — M3 (Playwright; public hashtag / profile / location / post).
* ``x``         — M3 (Playwright; nitter-first, x.com fallback).
* ``whatsapp``  — M3 (Playwright; public invite-link metadata only).

Run modes:

* ``--channel TARGET``          — single target (any platform).
* ``--channels-file path.txt``  — one target per line (telegram only).
* ``--search "keyword"``        — discovery mode (telegram only).

Events are written to the ``Store`` (NDJSON + SQLite) after the cleaner runs.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from osint.logging_setup import configure_logging, get_logger
from osint.processing.clean import clean_events
from osint.processing.store import Store
from osint.schemas import RawEvent

log = get_logger(__name__)

_SUPPORTED = ("telegram", "instagram", "x", "whatsapp")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="osint-scrape",
        description="Run a platform scraper and persist results to the local store.",
    )
    parser.add_argument("platform", choices=_SUPPORTED, help="Target platform")
    parser.add_argument(
        "--channel",
        help="Single channel/handle/hashtag (platform-specific).",
    )
    parser.add_argument(
        "--channels-file",
        help="Path to a text file with one channel/handle per line.",
    )
    parser.add_argument(
        "--search",
        help="Discovery mode: search the platform for this keyword and scrape the top results.",
    )
    parser.add_argument(
        "--discover-limit",
        type=int,
        default=5,
        help="Max number of channels to discover from a --search query (Telegram only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max events to capture per channel.",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Telegram session name (overrides TELEGRAM_SESSION in .env). "
             "Use the session you bootstrapped with scripts/bootstrap_telegram_session.py.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip the Pandas cleaner; persist raw events as-is.",
    )
    return parser.parse_args(argv)


def _events_for(args: argparse.Namespace) -> Iterable[RawEvent]:
    """Dispatch to the right scraper entry point and return an iterable of events."""
    if args.platform not in ("telegram", "instagram", "x", "whatsapp"):
        log.warning(
            "osint.cli.scrape.not_implemented",
            platform=args.platform,
            hint=f"Scraper for {args.platform!r} lands in a later milestone.",
        )
        return []

    # Importing the scraper module here (a) keeps the CLI importable when an
    # optional extra isn't installed, and (b) triggers the scraper's
    # @register decorator so it appears in the BaseScraper registry.
    if args.platform == "telegram":
        from osint.scrapers.telegram import (  # type: ignore[import-not-found]
            TelegramScraper,
            discover_and_run,
            run_from_file,
        )

        if args.search:
            return discover_and_run(
                args.search,
                discover_limit=args.discover_limit,
                per_channel_limit=args.limit,
            )
        if args.channels_file:
            return run_from_file(args.channels_file, limit=args.limit, session_name=args.session)
        if args.channel:
            return TelegramScraper(session_name=args.session).run(args.channel, limit=args.limit)
        log.warning(
            "osint.cli.scrape.no_target",
            platform=args.platform,
            hint="pass --channel, --channels-file, or --search",
        )
        return []

    if args.platform == "instagram":
        from osint.scrapers.instagram import InstagramScraper  # type: ignore[import-not-found]

        if not args.channel:
            log.warning("osint.cli.scrape.no_target", platform=args.platform, hint="pass --channel")
            return []
        return InstagramScraper().run(args.channel, limit=args.limit)

    if args.platform == "x":
        from osint.scrapers.x import XScraper  # type: ignore[import-not-found]

        if not args.channel:
            log.warning("osint.cli.scrape.no_target", platform=args.platform, hint="pass --channel")
            return []
        return XScraper().run(args.channel, limit=args.limit)

    if args.platform == "whatsapp":
        from osint.scrapers.whatsapp import WhatsAppScraper  # type: ignore[import-not-found]

        if not args.channel:
            log.warning("osint.cli.scrape.no_target", platform=args.platform, hint="pass --channel")
            return []
        return WhatsAppScraper().run(args.channel, limit=args.limit)

    return []  # unreachable; argparse already validated the choice


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)

    raw_events = list(_events_for(args))
    if not raw_events:
        log.info("osint.cli.scrape.no_events", platform=args.platform)
        return 0

    events = raw_events if args.no_clean else clean_events(raw_events)
    store = Store()
    inserted = store.upsert_many(events)
    log.info(
        "osint.cli.scrape.done",
        platform=args.platform,
        raw=len(raw_events),
        after_clean=len(events),
        inserted=inserted,
        total=store.count(),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
