"""Portable storage configuration, resolved before backend modules are imported.

No directories or databases are created by importing this module.  Existing
Forge installations can opt into their database explicitly with
``FORGE_SCHOLAR_DB``; a standalone checkout never searches or opens the Vault.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping


def resolve_database_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Return the explicit database file or the platform's user-data location.

    Environment changes take effect on the next process start.  Relative
    overrides resolve against the current working directory; an absolute path
    is recommended when several launchers share a database.
    """
    environment = os.environ if environment is None else environment
    home = Path.home() if home is None else Path(home)
    platform = sys.platform if platform is None else platform

    if "FORGE_SCHOLAR_DB" in environment:
        configured = environment["FORGE_SCHOLAR_DB"].strip()
        if not configured or configured == ":memory:":
            raise ValueError("FORGE_SCHOLAR_DB must name a persistent database file.")
        return Path(configured).expanduser().resolve()

    if platform == "darwin":
        data_root = home / "Library" / "Application Support"
    elif platform == "win32":
        configured_root = environment.get("LOCALAPPDATA", "")
        data_root = Path(configured_root) if configured_root else home / "AppData" / "Local"
    else:
        configured_root = environment.get("XDG_DATA_HOME", "")
        candidate = Path(configured_root) if configured_root else None
        # XDG_DATA_HOME is specified as an absolute path. Ignore a relative
        # value rather than accidentally placing user data in a checkout.
        data_root = (
            candidate
            if candidate is not None and candidate.is_absolute()
            else home / ".local" / "share"
        )

    return (data_root / "Forge Scholar" / "scholar.duckdb").resolve()


def resolve_demo_database_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Use the platform data directory, independent of the legacy DB override."""
    environment = os.environ if environment is None else environment
    if "FORGE_SCHOLAR_DEMO_DB" in environment:
        configured = environment["FORGE_SCHOLAR_DEMO_DB"].strip()
        if not configured or configured == ":memory:":
            raise ValueError("FORGE_SCHOLAR_DEMO_DB must name a persistent database file.")
        return Path(configured).expanduser().resolve()
    isolated_environment = {key: value for key, value in environment.items() if key != "FORGE_SCHOLAR_DB"}
    return resolve_database_path(environment=isolated_environment, home=home, platform=platform).with_name("fictional-classroom.sqlite3")
