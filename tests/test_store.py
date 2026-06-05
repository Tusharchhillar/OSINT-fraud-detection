"""Tests for the SQLite + NDJSON store."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from osint.processing.store import Store
from osint.schemas import EnrichedEvent, RawEvent


def _sample_events() -> list[RawEvent]:
    return [
        RawEvent.from_scraped(platform="telegram", source="@a", text="one"),
        RawEvent.from_scraped(platform="instagram", source="@b", text="two"),
        RawEvent.from_scraped(platform="x", source="@c", text="three"),
    ]


def test_upsert_is_idempotent(temp_data_dir) -> None:
    store = Store()
    events = _sample_events()

    assert store.upsert_many(events) == 3
    # Second insert of the same events: nothing new.
    assert store.upsert_many(events) == 0
    assert store.count() == 3


def test_ndjson_records_every_observation(temp_data_dir) -> None:
    store = Store()
    events = _sample_events()
    store.upsert_many(events)
    store.upsert_many(events)  # re-write on purpose

    ndjson_lines = list(store.iter_ndjson())
    # Audit log keeps every line, even duplicates.
    assert len(ndjson_lines) == 6
    # SQLite is still 3 unique rows.
    assert store.count() == 3


def test_enriched_event_round_trips_through_sqlite(temp_data_dir) -> None:
    store = Store()
    base = RawEvent.from_scraped(platform="telegram", source="@a", text="scammy")
    enriched = EnrichedEvent(
        **base.model_dump(),
        intent="scam",
        risk_score=92.0,
        category="crypto-pump",
        indicators=["high-return promise"],
    )
    store.upsert_many([enriched])

    df = store.all_events()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["intent"] == "scam"
    assert float(row["risk_score"]) == 92.0
    assert row["category"] == "crypto-pump"


def test_empty_upsert_is_noop(temp_data_dir) -> None:
    store = Store()
    assert store.upsert_many([]) == 0
    assert store.count() == 0


def test_export_parquet(temp_data_dir) -> None:
    pytest.importorskip("pyarrow")
    store = Store()
    store.upsert_many(_sample_events())

    out = store.export_parquet()
    assert out.exists()
    assert out.suffix == ".parquet"

    # Round-trip via pandas to confirm we can read it back.
    import pandas as pd

    df = pd.read_parquet(out)
    assert len(df) == 3
    assert set(df["platform"]) == {"telegram", "instagram", "x"}


def test_ndjson_rotation_at_threshold(temp_data_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the audit file crosses the threshold, it should be gzipped."""
    store = Store()
    # Force a tiny threshold so we can trigger rotation cheaply.
    store.rotate_bytes = 200  # 200 bytes

    # 1) Write a single event and verify no rotation yet.
    store.upsert_many(_sample_events())
    rotated_files = list(store.ndjson_path.parent.glob("events-*.ndjson.gz"))
    assert rotated_files == []

    # 2) Stuff the file past the threshold.
    store.ndjson_path.write_text("x" * 1024, encoding="utf-8")

    # 3) Next upsert triggers rotation.
    store.upsert_many(_sample_events())

    rotated_files = sorted(store.ndjson_path.parent.glob("events-*.ndjson.gz"))
    assert len(rotated_files) == 1
    # The rotated file is a valid gzip with the original payload.
    with gzip.open(rotated_files[0], "rt", encoding="utf-8") as fh:
        assert fh.read() == "x" * 1024
    # The active file is fresh and small.
    assert store.ndjson_path.stat().st_size < 1024


def test_ndjson_rotation_disabled_with_zero_threshold(
    temp_data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store()
    store.rotate_bytes = 0  # explicit "off"
    store.ndjson_path.write_text("x" * 1024, encoding="utf-8")
    store.upsert_many(_sample_events())
    assert list(store.ndjson_path.parent.glob("events-*.ndjson.gz")) == []


def test_content_hash_persists_in_sqlite(temp_data_dir) -> None:
    store = Store()
    ev = RawEvent.from_scraped(platform="x", source="@h", text="hello world")
    store.upsert_many([ev])

    df = store.all_events()
    assert df.iloc[0]["content_hash"] == ev.content_hash
    assert len(df.iloc[0]["content_hash"]) == 64
