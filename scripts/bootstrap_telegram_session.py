"""One-time bootstrap for a Telethon session file.

Run this once on your machine to authenticate against Telegram and create the
``*.session`` file used by the scraper and the live integration test.

Usage:
    python -m scripts.bootstrap_telegram_session
    # or, with a custom session name:
    python -m scripts.bootstrap_telegram_session osint_test_session

You will be prompted for:
  1. Your phone number in international format (e.g. +91XXXXXXXXXX).
  2. The login code Telegram sends to your Telegram app.
  3. Your 2FA password, if you have one set.

The session is saved to ``<session_name>.session`` next to this script's
working directory. Subsequent runs of the scraper / live tests reuse the
file and do not prompt again.

Credentials are read from ``.env`` (TELEGRAM_API_ID, TELEGRAM_API_HASH) — the
script will refuse to run if either is missing.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make `osint.*` importable when this script is run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from osint.config import get_settings  # noqa: E402
from osint.logging_setup import configure_logging, get_logger  # noqa: E402

log = get_logger(__name__)


async def _bootstrap(session_name: str) -> None:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env. "
            "Get them at https://my.telegram.org → API development tools."
        )

    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit(
            "Telethon is not installed. Run:  pip install telethon"
        ) from exc

    client = TelegramClient(
        session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    print(f"Connecting to Telegram as session={session_name!r} ...")
    await client.connect()

    if not await client.is_user_authorized():
        # ``start()`` handles the phone + code + 2FA flow interactively.
        print("No existing session — starting interactive login.")
        await client.start()
    else:
        print("Existing authorized session found — nothing to do.")

    me = await client.get_me()
    print(f"Logged in as: {getattr(me, 'username', None) or me.first_name} (id={me.id})")
    await client.disconnect()
    log.info("osint.bootstrap.session_ready", session=session_name)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = argv if argv is not None else sys.argv[1:]
    session_name = args[0] if args else "osint_test_session"
    asyncio.run(_bootstrap(session_name))
    print(f"\nSession file ready: {session_name}.session")
    print("Future scraper / test runs will reuse it without prompting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
