"""Pandas-based cleaning of raw events.

Pipeline (run in order, each step is logged):

1. **Dedupe** by ``event_id`` — the source of truth.
2. **Drop empty rows** — text is whitespace AND no urls AND no media.
3. **Drop emoji-only noise** — no alpha character in the text.
4. **Drop too-short messages** — stripped text shorter than ``_MIN_TEXT_LEN``.
5. **Normalize URLs** — strip ``utm_*`` / ``fbclid`` / ``gclid``, lowercase host.
6. **Flag shortener hosts** — append ``*.<host>`` markers to the URL list so M5
   heuristics can detect "message has a known shortened link".

Bigger heuristics (language tagging, keyword detection) land in M4.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from osint.logging_setup import get_logger
from osint.schemas import RawEvent

log = get_logger(__name__)

# Tracker query parameters we strip during URL normalization.
_TRACKERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}

# Hosts that we *flag* (not auto-expand) in the cleaner's output. Expansion is opt-in
# because it requires network calls; the flag is enough to drive M5 heuristics.
_KNOWN_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy",
}

# Drop messages whose stripped text is shorter than this.
_MIN_TEXT_LEN = 4


def _normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
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


def _has_letters(s: str) -> bool:
    return any(ch.isalpha() for ch in s)


def _is_shortener(url: str) -> bool:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    # Strip leading "www." for matching.
    if host.startswith("www."):
        host = host[4:]
    return host in _KNOWN_SHORTENERS


def clean_events(events: Iterable[RawEvent]) -> list[RawEvent]:
    """Apply light cleaning and dedupe. Returns a new list (does not mutate input)."""
    df = pd.DataFrame([ev.model_dump() for ev in events])
    if df.empty:
        log.info("osint.cleaner.empty_input")
        return []

    rows_in = len(df)

    # 1) Dedupe by event_id.
    df = df.drop_duplicates(subset=["event_id"], keep="first")
    dropped_dupes = rows_in - len(df)

    # 2) Drop rows with empty text AND no urls AND no media.
    has_payload = (df["text"].fillna("").str.len() > 0) | (df["urls"].apply(len) > 0) | (
        df["media"].apply(len) > 0
    )
    df = df[has_payload]
    dropped_empty = rows_in - dropped_dupes - len(df)

    # 3) Drop emoji-only / no-alpha noise.
    before = len(df)
    df = df[df["text"].fillna("").apply(_has_letters)]
    dropped_emoji = before - len(df)

    # 4) Drop too-short messages (only if they have no urls/media to anchor on).
    def _too_short(row: pd.Series) -> bool:
        if (len(row.get("urls") or []) + len(row.get("media") or [])) > 0:
            return False
        return len((row.get("text") or "").strip()) < _MIN_TEXT_LEN

    before = len(df)
    df = df[~df.apply(_too_short, axis=1)]
    dropped_short = before - len(df)

    # 5) Normalize URLs.
    df["urls"] = df["urls"].apply(lambda lst: [_normalize_url(u) for u in lst])

    # 6) Flag shortener hosts by appending a "*.<host>" marker to the URL list.
    #    Markers are non-URLs (start with "*.") so they can never be confused with
    #    real links by downstream consumers.
    def _flag_shorteners(lst: list[str]) -> list[str]:
        out = list(lst)
        for u in lst:
            if _is_shortener(u):
                try:
                    host = urlsplit(u).netloc.lower()
                except ValueError:
                    continue
                if host.startswith("www."):
                    host = host[4:]
                marker = f"*.{host}"
                if marker not in out:
                    out.append(marker)
        return out

    df["urls"] = df["urls"].apply(_flag_shorteners)

    log.info(
        "osint.cleaner.run",
        rows_in=rows_in,
        rows_out=len(df),
        dropped_dupes=dropped_dupes,
        dropped_empty=dropped_empty,
        dropped_emoji=dropped_emoji,
        dropped_short=dropped_short,
    )

    # Re-hydrate into RawEvent objects. Pydantic ignores unknown fields by default.
    cleaned: list[RawEvent] = []
    for row in df.to_dict(orient="records"):
        ts = row.get("timestamp")
        if hasattr(ts, "to_pydatetime"):
            row["timestamp"] = ts.to_pydatetime()
        elif isinstance(ts, str) and ts:
            try:
                row["timestamp"] = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                row.pop("timestamp", None)
        cleaned.append(RawEvent.model_validate(row))
    return cleaned
