"""Behavior tests for the portable, fictional classroom workflow."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from scholar_demo import (
    StaleLessonError,
    approve_lesson,
    get_classroom,
    get_lesson,
    get_student_preview,
    initialize_demo,
    save_lesson_draft,
)


@pytest.fixture
def demo_db(tmp_path):
    path = tmp_path / "classroom.sqlite3"
    initialize_demo(path)
    return path


def _draft(db_path, **overrides):
    suggested = get_classroom(db_path)["recommended_lesson"]
    values = {key: suggested[key] for key in ("title", "objective", "activities")}
    values.update(overrides)
    return save_lesson_draft(db_path, **values)


def test_fixture_counts_and_patterns_are_grounded_in_exact_student_answers(demo_db):
    classroom = get_classroom(demo_db)
    assert classroom["classroom"]["is_fictional"] is True
    assert classroom["summary"] == {
        "student_count": 8,
        "response_count": 24,
        "correct_count": 14,
        "accuracy_percent": 58.3,
        "needs_support_count": 6,
    }
    patterns = {pattern["id"]: pattern for pattern in classroom["patterns"]}
    denominators = patterns["adding_denominators"]
    assert denominators["student_count"] == 5
    assert denominators["response_count"] == 8
    assert denominators["student_names"] == ["Avery", "Jordan", "Theo", "Lena", "Sam"]
    assert {(e["question_id"], e["answer"]) for e in denominators["evidence"]} == {
        ("equal_parts", "2/8"),
        ("common_unit", "2/5"),
    }
    comparisons = patterns["numerator_only_comparison"]
    assert comparisons["student_names"] == ["Jordan", "Omar"]
    assert all(e["answer"] == "3/8" for e in comparisons["evidence"])
    assert classroom["recommended_lesson"]["target_student_ids"] == denominators["student_ids"]
    assert "5 of 8" in classroom["recommended_lesson"]["reason"]


def test_review_recomputes_evidence_instead_of_repeating_hardcoded_counts(demo_db):
    # Change two students' work; a truthful review must update both the counts
    # and the supporting example rows. 2/4 is equivalent to the right answer.
    with sqlite3.connect(demo_db) as con:
        con.execute("UPDATE demo_responses SET answer = '2/4' WHERE student_id = 'fictional_avery' AND question_id = 'equal_parts'")
        con.execute("UPDATE demo_responses SET answer = '5/6' WHERE student_id = 'fictional_avery' AND question_id = 'common_unit'")
    classroom = get_classroom(demo_db)
    denominators = next(p for p in classroom["patterns"] if p["id"] == "adding_denominators")
    assert classroom["summary"]["correct_count"] == 16
    assert denominators["student_count"] == 4
    assert denominators["response_count"] == 6
    assert "fictional_avery" not in denominators["student_ids"]
    assert "4 of 8" in classroom["recommended_lesson"]["reason"]
    avery = get_student_preview(demo_db, "fictional_avery")["student"]
    assert avery["correct_count"] == 3


def test_teacher_draft_requires_approval_and_edits_revoke_that_approval(demo_db):
    assert get_lesson(demo_db) is None
    first = _draft(demo_db, teacher_note="Use equal-length bars on the board.")
    assert first["status"] == "draft"
    assert first["version"] == 1
    assert get_student_preview(demo_db, "fictional_avery")["lesson"] is None

    approved = approve_lesson(demo_db, expected_version=first["version"])
    assert approved["status"] == "approved"
    assert approved["approved_at"]
    preview = get_student_preview(demo_db, "fictional_avery")
    assert preview["lesson"] == {key: value for key, value in approved.items() if key != "teacher_note"}
    assert "teacher_note" not in preview["lesson"]
    assert get_lesson(demo_db)["teacher_note"] == "Use equal-length bars on the board."

    edited = _draft(demo_db, title="Use quarter pieces first")
    assert edited["version"] == 2
    assert edited["status"] == "draft"
    assert edited["approved_at"] is None
    assert get_student_preview(demo_db, "fictional_avery")["lesson"] is None
    with pytest.raises(StaleLessonError, match="lesson changed"):
        approve_lesson(demo_db, expected_version=1)
    assert get_lesson(demo_db)["status"] == "draft"


def test_saved_teacher_work_survives_reinitialization_and_repeated_approval(demo_db):
    first = _draft(demo_db, title="Teacher's custom lesson", teacher_note="Pairs, then individual exit ticket.")
    approved = approve_lesson(demo_db, expected_version=first["version"])
    initialize_demo(demo_db)
    assert get_lesson(demo_db) == approved
    assert approve_lesson(demo_db, expected_version=first["version"]) == approved
    assert get_classroom(demo_db)["summary"]["response_count"] == 24


def test_invalid_drafts_and_unreviewed_approval_preserve_existing_state(demo_db):
    with pytest.raises(ValueError, match="Save and review"):
        approve_lesson(demo_db, expected_version=1)
    good = _draft(demo_db)
    for overrides in ({"title": " "}, {"objective": ""}, {"activities": []}, {"activities": [42]}, {"activities": "not a list"}):
        with pytest.raises(ValueError):
            _draft(demo_db, **overrides)
        assert get_lesson(demo_db) == good
    with pytest.raises(ValueError, match="integer"):
        approve_lesson(demo_db, expected_version=True)
    with pytest.raises(KeyError, match="Unknown fictional student"):
        get_student_preview(demo_db, "someone_else")


def test_no_hidden_default_path_or_implicit_database_creation(tmp_path):
    missing = tmp_path / "not_created.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        get_classroom(missing)
    assert not missing.exists()
    with pytest.raises(ValueError, match="explicit path"):
        initialize_demo("")
    with pytest.raises(ValueError, match="explicit path"):
        initialize_demo(":memory:")
    nested = tmp_path / "a folder" / "fractions # review.sqlite3"
    initialize_demo(nested)
    assert get_classroom(nested)["summary"]["student_count"] == 8


def test_unrecognized_incorrect_answers_are_not_misrepresented_as_known_patterns(demo_db):
    with sqlite3.connect(demo_db) as con:
        con.execute("UPDATE demo_responses SET answer = 'I do not know'")
    classroom = get_classroom(demo_db)
    assert classroom["summary"]["correct_count"] == 0
    assert all(pattern["student_count"] == 0 for pattern in classroom["patterns"])
    assert "No saved answer" in classroom["recommended_lesson"]["reason"]
    assert all(answer["pattern_id"] is None for student in classroom["students"] for answer in student["answers"])


def test_two_concurrent_saves_produce_distinct_versions(demo_db):
    _draft(demo_db)
    start = Barrier(3)

    def save(title):
        start.wait(timeout=5)
        return _draft(demo_db, title=title)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(save, "First teacher edit")
        second = workers.submit(save, "Second teacher edit")
        start.wait(timeout=5)
        versions = {first.result(timeout=10)["version"], second.result(timeout=10)["version"]}
    assert versions == {2, 3}
    assert get_lesson(demo_db)["version"] == 3
    assert get_lesson(demo_db)["status"] == "draft"


def test_concurrent_edit_cannot_approve_unreviewed_content(demo_db):
    reviewed = _draft(demo_db, title="The reviewed lesson")
    start = Barrier(3)

    def edit():
        start.wait(timeout=5)
        return _draft(demo_db, title="A new, unreviewed lesson")

    def approve():
        start.wait(timeout=5)
        try:
            return approve_lesson(demo_db, expected_version=reviewed["version"])
        except StaleLessonError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        edit_result = workers.submit(edit)
        approval_result = workers.submit(approve)
        start.wait(timeout=5)
        changed = edit_result.result(timeout=10)
        approved = approval_result.result(timeout=10)
    # Either the old version was approved before the edit, or approval rejected
    # the stale version after it. Neither ordering may approve the new content.
    if approved:
        assert approved["title"] == "The reviewed lesson"
        assert approved["version"] == reviewed["version"]
    assert changed["version"] == reviewed["version"] + 1
    assert get_lesson(demo_db)["title"] == "A new, unreviewed lesson"
    assert get_lesson(demo_db)["status"] == "draft"
    assert get_student_preview(demo_db, "fictional_avery")["lesson"] is None
