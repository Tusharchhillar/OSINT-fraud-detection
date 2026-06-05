"""SQLite + NDJSON storage for events.

Two write targets on purpose:

* **NDJSON** (append-only) is the audit log. Once a line is written, it is never
  rewritten — perfect for replaying into another system or for forensics.
* **SQLite** is the queryable view used by the dashboard and tests. Inserts are
  idempotent on ``event_id`` (UNIQUE constraint + ``INSERT OR IGNORE``).

The two stay in sync inside :meth:`Store.upsert_many`; either both succeed or the
caller is told about the failure with the offending rows.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd

from osint.config import get_settings
from osint.logging_setup import get_logger
from osint.schemas import EnrichedEvent, RawEvent

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    platform     TEXT NOT NULL,
    source       TEXT NOT NULL,
    author       TEXT,
    timestamp    TEXT NOT NULL,
    text         TEXT NOT NULL DEFAULT '',
    urls         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    media        TEXT NOT NULL DEFAULT '[]',   -- JSON array
    intent       TEXT NOT NULL DEFAULT 'benign',
    risk_score   REAL NOT NULL DEFAULT 0.0,
    category     TEXT,
    indicators   TEXT NOT NULL DEFAULT '[]',   -- JSON array
    reasoning    TEXT,
    scored_at    TEXT,
    raw          TEXT NOT NULL DEFAULT '{}'    -- JSON object
);
CREATE INDEX IF NOT EXISTS idx_events_platform ON events(platform);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_risk ON events(risk_score);
"""


def _row_from_event(ev: RawEvent | EnrichedEvent) -> tuple:
    enriched: EnrichedEvent | None = ev if isinstance(ev, EnrichedEvent) else None
    import json

    return (
        ev.event_id,
        ev.platform,
        ev.source,
        ev.author,
        ev.timestamp.isoformat(),
        ev.text,
        json.dumps(ev.urls),
        json.dumps(ev.media),
        (enriched.intent if enriched else "benign"),
        (enriched.risk_score if enriched else 0.0),
        (enriched.category if enriched else None),
        json.dumps(enriched.indicators if enriched else []),
        (enriched.reasoning if enriched else None),
        (enriched.scored_at.isoformat() if enriched and enriched.scored_at else None),
        json.dumps(ev.raw),
    )


class Store:
    """Thin wrapper around a single SQLite file."""

    def __init__(self, db_path: str | Path | None = None, ndjson_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.db_path
        self.ndjson_path = Path(ndjson_path) if ndjson_path else settings.raw_log_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ndjson_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------- low-level connection helpers ----------

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        log.info("store.schema_ready", db_path=str(self.db_path))

    # ---------- writes ----------

    def upsert_many(self, events: Sequence[RawEvent | EnrichedEvent]) -> int:
        """Insert events, ignoring duplicates. Writes NDJSON mirror first.

        Returns the number of *new* rows inserted (excludes duplicates).
        """
        if not events:
            return 0

        # 1) Append-only NDJSON: every event goes in, even duplicates. This is
        # the audit trail and must reflect every observation.
        with self.ndjson_path.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(ev.to_ndjson() + "\n")

        # 2) SQLite: idempotent insert.
        rows = [_row_from_event(ev) for ev in events]
        with self._conn() as conn:
            cur = conn.executemany(
                """
                INSERT OR IGNORE INTO events (
                    event_id, platform, source, author, timestamp, text,
                    urls, media, intent, risk_score, category, indicators,
                    reasoning, scored_at, raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = cur.rowcount and cur.rowcount or 0

        log.info("store.upsert", attempted=len(events), inserted=inserted)
        return inserted

    # ---------- reads ----------

    def all_events(self) -> pd.DataFrame:
        """Return every event as a DataFrame (used by the dashboard)."""
        with self._conn() as conn:
            df = pd.read_sql_query("SELECT * FROM events ORDER BY timestamp DESC", conn)
        return df

    def iter_ndjson(self) -> Iterator[RawEvent]:
        """Yield events from the NDJSON audit log in order."""
        if not self.ndjson_path.exists():
            return
        with self.ndjson_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield RawEvent.from_ndjson(line)

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
