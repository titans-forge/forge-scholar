# Standalone classroom verification — October 3, 2026

This revision adds a self-contained fictional classroom example. It does not turn the original multi-page Forge workspace into a production school installation.

## Reproducible environment

A fresh Python 3.12.14 virtual environment installed `requirements-dev.txt`. Runtime versions: Streamlit 1.56.0, DuckDB 1.5.3, pytest 9.0.3. `python -m pip check` passed.

```sh
python -m pytest -q
```

Result: **28 tests passed**. Tests cover the original teacher workspace, portable database paths, fictional response counts, equivalent fraction answers, persistent drafts, hidden unapproved lessons, teacher-note exclusion from student payloads, concurrent saves, stale approvals and the actual Streamlit approval callback.

The stale-review regression renders version 1, saves version 2 from another session, clicks the old approval control, and verifies version 2 stays in draft. After a new review renders, approval succeeds.

## Rendered workflow

The in-app browser exercised the local app on `http://127.0.0.1:8531/` using an explicit disposable example database:

- Desktop: 1280 × 720. Phone layout: 390 × 844.
- Page identity and meaningful first render passed.
- No framework error overlay or relevant browser warning/error logs.
- Inspected exact student answers behind the fraction patterns.
- Edited a lesson, saved a draft and approved the displayed saved version.
- Confirmed the approved lesson appeared in the student preview.
- Edited the approved lesson; confirmed the new draft was hidden until reviewed and approved again.
- Reloaded the application and confirmed saved state persisted.
- Phone controls wrapped without horizontal page overflow; the approved student view remained usable.

Screenshots, installation receipts, dependency freeze and promotional media are kept outside the source checkout. The promotion uses actual UI captures from this fictional example, plus a mathematical animation and locally generated Qwen narration; it does not show live model inference.

## Boundaries

This is local demonstration and automated/browser verification, not independent teacher usability or student-outcome validation. The preview switch is not authentication. Real school deployment, different browsers, assistive-technology testing, model integrations and the complete legacy multi-page workspace remain unverified.

No live Forge Vault or real student records were used. The source is Apache 2.0; model weights and production environments are not included.
