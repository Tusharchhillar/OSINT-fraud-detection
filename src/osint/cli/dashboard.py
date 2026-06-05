"""``osint-dashboard`` — placeholder for the Streamlit app (M6)."""

from __future__ import annotations

from osint.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


def main() -> int:
    configure_logging()
    log.warning("osint.cli.dashboard.not_implemented", hint="Streamlit app lands in M6.")
    print(
        "The Streamlit dashboard will be added in milestone M6.\n"
        "In the meantime, run:  poetry run osint-process --seed"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
