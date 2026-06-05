"""Tests for scripts/run_tests.py — the test runner wrapper.

The wrapper's job is to catch the case where a developer runs pytest
from a directory that doesn't have ``tests/`` and would otherwise get
``file or directory not found: tests/...``. We test the underlying
``_find_project_root`` function directly; we don't try to drive the full
``os.chdir`` + ``pytest.main`` flow from a test (that would mutate the
caller's environment).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.run_tests import _find_project_root


def test_finds_real_project_root() -> None:
    """Starting from the scripts/ dir, walk up to the project root."""
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    assert scripts_dir.is_dir(), f"expected {scripts_dir} to exist"
    result = _find_project_root(scripts_dir)
    assert result == scripts_dir.parent
    assert (result / "pyproject.toml").is_file()


def test_raises_when_no_pyproject_above(tmp_path: Path) -> None:
    """A scratch dir with no pyproject.toml anywhere above must error."""
    fake_script = tmp_path / "fake.py"
    fake_script.write_text("pass", encoding="utf-8")
    with pytest.raises(SystemExit, match="Could not find pyproject.toml"):
        _find_project_root(fake_script)


def test_finds_root_from_deeply_nested_path(tmp_path: Path) -> None:
    """Even if the start is many levels deep, walking up finds the root."""
    # Create: tmp/project/pyproject.toml + tmp/project/a/b/c/script.py
    project = tmp_path / "project"
    deep = project / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "smart-osint-fraud-intel"\n', encoding="utf-8"
    )
    script = deep / "script.py"
    script.write_text("pass", encoding="utf-8")
    assert _find_project_root(script) == project
