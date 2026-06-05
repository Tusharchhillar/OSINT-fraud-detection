"""Pydantic schemas for events that flow through the pipeline.

We define a small set of records and let ``type: ignore`` slip in only where pydantic's
v2 ergonomics still demand a forward reference. Keeping the schemas in one file makes
it easy to evolve the wire format without hunting through the codebase.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Platform = Literal["telegram", "instagram", "x", "whatsapp", "unknown"]
IntentClass = Literal["benign", "suspicious", "scam", "illicit"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_event_id(platform: Platform, source: str, raw_id: str | None, text: str) -> str:
    """Stable event id: ``<platform>-<sha1[:12]>``.

    Falls back to hashing the text alone when the upstream platform doesn't give us
    a unique message id (e.g. some web scrapes).
    """
    payload = f"{platform}|{source}|{raw_id or ''}|{text}".encode("utf-8")
    digest = hashlib.sha1(payload).hexdigest()[:12]
    return f"{platform}-{digest}"


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class RawEvent(BaseModel):
    """A single piece of scraped content, as emitted by a scraper."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_id: str
    platform: Platform
    source: str = Field(..., description="Channel / handle / hashtag / phone")
    author: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)
    text: str = ""
    urls: list[str] = Field(default_factory=list)
    media: list[str] = Field(default_factory=list, description="URLs or refs to media")
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("urls", "media", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v)

    @classmethod
    def from_scraped(
        cls,
        *,
        platform: Platform,
        source: str,
        text: str,
        author: str | None = None,
        raw_id: str | None = None,
        urls: list[str] | None = None,
        media: list[str] | None = None,
        timestamp: datetime | None = None,
        raw: dict[str, Any] | None = None,
    ) -> "RawEvent":
        """Convenience constructor that auto-fills ``event_id`` and URL extraction."""
        extracted = list(urls or [])
        if not extracted:
            extracted = _URL_RE.findall(text or "")
        return cls(
            event_id=make_event_id(platform, source, raw_id, text or ""),
            platform=platform,
            source=source,
            author=author,
            timestamp=timestamp or _utcnow(),
            text=text or "",
            urls=extracted,
            media=list(media or []),
            raw=raw or {},
        )

    def to_ndjson(self) -> str:
        """Serialize to a single NDJSON line (no trailing newline)."""
        return self.model_dump_json()

    @classmethod
    def from_ndjson(cls, line: str) -> "RawEvent":
        return cls.model_validate_json(line)


class EnrichedEvent(RawEvent):
    """A ``RawEvent`` augmented with intent analysis and a composite risk score."""

    intent: IntentClass = "benign"
    risk_score: float = Field(0.0, ge=0.0, le=100.0)
    category: str | None = None
    indicators: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    scored_at: datetime = Field(default_factory=_utcnow)
