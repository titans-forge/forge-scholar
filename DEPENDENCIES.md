# Dependencies and storage

The standalone classroom example needs Python and the packages in `requirements.txt`:

- Streamlit 1.56.0 renders the local interface.
- DuckDB 1.5.3 supports the included legacy Scholar backend.
- Python’s built-in SQLite library stores the fictional classroom example.

`requirements-dev.txt` adds pytest 9.0.3. Optional PDF/DOCX imports in the larger Scholar source require `requirements-documents.txt`; they are not needed to run the classroom example.

No model weights, API keys, Forge Vault, school account, or external service are needed by `app.py`. The example has no model-inference dependency.

## Separate databases

The standalone example uses `FORGE_SCHOLAR_DEMO_DB`, or the per-user `Forge Scholar/fictional-classroom.sqlite3` file. The larger legacy backend uses `FORGE_SCHOLAR_DB`, or `Forge Scholar/scholar.duckdb`.

Default app-data roots:

- macOS: `~/Library/Application Support`
- Linux: `~/.local/share`, or an absolute `XDG_DATA_HOME`.
- Windows: `LOCALAPPDATA`, or `~/AppData/Local`.

The standalone app binds to `127.0.0.1` in `.streamlit/config.toml`. Its preview role switch is not authentication; it is intended for local fictional data.
