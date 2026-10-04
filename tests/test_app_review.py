"""Regression coverage for approval using the version actually shown to a teacher."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from scholar_demo import (
    get_classroom,
    get_lesson,
    get_student_preview,
    initialize_demo,
    save_lesson_draft,
)


def test_stale_ui_click_cannot_approve_an_unseen_lesson(tmp_path, monkeypatch):
    db = tmp_path / "fictional-classroom.sqlite3"
    monkeypatch.setenv("FORGE_SCHOLAR_DEMO_DB", str(db))
    initialize_demo(db)
    suggestion = get_classroom(db)["recommended_lesson"]
    save_lesson_draft(
        db,
        title="The version this teacher reviewed",
        objective=suggestion["objective"],
        activities=suggestion["activities"],
    )
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    app.button_group[0].set_value("Next lesson").run()
    assert not app.exception
    stale_button = next(
        button for button in app.button
        if button.label == "Approve saved lesson for student preview"
    )

    # Another browser changes the saved lesson after this page has rendered.
    # The click must carry the old displayed token, even though Streamlit
    # reloads the current lesson during the subsequent script execution.
    unseen = save_lesson_draft(
        db,
        title="An unseen edit from another browser",
        objective=suggestion["objective"],
        activities=suggestion["activities"],
    )
    assert unseen["version"] == 2
    stale_button.click().run()
    assert not app.exception
    assert get_lesson(db)["version"] == 2
    assert get_lesson(db)["status"] == "draft"
    assert get_student_preview(db, "fictional_avery")["lesson"] is None
    assert any("Review the current version" in error.value for error in app.error)

    # Once the replacement has actually been rendered, a fresh approval may
    # approve that exact version; the stale-error path must not break recovery.
    next(button for button in app.button if button.label == stale_button.label).click().run()
    assert not app.exception
    assert get_lesson(db)["status"] == "approved"
    assert get_student_preview(db, "fictional_avery")["lesson"]["title"] == unseen["title"]
