from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from forge_scholar_config import resolve_database_path


@pytest.mark.parametrize(
    ("platform", "suffix"),
    [
        ("darwin", "Library/Application Support/Forge Scholar/scholar.duckdb"),
        ("linux", ".local/share/Forge Scholar/scholar.duckdb"),
        ("win32", "AppData/Local/Forge Scholar/scholar.duckdb"),
    ],
)
def test_default_storage_is_portable_and_does_not_create_files(tmp_path, platform, suffix):
    home = tmp_path / "fictional-home"
    actual = resolve_database_path(environment={}, home=home, platform=platform)
    assert actual == home / suffix
    assert not home.exists()
    assert "Vault" not in actual.parts


def test_explicit_database_wins_over_platform_default(tmp_path):
    target = tmp_path / "classroom" / "custom.duckdb"
    assert resolve_database_path(
        environment={"FORGE_SCHOLAR_DB": str(target), "XDG_DATA_HOME": str(tmp_path / "ignored")},
        home=tmp_path / "home",
        platform="linux",
    ) == target
    assert not target.parent.exists()


def test_xdg_absolute_directory_is_used_but_relative_value_is_ignored(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "app-data"
    assert resolve_database_path(
        environment={"XDG_DATA_HOME": str(root)}, home=home, platform="linux"
    ) == root / "Forge Scholar" / "scholar.duckdb"
    assert resolve_database_path(
        environment={"XDG_DATA_HOME": "relative-data"}, home=home, platform="linux"
    ) == home / ".local" / "share" / "Forge Scholar" / "scholar.duckdb"


@pytest.mark.parametrize("value", ["", "  ", ":memory:"])
def test_invalid_override_fails_instead_of_silently_using_another_database(value):
    with pytest.raises(ValueError, match="persistent database file"):
        resolve_database_path(environment={"FORGE_SCHOLAR_DB": value})


def test_all_backend_modules_share_explicit_storage_and_initialize_it(tmp_path):
    """A fresh process proves configuration is applied before import/schema work."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "isolated" / "classroom.duckdb"
    environment = dict(os.environ, HOME=str(home), FORGE_SCHOLAR_DB=str(target))
    code = """
from pathlib import Path
import forge_scholar, forge_teacher, forge_assignments, forge_admin, forge_teacher_dashboard
modules = (forge_scholar, forge_teacher, forge_assignments, forge_admin, forge_teacher_dashboard)
assert len({module.SCHOLAR_DB for module in modules}) == 1
assert not Path(forge_scholar.SCHOLAR_DB).exists()
forge_scholar.init_scholar_db()
forge_teacher.init_teacher_db()
forge_assignments.init_assignments_db()
forge_admin.init_admin_db()
with forge_scholar._con() as connection:
    tables = {row[0] for row in connection.execute('SHOW TABLES').fetchall()}
assert {'scholar_students', 'teacher_profiles', 'assignments', 'schools'} <= tables
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.is_file()
    assert not (home / "Vault").exists()
