"""``osint-process`` — read NDJSON, clean, and persist to SQLite.

For M1 this is a smoke command: it reads the raw audit log (if any) and re-runs the
cleaning + dedupe step, reporting what changed. Real per-stage processing lands in
M4. The command is safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import sys

from osint.logging_setup import configure_logging, get_logger
from osint.processing.clean import clean_events
from osint.processing.store import Store
from osint.schemas import RawEvent

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="osint-process",
        description="Clean events from the NDJSON audit log and persist to SQLite.",
    )
    parser.add_argument(
        "--from-ndjson",
        action="store_true",
        help="Re-ingest everything from the raw NDJSON audit log.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Insert a small set of demo events (useful for first-run smoke tests).",
    )
    return parser.parse_args(argv)


def _seed_events() -> list[RawEvent]:
    """A handful of representative events for the smoke command."""
    return [
        RawEvent.from_scraped(
            platform="telegram",
            source="@scam_promos_demo",
            text="Join our VIP channel for 10x crypto returns! https://t.me/joinchat/abc123",
            author="demo_user",
        ),
        RawEvent.from_scraped(
            platform="instagram",
            source="#giveaway",
            text="DM me to claim your $500 gift card 🎁",
            author="promo_page",
        ),
        RawEvent.from_scraped(
            platform="x",
            source="@investor_handle",
            text="Legit job posting: work 2h/day, earn 5k/week. DM for details.",
        ),
        RawEvent.from_scraped(
            platform="whatsapp",
            source="chat.whatsapp.com/DEMO123",
            text="Click here to join the investment group: https://chat.whatsapp.com/DEMO123",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)

    store = Store()

    if args.seed:
        events = _seed_events()
        inserted = store.upsert_many(events)
        log.info("osint.cli.process.seeded", inserted=inserted, total=store.count())
        return 0

    if args.from_ndjson:
        raw = list(store.iter_ndjson())
        cleaned = clean_events(raw)
        before = len(raw)
        after = len(cleaned)
        inserted = store.upsert_many(cleaned)
        log.info(
            "osint.cli.process.reingest",
            read=before,
            after_clean=after,
            inserted=inserted,
            total=store.count(),
        )
        return 0

    log.warning("osint.cli.process.no_action", hint="pass --seed or --from-ndjson")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
