"""Pandas-based cleaning of raw events.

Kept deliberately small for M1: deduplicate, drop empties, normalize URL casing,
length-filter obvious noise (e.g. emoji-only lines). Bigger heuristics (language
tagging, keyword detection) land in M4.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from osint.schemas import RawEvent

_TRACKERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


def _normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    # Strip common trackers, lowercase host.
    query_pairs = []
    for kv in parts.query.split("&"):
        if not kv:
            continue
        k, _, _ = kv.partition("=")
        if k.lower() in _TRACKERS:
            continue
        query_pairs.append(kv)
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, "&".join(query_pairs), ""))


def clean_events(events: Iterable[RawEvent]) -> list[RawEvent]:
    """Apply light cleaning and dedupe. Returns a new list (does not mutate input)."""
    df = pd.DataFrame([ev.model_dump() for ev in events])
    if df.empty:
        return []

    # Drop exact duplicates by event_id (the source of truth).
    df = df.drop_duplicates(subset=["event_id"], keep="first")

    # Drop rows with empty text AND no urls/media.
    has_payload = (df["text"].fillna("").str.len() > 0) | (df["urls"].apply(len) > 0) | (
        df["media"].apply(len) > 0
    )
    df = df[has_payload]

    # Drop emoji-only / noise messages (no alphanumeric letters at all).
    def _has_letters(s: str) -> bool:
        return any(ch.isalpha() for ch in s)

    df = df[df["text"].fillna("").apply(_has_letters)]

    # Normalize URLs.
    df["urls"] = df["urls"].apply(lambda lst: [_normalize_url(u) for u in lst])

    # Re-hydrate into RawEvent objects. Pydantic ignores unknown fields by default.
    cleaned: list[RawEvent] = []
    for row in df.to_dict(orient="records"):
        # DataFrame can stringify datetimes; coerce back if needed.
        ts = row.get("timestamp")
        if hasattr(ts, "to_pydatetime"):
            row["timestamp"] = ts.to_pydatetime()
        elif isinstance(ts, str) and ts:
            try:
                from datetime import datetime

                row["timestamp"] = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                row.pop("timestamp", None)  # let the default factory fill it
        cleaned.append(RawEvent.model_validate(row))
    return cleaned
