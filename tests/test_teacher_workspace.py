from __future__ import annotations

import duckdb

import forge_admin
import forge_assignments
import forge_scholar
import forge_teacher
import forge_teacher_dashboard


def _use_temp_scholar_db(monkeypatch, tmp_path):
    db_path = tmp_path / "teacher_workspace.duckdb"
    for module in (
        forge_scholar,
        forge_teacher,
        forge_assignments,
        forge_admin,
        forge_teacher_dashboard,
    ):
        monkeypatch.setattr(module, "SCHOLAR_DB", db_path)
    return db_path


def test_demo_workspace_populates_the_complete_teacher_story(monkeypatch, tmp_path):
    db_path = _use_temp_scholar_db(monkeypatch, tmp_path)

    teacher_id = forge_teacher_dashboard.seed_titans_forge_teacher_demo()
    snapshot = forge_teacher_dashboard.get_teacher_dashboard_snapshot(teacher_id)

    assert snapshot["students_total"] == 96
    assert len(snapshot["today_lessons"]) == 4
    assert len(snapshot["upcoming_lessons"]) == 8
    assert snapshot["draft_count"] == 4
    assert any(brief["subject"] == "Social Studies" for brief in snapshot["subject_briefs"])
    assert {action["kind"] for action in snapshot["actions"]} >= {
        "intervention",
        "assignment_review",
    }
    assert all(
        len(forge_teacher.list_class_students(cls["class_id"])) == 24
        for cls in snapshot["classes"]
    )

    con = duckdb.connect(str(db_path), read_only=True)
    expected_counts = {
        "assignments": 8,
        "student_submissions": 144,
        "submission_feedback": 96,
        "standards_coverage": 16,
        "intervention_plans": 8,
        "intervention_progress": 8,
        "class_communications": 8,
        "parent_reports": 8,
        "teacher_resources": 4,
        "student_evidence_events": 96,
        "school_classes_link": 4,
    }
    for table, expected in expected_counts.items():
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected
    con.close()

    school_classes = forge_admin.list_school_classes(
        forge_teacher_dashboard.DEMO_SCHOOL_ID
    )
    assert len(school_classes) == 4
    assert all("description" in cls for cls in school_classes)


def test_alert_sweeps_are_idempotent(monkeypatch, tmp_path):
    _use_temp_scholar_db(monkeypatch, tmp_path)
    teacher_id = forge_teacher_dashboard.seed_titans_forge_teacher_demo()

    assert forge_teacher.generate_alert_sweep(teacher_id) == 0
    assert forge_teacher.generate_alert_sweep(teacher_id) == 0
    assert len(forge_teacher.list_alerts(teacher_id)) == 8


def test_social_studies_standards_coverage_supports_exact_focus(monkeypatch, tmp_path):
    _use_temp_scholar_db(monkeypatch, tmp_path)
    teacher_id = forge_teacher_dashboard.seed_titans_forge_teacher_demo()
    social_studies = next(
        cls for cls in forge_teacher.list_classes(teacher_id)
        if cls["subject"] == "Social Studies"
    )

    standards = forge_teacher_dashboard.list_class_standards_coverage(
        social_studies["class_id"]
    )
    assert len(standards) == 4
    assert len({row["code"] for row in standards}) == 4
    assert all(
        set(row) == {
            "code", "description", "coverage_level", "lesson_count", "last_taught_ts"
        }
        for row in standards
    )
    assert [row["code"] for row in standards] == sorted(row["code"] for row in standards)

    focused = forge_teacher_dashboard.list_class_standards_coverage(
        social_studies["class_id"], standard_code=standards[1]["code"]
    )
    assert len(focused) == 1
    assert focused[0]["code"] == standards[1]["code"]

    assert forge_teacher_dashboard.list_class_standards_coverage(
        social_studies["class_id"], standard_code="UNKNOWN.STANDARD"
    ) == []


def test_action_and_ai_draft_lifecycle(monkeypatch, tmp_path):
    _use_temp_scholar_db(monkeypatch, tmp_path)
    forge_scholar.init_scholar_db()
    forge_teacher.init_teacher_db()

    first_id = forge_teacher.create_or_update_action(
        "teacher-1",
        "submission_review",
        "Review submissions",
        source_key="assignment:1",
    )
    second_id = forge_teacher.create_or_update_action(
        "teacher-1",
        "submission_review",
        "Review five submissions",
        source_key="assignment:1",
    )
    assert first_id == second_id
    assert len(forge_teacher.list_teacher_actions("teacher-1")) == 1

    forge_teacher.resolve_teacher_action(first_id)
    assert forge_teacher.list_teacher_actions("teacher-1") == []

    draft_id = forge_teacher.save_ai_artifact_draft(
        "teacher-1",
        "lesson",
        "Slope reteach",
        {"content": "Teacher-reviewed draft content"},
        source={"kind": "teacher_copilot"},
    )
    drafts = forge_teacher.list_ai_artifact_drafts("teacher-1")
    assert [draft["draft_id"] for draft in drafts] == [draft_id]
    assert drafts[0]["source"]["kind"] == "teacher_copilot"
