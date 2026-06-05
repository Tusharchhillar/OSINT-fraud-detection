"""Tests for the SQLite + NDJSON store."""

from __future__ import annotations

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
