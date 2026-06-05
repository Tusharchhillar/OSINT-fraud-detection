"""Tests for the project-root guard in tests/conftest.py.

The guard's job is to catch the case where someone runs ``pytest`` from
the wrong directory and would otherwise see the cryptic
``file or directory not found: tests/...``. We test the underlying
checker function directly — driving the full pytest config from a test
is more trouble than it's worth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Importing from conftest works because pytest puts the tests/ directory
# on sys.path during collection. We import the helper, not the fixtures,
# to keep this test independent of OSINT_DATA_DIR env state.
from conftest import _check_project_root


def test_check_passes_for_real_project_root() -> None:
    """The actual project root must pass the guard."""
    # tests/conftest.py → tests/ → project root
    project_root = Path(__file__).resolve().parent.parent
    _check_project_root(project_root)  # should not raise


def test_check_raises_when_no_pyproject(tmp_path: Path) -> None:
    """A directory without pyproject.toml must trigger a UsageError."""
    with pytest.raises(pytest.UsageError, match="pytest was not run from the project root"):
        _check_project_root(tmp_path)


def test_check_raises_when_pyproject_is_wrong_project(tmp_path: Path) -> None:
    """A pyproject.toml from a different project must be rejected."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "some-other-project"\nversion = "0.0.1"\n',
        encoding="utf-8",
    )
    with pytest.raises(pytest.UsageError, match="does not look like this project"):
        _check_project_root(tmp_path)
