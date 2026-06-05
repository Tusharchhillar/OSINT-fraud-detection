"""SQLite + NDJSON storage for events.

Two write targets on purpose:

* **NDJSON** (append-only) is the audit log. Once a line is written, it is never
  rewritten — perfect for replaying into another system or for forensics.
  The active file is ``data/raw/events.ndjson``; when it exceeds
  ``OSINT_NDJSON_ROTATE_BYTES`` it is gzipped to
  ``events-<UTC-timestamp>.ndjson.gz`` and a fresh empty file is started.
* **SQLite** is the queryable view used by the dashboard and tests. Inserts are
  idempotent on ``event_id`` (UNIQUE constraint + ``INSERT OR IGNORE``).

The two stay in sync inside :meth:`Store.upsert_many`; either both succeed or the
caller is told about the failure with the offending rows.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
    urls         TEXT NOT NULL DEFAULT '[]',        -- JSON array
    media        TEXT NOT NULL DEFAULT '[]',        -- JSON array
    language     TEXT,                              -- ISO-639-1, nullable
    content_hash TEXT,                              -- sha256 of normalized text+URLs
    intent       TEXT NOT NULL DEFAULT 'benign',
    risk_score   REAL NOT NULL DEFAULT 0.0,
    category     TEXT,
    indicators   TEXT NOT NULL DEFAULT '[]',        -- JSON array
    reasoning    TEXT,
    scored_at    TEXT,
    raw          TEXT NOT NULL DEFAULT '{}'         -- JSON object
);
CREATE INDEX IF NOT EXISTS idx_events_platform ON events(platform);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_risk ON events(risk_score);
CREATE INDEX IF NOT EXISTS idx_events_content_hash ON events(content_hash);
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
        ev.language,
        ev.content_hash,
        (enriched.intent if enriched else "benign"),
        (enriched.risk_score if enriched else 0.0),
        (enriched.category if enriched else None),
        json.dumps(enriched.indicators if enriched else []),
        (enriched.reasoning if enriched else None),
        (enriched.scored_at.isoformat() if enriched and enriched.scored_at else None),
        json.dumps(ev.raw),
    )


class Store:
    """Thin wrapper around a single SQLite file + a rotating NDJSON audit log."""

    def __init__(self, db_path: str | Path | None = None, ndjson_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.db_path
        self.ndjson_path = Path(ndjson_path) if ndjson_path else settings.raw_log_path
        self.rotate_bytes: int = settings.ndjson_rotate_bytes
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
        log.info("osint.store.schema_ready", db_path=str(self.db_path))

    # ---------- writes ----------

    def _maybe_rotate_ndjson(self) -> None:
        """If the active NDJSON file exceeds the rotation threshold, gzip it.

        Rotation is a no-op when the file doesn't exist or is below the threshold.
        The rotated file is named ``events-<UTC-timestamp>.ndjson.gz`` and lives
        next to the active file.
        """
        if self.rotate_bytes <= 0:
            return
        if not self.ndjson_path.exists():
            return
        try:
            size = self.ndjson_path.stat().st_size
        except OSError:
            return
        if size < self.rotate_bytes:
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rotated = self.ndjson_path.with_name(f"events-{ts}.ndjson.gz")
        # gzipped rotation: open the destination in gzip mode, copy bytes.
        with self.ndjson_path.open("rb") as src, gzip.open(rotated, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # Truncate the active file (open in write mode = truncate).
        self.ndjson_path.write_text("", encoding="utf-8")
        log.info(
            "osint.store.ndjson_rotated",
            rotated_to=str(rotated),
            rotated_bytes=size,
        )

    def upsert_many(self, events: Sequence[RawEvent | EnrichedEvent]) -> int:
        """Insert events, ignoring duplicates. Writes NDJSON mirror first.

        Returns the number of *new* rows inserted (excludes duplicates).
        """
        if not events:
            return 0

        # 1) Append-only NDJSON: every event goes in, even duplicates. This is
        # the audit trail and must reflect every observation. Rotate first if
        # the existing file is large.
        self._maybe_rotate_ndjson()
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
                    urls, media, language, content_hash,
                    intent, risk_score, category, indicators,
                    reasoning, scored_at, raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = cur.rowcount if cur.rowcount is not None else 0

        log.info("osint.store.upsert", attempted=len(events), inserted=inserted)
        return inserted

    # ---------- reads ----------

    def all_events(self) -> pd.DataFrame:
        """Return every event as a DataFrame (used by the dashboard)."""
        with self._conn() as conn:
            df = pd.read_sql_query("SELECT * FROM events ORDER BY timestamp DESC", conn)
        return df

    def iter_ndjson(self) -> Iterator[RawEvent]:
        """Yield events from the active NDJSON audit log in order.

        Rotated ``.ndjson.gz`` files are not replayed automatically; point a
        separate reader at them if you need full history.
        """
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

    # ---------- exports ----------

    def export_parquet(self, path: str | Path | None = None) -> Path:
        """Write the entire events table to a Parquet file.

        Returns the path written. The dashboard (M6) uses this for fast columnar
        reads without going through SQLite on every refresh.
        """
        out = Path(path) if path else self.db_path.with_suffix(".parquet")
        df = self.all_events()
        df.to_parquet(out, index=False)
        log.info("osint.store.export_parquet", path=str(out), rows=len(df))
        return out
