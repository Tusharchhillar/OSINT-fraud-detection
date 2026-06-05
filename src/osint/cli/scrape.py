"""``osint-scrape`` — dispatch to a platform scraper and persist results.

Supported platforms depend on which scraper modules are installed. Currently:

* ``telegram`` — implemented in M2 (Telethon, optional extra).
* ``instagram``, ``x``, ``whatsapp`` — land in M3.

Three run modes for any platform that supports them:

* ``--channel @handle``         — single target.
* ``--channels-file path.txt``  — one target per line.
* ``--search "keyword"``        — discovery mode (Telegram only for M2).

Events are written to the ``Store`` (NDJSON + SQLite). On any platform that
isn't implemented, the CLI exits with code 2 and a clear ``not_implemented``
log line — never a silent stub failure.
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
        "--no-clean",
        action="store_true",
        help="Skip the Pandas cleaner; persist raw events as-is.",
    )
    return parser.parse_args(argv)


def _events_for(args: argparse.Namespace) -> Iterable[RawEvent]:
    """Dispatch to the right scraper entry point and return an iterable of events."""
    if args.platform != "telegram":
        log.warning(
            "osint.cli.scrape.not_implemented",
            platform=args.platform,
            hint=f"Scraper for {args.platform!r} lands in a later milestone (M3).",
        )
        return []

    # Importing inside the function keeps the CLI importable even when the
    # `telegram` extra isn't installed.
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
        return run_from_file(args.channels_file, limit=args.limit)
    if args.channel:
        return TelegramScraper().run(args.channel, limit=args.limit)

    log.warning(
        "osint.cli.scrape.no_target",
        platform=args.platform,
        hint="pass --channel, --channels-file, or --search",
    )
    return []


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
