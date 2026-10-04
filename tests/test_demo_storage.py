from pathlib import Path
import pytest
from forge_scholar_config import resolve_demo_database_path


def test_demo_does_not_follow_the_legacy_database_override(tmp_path):
    home = tmp_path / 'person'
    demo = resolve_demo_database_path(environment={'FORGE_SCHOLAR_DB': str(tmp_path / 'legacy.duckdb')}, home=home, platform='darwin')
    assert demo == home / 'Library/Application Support/Forge Scholar/fictional-classroom.sqlite3'
    assert not home.exists()


def test_demo_honors_windows_local_app_data(tmp_path):
    demo = resolve_demo_database_path(environment={'LOCALAPPDATA':str(tmp_path / 'local')}, home=tmp_path / 'home', platform='win32')
    assert demo == tmp_path / 'local/Forge Scholar/fictional-classroom.sqlite3'


@pytest.mark.parametrize('value', ['', '   ', ':memory:'])
def test_demo_rejects_invalid_storage_override(value):
    with pytest.raises(ValueError, match='FORGE_SCHOLAR_DEMO_DB'):
        resolve_demo_database_path(environment={'FORGE_SCHOLAR_DEMO_DB':value})
