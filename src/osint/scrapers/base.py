"""Base interface every platform scraper implements.

The contract is intentionally tiny so we can write generic code in the dashboard
and the processing pipeline (M4) that works across all platforms:

* :meth:`BaseScraper.run` returns an iterator of :class:`~osint.schemas.RawEvent`.
* :meth:`BaseScraper.close` releases any resources (network clients, browsers, etc.).

Scrapers are *not* responsible for persistence — that's the ``Store``'s job. They
just yield events. The ``osint-scrape`` CLI dispatcher handles wiring scraper
output into the store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from osint.schemas import RawEvent


class BaseScraper(ABC):
    """Abstract base class for platform scrapers."""

    #: Lowercase platform name; must match the ``Platform`` literal in schemas.
    platform: str

    @abstractmethod
    def run(self, target: str, *, limit: int = 100) -> Iterator[RawEvent]:
        """Scrape up to ``limit`` events from ``target`` and yield them as ``RawEvent``s.

        ``target`` interpretation is platform-specific (channel handle, hashtag,
        search keyword, etc.).
        """
        raise NotImplementedError

    def close(self) -> None:  # noqa: B027  (intentional no-op default)
        """Release any resources. Default: no-op."""
        return None


# A small registry maps the CLI's ``platform`` argument to a scraper factory.
# Concrete scrapers register themselves on import.
REGISTRY: dict[str, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Class decorator that adds ``cls`` to the ``REGISTRY`` under ``cls.platform``."""
    if not getattr(cls, "platform", None):
        raise ValueError(f"{cls.__name__} must define a non-empty `platform` attribute")
    REGISTRY[cls.platform] = cls
    return cls


def build_scraper(platform: str, **kwargs: Any) -> BaseScraper:
    """Look up a scraper class in the registry and instantiate it with ``kwargs``."""
    if platform not in REGISTRY:
        raise KeyError(
            f"Unknown platform {platform!r}. Known: {sorted(REGISTRY)}. "
            f"Did you forget to import the scraper module?"
        )
    return REGISTRY[platform](**kwargs)
