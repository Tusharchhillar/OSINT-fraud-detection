"""``osint-scrape`` — placeholder for the per-platform scraper runners.

The real scrapers land in M2 (Telegram) and M3 (IG / X / WA). For now this is a
dispatcher that prints a helpful message and exits non-zero so we notice the
missing platform in CI.
"""

from __future__ import annotations

import argparse
import sys

from osint.logging_setup import configure_logging, get_logger

log = get_logger(__name__)

_SUPPORTED = ("telegram", "instagram", "x", "whatsapp")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="osint-scrape", description="Run a platform scraper.")
    parser.add_argument("platform", choices=_SUPPORTED, help="Target platform")
    parser.add_argument("--channel", help="Channel / handle / hashtag (platform-specific)")
    parser.add_argument("--limit", type=int, default=100, help="Max events to capture")
    args = parser.parse_args(argv)

    log.warning(
        "osint.cli.scrape.not_implemented",
        platform=args.platform,
        hint=f"Scraper for {args.platform!r} lands in a later milestone (M2/M3).",
    )
    return 2  # distinct exit code so the run is easy to spot in CI


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
