"""Platform scrapers.

Each platform gets its own module under this package. All scrapers expose a
:class:`BaseScraper` interface (see :mod:`osint.scrapers.base`) so the rest of the
pipeline can treat them uniformly.

Adding a new platform in M3+: implement ``BaseScraper`` and register the class in
``osint.scrapers.REGISTRY`` so the ``osint-scrape`` CLI dispatcher can find it.
"""
