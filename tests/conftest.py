"""Shared pytest fixtures + project-root guard.

The guard runs in :func:`pytest_configure` and verifies that pytest's
``rootdir`` actually points at the project (i.e. the directory containing
``pyproject.toml`` with ``name = "smart-osint-fraud-intel"``). If not, we
abort with a clear, actionable error — the default pytest error in this
case is just ``file or directory not found: tests/...`` which is hard to
interpret if you ran pytest from the wrong directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from osint.config import get_settings

EXPECTED_PROJECT_NAME = "smart-osint-fraud-intel"


def _check_project_root(rootdir: Path) -> None:
    """Raise :class:`pytest.UsageError` if ``rootdir`` is not this project.

    Pure function — no pytest config object needed — so it's trivial to
    unit-test in isolation. ``pytest_configure`` just calls it.
    """
    pyproject = rootdir / "pyproject.toml"
    if not pyproject.is_file():
        raise pytest.UsageError(
            "pytest was not run from the project root.\n"
            f"  current rootdir: {rootdir}\n"
            "  expected to find: pyproject.toml at the root\n"
            "\n"
            "Fix: cd into the project directory and re-run, e.g.\n"
            '    cd "D:\\GPCSSI 2026\\final project"\n'
            "    python -m pytest\n"
        )
    # Cheap sanity check: does the pyproject.toml name match this project?
    contents = pyproject.read_text(encoding="utf-8")
    first_line = contents.splitlines()[0] if contents else ""
    if EXPECTED_PROJECT_NAME not in contents:
        raise pytest.UsageError(
            f"pyproject.toml at {pyproject} does not look like this project "
            f"(expected to find '{EXPECTED_PROJECT_NAME}').\n"
            f"  first line: {first_line!r}\n"
        )


def pytest_configure(config: pytest.Config) -> None:
    """Abort early with a helpful message if pytest's rootdir is wrong."""
    _check_project_root(Path(config.rootdir).resolve())


@pytest.fixture
def temp_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the package at a fresh temp dir so tests don't touch the real DB."""
    monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OSINT_RAW_LOG", str(tmp_path / "raw" / "events.ndjson"))
    monkeypatch.setenv("OSINT_DB_PATH", str(tmp_path / "osint.db"))
    # The Settings object is cached; clear it so the new env vars take effect.
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
