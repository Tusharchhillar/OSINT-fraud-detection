"""Test runner wrapper.

Catches the "wrong directory" case the conftest guard cannot. Pytest's
``conftest.py`` is only loaded after rootdir is correctly resolved — and
rootdir is only correctly resolved when ``pyproject.toml`` is an ancestor
of the test path. So a user running ``pytest`` from an unrelated
directory gets the cryptic ``file or directory not found: tests/...``
error with no chance for us to intervene.

This script:

1. Resolves the project root (the directory containing ``pyproject.toml``)
   by walking up from this file — works regardless of the user's cwd.
2. cd's into that root so pytest's normal config discovery Just Works.
3. Invokes ``pytest.main()`` with any extra args the user passed.

Usage:

    python scripts/run_tests.py                       # whole suite
    python scripts/run_tests.py tests/test_telegram.py -v
    python scripts/run_tests.py -k live_scrape        # filter

If you run it from the wrong directory, you'll see a clear message
pointing at the project root, not the cryptic "tests/... not found".
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_project_root(start: Path) -> Path:
    """Walk up from ``start`` until we find a directory with ``pyproject.toml``.

    Raises ``SystemExit`` with a friendly message if we walk off the top of
    the filesystem without finding it. This is the same logic pytest uses
    to determine ``rootdir``, but we run it ourselves *before* invoking
    pytest so we can produce a useful error.
    """
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise SystemExit(
        f"Could not find pyproject.toml by walking up from {start}.\n"
        "Is this script inside the smart-osint-fraud-intel project?"
    )


def main(argv: list[str] | None = None) -> int:
    # sys.path manipulation isn't needed — pytest discovers tests/ via the
    # cwd we'll set, and `pyproject.toml`'s [tool.pytest.ini_options] adds
    # `src/` to pythonpath for us.
    project_root = _find_project_root(Path(__file__).resolve().parent)

    # cd into the project root so pytest's auto-config and test discovery
    # behave the same as if the user had typed the right command.
    import os

    os.chdir(project_root)

    # Add src/ to sys.path so the `osint` package imports cleanly when
    # this script is invoked via `python scripts/run_tests.py` (pytest's
    # pythonpath config only helps the test process itself, not us).
    sys.path.insert(0, str(project_root / "src"))

    import pytest  # imported after sys.path mutation

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        args = ["tests"]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
