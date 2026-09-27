"""
forge_teacher.py — Titans Forge Scholar: Teacher Command Suite backend
=======================================================================

Teacher-side DuckDB schema, CRUD helpers, and prompt builders for the
8-page Teacher Command Suite. All data stored in scholar.duckdb (same file
as student data — different tables).

Tables
------
  teacher_profiles        Teacher identity, subjects taught, grade levels
  teacher_classes         Class definitions with standards alignment
  class_student_map       Many-to-many class ↔ student_id
  teacher_lesson_plans    Day-level lesson content (fully structured + differentiated)
  teacher_assessments     Quizzes/tests: questions + rubric + Bloom's coverage
  gradebook_entries       Per-student per-assessment scores + AI feedback
  parent_reports          Generated progress reports
  teacher_resources       Uploaded file texts + AI metadata
  class_communications    Parent/student communication log
  teacher_alerts          At-risk and action-required alerts

Architecture
------------
  forge_teacher.py → pure backend (schema, CRUD, prompt builders)
  pages/34–41      → Streamlit UI consuming this module
  Uses forge_scholar.SCHOLAR_DB for storage
  Reads scholar_students / scholar_mastery / scholar_quiz_results for analytics
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

# Re-use Scholar's DB path
from forge_scholar import SCHOLAR_DB, _rollback_quietly, SUBJECTS, EDU_LEVELS, EDU_LABELS

# ── Standards sets ─────────────────────────────────────────────────────────────
STANDARDS_SETS = [
    "Common Core (CCSS)",
    "Next Generation Science Standards (NGSS)",
    "College Board AP",
    "International Baccalaureate (IB)",
    "State Standards",
    "Custom / School-Defined",
]

BLOOM_LEVELS = [
    "Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"
]

QUESTION_TYPES = [
    "Multiple Choice", "Short Answer", "Essay", "True/False", "Matching", "Fill-in-the-Blank"
]

GRADING_SCALES = [
    "Letter (A–F)",
    "Percentage (0–100)",
    "Points",
    "Pass / Fail",
    "Mastery-Based (0–4)",
]

REPORT_TONES = ["Professional", "Warm", "Direct"]
REPORT_LANGUAGES = ["English", "Spanish", "French", "Portuguese", "Mandarin"]

# Page-facing aliases
REPORT_TONE_OPTIONS = REPORT_TONES
REPORT_LANG_OPTIONS = REPORT_LANGUAGES

ALERT_TYPES = [
    "mastery_drop",      # ≥3 topics below threshold for ≥7 days
    "inactive",          # no study session in ≥10 days
    "grade_drop",        # assessment score dropped >20% from prior
    "missing_work",      # assignment overdue >5 days
    "custom",            # teacher-created
]

# ── DB connection ──────────────────────────────────────────────────────────────
def _con() -> duckdb.DuckDBPyConnection:
    SCHOLAR_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(SCHOLAR_DB))


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def init_teacher_db() -> None:
    """Create all teacher tables (idempotent). Safe to call on every page load."""
    con = _con()
    try:
        # Teacher profiles
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_profiles (
                teacher_id      VARCHAR PRIMARY KEY,
                display_name    VARCHAR NOT NULL,
                subjects_json   TEXT DEFAULT '[]',
                grade_levels_json TEXT DEFAULT '[]',
                school          VARCHAR DEFAULT '',
                created_ts      TIMESTAMP DEFAULT NOW(),
                updated_ts      TIMESTAMP DEFAULT NOW()
            )
        """)

        # Classes
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_classes (
                class_id        VARCHAR PRIMARY KEY,
                teacher_id      VARCHAR NOT NULL,
                name            VARCHAR NOT NULL,
                subject         VARCHAR DEFAULT '',
                grade_level     VARCHAR DEFAULT '',
                term            VARCHAR DEFAULT '',
                school_year     VARCHAR DEFAULT '',
                standards_set   VARCHAR DEFAULT 'Common Core (CCSS)',
                grading_scale   VARCHAR DEFAULT 'Percentage (0–100)',
                mastery_threshold DOUBLE DEFAULT 0.7,
                notes           TEXT DEFAULT '',
                archived        BOOLEAN DEFAULT FALSE,
                created_ts      TIMESTAMP DEFAULT NOW()
            )
        """)

        # Class ↔ student mapping
        con.execute("""
            CREATE TABLE IF NOT EXISTS class_student_map (
                class_id            VARCHAR NOT NULL,
                student_id          VARCHAR NOT NULL,
                enrolled_ts         TIMESTAMP DEFAULT NOW(),
                accommodations      TEXT DEFAULT '',
                iep_notes           TEXT DEFAULT '',
                parent_contact      TEXT DEFAULT '',
                PRIMARY KEY (class_id, student_id)
            )
        """)

        # Lesson plans
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_lesson_plans (
                lesson_id           VARCHAR PRIMARY KEY,
                class_id            VARCHAR NOT NULL,
                teacher_id          VARCHAR NOT NULL,
                lesson_date         DATE NOT NULL,
                topic               VARCHAR NOT NULL,
                duration_min        INTEGER DEFAULT 50,
                hook                TEXT DEFAULT '',
                objectives_json     TEXT DEFAULT '[]',
                direct_instruction  TEXT DEFAULT '',
                guided_practice     TEXT DEFAULT '',
                independent_practice TEXT DEFAULT '',
                differentiated_json TEXT DEFAULT '{}',
                exit_ticket         TEXT DEFAULT '',
                standards_tags_json TEXT DEFAULT '[]',
                resource_ids_json   TEXT DEFAULT '[]',
                notes               TEXT DEFAULT '',
                ai_generated        BOOLEAN DEFAULT FALSE,
                created_ts          TIMESTAMP DEFAULT NOW(),
                updated_ts          TIMESTAMP DEFAULT NOW()
            )
        """)

        # Assessments (quiz/test/project definitions)
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_assessments (
                assessment_id       VARCHAR PRIMARY KEY,
                class_id            VARCHAR NOT NULL,
                teacher_id          VARCHAR NOT NULL,
                title               VARCHAR NOT NULL,
                assessment_type     VARCHAR DEFAULT 'quiz',
                topic               VARCHAR DEFAULT '',
                instructions        TEXT DEFAULT '',
                questions_json      TEXT DEFAULT '[]',
                rubric_json         TEXT DEFAULT '{}',
                bloom_coverage_json TEXT DEFAULT '{}',
                difficulty_dist_json TEXT DEFAULT '{}',
                standards_tags_json TEXT DEFAULT '[]',
                time_estimate_min   INTEGER DEFAULT 0,
                ai_generated        BOOLEAN DEFAULT FALSE,
                created_ts          TIMESTAMP DEFAULT NOW()
            )
        """)

        # Gradebook entries
        con.execute("""
            CREATE TABLE IF NOT EXISTS gradebook_entries (
                entry_id        VARCHAR PRIMARY KEY,
                assessment_id   VARCHAR NOT NULL,
                class_id        VARCHAR NOT NULL,
                student_id      VARCHAR NOT NULL,
                raw_response    TEXT DEFAULT '',
                score           DOUBLE,
                max_score       DOUBLE DEFAULT 100.0,
                pct             DOUBLE,
                feedback_json   TEXT DEFAULT '{}',
                overall_comment TEXT DEFAULT '',
                ai_graded       BOOLEAN DEFAULT FALSE,
                teacher_reviewed BOOLEAN DEFAULT FALSE,
                graded_ts       TIMESTAMP DEFAULT NOW()
            )
        """)

        # Parent/guardian progress reports
        con.execute("""
            CREATE TABLE IF NOT EXISTS parent_reports (
                report_id       VARCHAR PRIMARY KEY,
                student_id      VARCHAR NOT NULL,
                class_id        VARCHAR NOT NULL,
                period          VARCHAR NOT NULL,
                content         TEXT DEFAULT '',
                tone            VARCHAR DEFAULT 'Professional',
                language        VARCHAR DEFAULT 'English',
                status          VARCHAR DEFAULT 'draft',
                sent_ts         TIMESTAMP,
                created_ts      TIMESTAMP DEFAULT NOW()
            )
        """)

        # Resource library (uploaded files)
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_resources (
                resource_id     VARCHAR PRIMARY KEY,
                teacher_id      VARCHAR NOT NULL,
                filename        VARCHAR NOT NULL,
                file_type       VARCHAR DEFAULT '',
                extracted_text  TEXT DEFAULT '',
                ai_summary      TEXT DEFAULT '',
                vocab_json      TEXT DEFAULT '[]',
                discussion_qs_json TEXT DEFAULT '[]',
                tags_json       TEXT DEFAULT '[]',
                standards_tags_json TEXT DEFAULT '[]',
                grade_level     VARCHAR DEFAULT '',
                subject         VARCHAR DEFAULT '',
                file_size_kb    INTEGER DEFAULT 0,
                created_ts      TIMESTAMP DEFAULT NOW()
            )
        """)

        # Communication log
        con.execute("""
            CREATE TABLE IF NOT EXISTS class_communications (
                comm_id         VARCHAR PRIMARY KEY,
                teacher_id      VARCHAR NOT NULL,
                class_id        VARCHAR DEFAULT '',
                student_id      VARCHAR DEFAULT '',
                comm_type       VARCHAR DEFAULT 'note',
                subject_line    VARCHAR DEFAULT '',
                content         TEXT DEFAULT '',
                follow_up       TEXT DEFAULT '',
                ts              TIMESTAMP DEFAULT NOW()
            )
        """)

        # Alert system
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_alerts (
                alert_id        VARCHAR PRIMARY KEY,
                class_id        VARCHAR NOT NULL,
                student_id      VARCHAR NOT NULL,
                alert_type      VARCHAR NOT NULL,
                message         TEXT NOT NULL,
                severity        VARCHAR DEFAULT 'medium',
                data_json       TEXT DEFAULT '{}',
                acknowledged    BOOLEAN DEFAULT FALSE,
                created_ts      TIMESTAMP DEFAULT NOW()
            )
        """)

        # Durable teacher workflow primitives shared across dashboard pages.
        con.execute("""
            CREATE TABLE IF NOT EXISTS teacher_action_items (
                action_id       VARCHAR PRIMARY KEY,
                teacher_id      VARCHAR NOT NULL,
                class_id        VARCHAR DEFAULT '',
                student_id      VARCHAR DEFAULT '',
                action_type     VARCHAR NOT NULL,
                title           VARCHAR NOT NULL,
                detail          TEXT DEFAULT '',
                priority        VARCHAR DEFAULT 'normal',
                status          VARCHAR DEFAULT 'open',
                due_date        DATE,
                source_key      VARCHAR DEFAULT '',
                source_json     TEXT DEFAULT '{}',
                created_ts      TIMESTAMP DEFAULT NOW(),
                updated_ts      TIMESTAMP DEFAULT NOW(),
                resolved_ts     TIMESTAMP,
                UNIQUE(teacher_id, source_key)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS ai_artifact_drafts (
                draft_id        VARCHAR PRIMARY KEY,
                teacher_id      VARCHAR NOT NULL,
                class_id        VARCHAR DEFAULT '',
                artifact_type   VARCHAR NOT NULL,
                title           VARCHAR NOT NULL,
                payload_json    TEXT DEFAULT '{}',
                source_json     TEXT DEFAULT '{}',
                model_name      VARCHAR DEFAULT '',
                status          VARCHAR DEFAULT 'draft',
                destination_id  VARCHAR DEFAULT '',
                created_ts      TIMESTAMP DEFAULT NOW(),
                updated_ts      TIMESTAMP DEFAULT NOW(),
                approved_ts     TIMESTAMP
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS student_evidence_events (
                evidence_id     VARCHAR PRIMARY KEY,
                student_id      VARCHAR NOT NULL,
                class_id        VARCHAR NOT NULL,
                teacher_id      VARCHAR NOT NULL,
                topic           VARCHAR DEFAULT '',
                standard_code   VARCHAR DEFAULT '',
                source_type     VARCHAR NOT NULL,
                source_id       VARCHAR DEFAULT '',
                score           DOUBLE,
                max_score       DOUBLE DEFAULT 100.0,
                evidence_json   TEXT DEFAULT '{}',
                observed_ts     TIMESTAMP DEFAULT NOW()
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS standards_coverage (
                entry_id        VARCHAR PRIMARY KEY,
                class_id        VARCHAR NOT NULL,
                teacher_id      VARCHAR NOT NULL,
                standard_code   VARCHAR NOT NULL,
                standard_desc   TEXT DEFAULT '',
                lessons_count   INTEGER DEFAULT 0,
                last_taught_ts  TIMESTAMP,
                coverage_level  VARCHAR DEFAULT 'not_started',
                notes           TEXT DEFAULT '',
                created_ts      TIMESTAMP DEFAULT NOW(),
                UNIQUE(class_id, standard_code)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS intervention_plans (
                plan_id          VARCHAR PRIMARY KEY,
                student_id       VARCHAR NOT NULL,
                class_id         VARCHAR NOT NULL,
                teacher_id       VARCHAR NOT NULL,
                tier             INTEGER DEFAULT 2,
                concern_area     TEXT DEFAULT '',
                goals_json       TEXT DEFAULT '[]',
                strategies_json  TEXT DEFAULT '[]',
                resources_json   TEXT DEFAULT '[]',
                timeline_weeks   INTEGER DEFAULT 6,
                progress_target  TEXT DEFAULT '',
                ai_plan_text     TEXT DEFAULT '',
                status           VARCHAR DEFAULT 'active',
                created_ts       TIMESTAMP DEFAULT NOW(),
                updated_ts       TIMESTAMP DEFAULT NOW()
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS intervention_progress (
                entry_id         VARCHAR PRIMARY KEY,
                plan_id          VARCHAR NOT NULL,
                student_id       VARCHAR NOT NULL,
                week_num         INTEGER,
                mastery_snapshot TEXT DEFAULT '{}',
                teacher_notes    TEXT DEFAULT '',
                student_response TEXT DEFAULT '',
                status           VARCHAR DEFAULT 'on_track',
                logged_ts        TIMESTAMP DEFAULT NOW()
            )
        """)

        # Add page-contract columns when upgrading a database created by an
        # earlier workspace-v2 development build.
        for statement in [
            "ALTER TABLE intervention_plans ADD COLUMN IF NOT EXISTS goals_json TEXT DEFAULT '[]'",
            "ALTER TABLE intervention_plans ADD COLUMN IF NOT EXISTS resources_json TEXT DEFAULT '[]'",
            "ALTER TABLE intervention_plans ADD COLUMN IF NOT EXISTS progress_target TEXT DEFAULT ''",
            "ALTER TABLE intervention_plans ADD COLUMN IF NOT EXISTS ai_plan_text TEXT DEFAULT ''",
            "ALTER TABLE intervention_plans ADD COLUMN IF NOT EXISTS updated_ts TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE intervention_progress ADD COLUMN IF NOT EXISTS student_response TEXT DEFAULT ''",
        ]:
            con.execute(statement)

        con.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id    VARCHAR PRIMARY KEY,
                applied_ts      TIMESTAMP DEFAULT NOW(),
                notes           TEXT DEFAULT ''
            )
        """)
        con.execute("""
            INSERT OR IGNORE INTO schema_migrations (migration_id, notes)
            VALUES ('teacher_workspace_v2_foundation',
                    'Action queue, AI drafts, and standards evidence foundation')
        """)

        con.commit()
    except Exception:
        _rollback_quietly(con)
        raise
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEACHER PROFILES
# ══════════════════════════════════════════════════════════════════════════════

def create_teacher(display_name: str, subjects: list[str] | None = None,
                   grade_levels: list[str] | None = None,
                   school: str = "") -> str:
    tid = f"tchr_{uuid.uuid4().hex[:12]}"
    con = _con()
    con.execute("""
        INSERT INTO teacher_profiles
            (teacher_id, display_name, subjects_json, grade_levels_json, school)
        VALUES (?,?,?,?,?)
    """, [tid, display_name,
          json.dumps(subjects or []), json.dumps(grade_levels or []), school])
    con.close()
    return tid


def list_teachers() -> list[dict]:
    con = _con()
    rows = con.execute(
        "SELECT teacher_id, display_name, subjects_json, grade_levels_json, school "
        "FROM teacher_profiles ORDER BY display_name"
    ).fetchall()
    con.close()
    return [
        {"teacher_id": r[0], "display_name": r[1],
         "subjects": json.loads(r[2] or "[]"),
         "grade_levels": json.loads(r[3] or "[]"),
         "school": r[4] or ""}
        for r in rows
    ]


def get_teacher(teacher_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT teacher_id, display_name, subjects_json, grade_levels_json, school "
        "FROM teacher_profiles WHERE teacher_id=?", [teacher_id]
    ).fetchone()
    con.close()
    if not row:
        return None
    return {"teacher_id": row[0], "display_name": row[1],
            "subjects": json.loads(row[2] or "[]"),
            "grade_levels": json.loads(row[3] or "[]"),
            "school": row[4] or ""}


# ══════════════════════════════════════════════════════════════════════════════
# CLASSES
# ══════════════════════════════════════════════════════════════════════════════

def create_class(teacher_id: str, name: str, subject: str = "",
                 grade_level: str = "", term: str = "", school_year: str = "",
                 standards_set: str = "Common Core (CCSS)",
                 grading_scale: str = "Percentage (0–100)",
                 mastery_threshold: float = 0.70,
                 notes: str = "") -> str:
    cid = f"cls_{uuid.uuid4().hex[:12]}"
    con = _con()
    con.execute("""
        INSERT INTO teacher_classes
            (class_id, teacher_id, name, subject, grade_level, term,
             school_year, standards_set, grading_scale, mastery_threshold, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [cid, teacher_id, name, subject, grade_level, term,
          school_year, standards_set, grading_scale, mastery_threshold, notes])
    con.close()
    return cid


def list_classes(teacher_id: str, include_archived: bool = False) -> list[dict]:
    con = _con()
    q = """SELECT class_id, teacher_id, name, subject, grade_level, term,
                  school_year, standards_set, grading_scale, mastery_threshold,
                  notes, archived, created_ts
           FROM teacher_classes WHERE teacher_id=?"""
    params: list[Any] = [teacher_id]
    if not include_archived:
        q += " AND archived=FALSE"
    q += " ORDER BY created_ts DESC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [_class_row_to_dict(r) for r in rows]


def _class_row_to_dict(r: tuple) -> dict:
    return {
        "class_id": r[0], "teacher_id": r[1], "name": r[2],
        "subject": r[3], "grade_level": r[4], "term": r[5],
        "school_year": r[6], "standards_set": r[7], "grading_scale": r[8],
        "mastery_threshold": r[9], "notes": r[10],
        "archived": r[11], "created_ts": str(r[12])[:16],
    }


def get_class(class_id: str) -> dict | None:
    con = _con()
    row = con.execute("""
        SELECT class_id, teacher_id, name, subject, grade_level, term,
               school_year, standards_set, grading_scale, mastery_threshold,
               notes, archived, created_ts
        FROM teacher_classes WHERE class_id=?
    """, [class_id]).fetchone()
    con.close()
    return _class_row_to_dict(row) if row else None


def update_class(class_id: str, **kwargs: Any) -> None:
    allowed = {"name", "subject", "grade_level", "term", "school_year",
               "standards_set", "grading_scale", "mastery_threshold", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [class_id]
    con = _con()
    con.execute(f"UPDATE teacher_classes SET {set_clause} WHERE class_id=?", vals)
    con.close()


def archive_class(class_id: str) -> None:
    con = _con()
    con.execute("UPDATE teacher_classes SET archived=TRUE WHERE class_id=?", [class_id])
    con.close()


def delete_class(class_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM teacher_classes WHERE class_id=?", [class_id])
    con.execute("DELETE FROM class_student_map WHERE class_id=?", [class_id])
    con.execute("DELETE FROM teacher_lesson_plans WHERE class_id=?", [class_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# CLASS ↔ STUDENT ENROLLMENT
# ══════════════════════════════════════════════════════════════════════════════

def enroll_student(class_id: str, student_id: str,
                   accommodations: str = "", iep_notes: str = "",
                   parent_contact: str = "") -> None:
    con = _con()
    con.execute("""
        INSERT OR REPLACE INTO class_student_map
            (class_id, student_id, accommodations, iep_notes, parent_contact)
        VALUES (?,?,?,?,?)
    """, [class_id, student_id, accommodations, iep_notes, parent_contact])
    con.close()


def unenroll_student(class_id: str, student_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM class_student_map WHERE class_id=? AND student_id=?",
                [class_id, student_id])
    con.close()


def list_class_students(class_id: str) -> list[dict]:
    """Return enrolled students with their scholar_students profile data."""
    con = _con()
    rows = con.execute("""
        SELECT m.student_id, m.accommodations, m.iep_notes, m.parent_contact,
               m.enrolled_ts,
               s.display_name, s.edu_level, s.grade_year, s.goals_json
        FROM class_student_map m
        LEFT JOIN scholar_students s ON m.student_id = s.student_id
        WHERE m.class_id=?
        ORDER BY s.display_name
    """, [class_id]).fetchall()
    con.close()
    return [
        {
            "student_id": r[0], "accommodations": r[1], "iep_notes": r[2],
            "parent_contact": r[3], "enrolled_ts": str(r[4])[:10],
            "display_name": r[5] or r[0], "edu_level": r[6] or "",
            "grade_year": r[7] or "",
            "goals": json.loads(r[8] or "[]"),
        }
        for r in rows
    ]


def update_student_enrollment(class_id: str, student_id: str, **kwargs: Any) -> None:
    allowed = {"accommodations", "iep_notes", "parent_contact"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [class_id, student_id]
    con = _con()
    con.execute(
        f"UPDATE class_student_map SET {set_clause} "
        f"WHERE class_id=? AND student_id=?", vals
    )
    con.close()


def get_student_classes(student_id: str) -> list[dict]:
    """Return all classes a student is enrolled in."""
    con = _con()
    rows = con.execute("""
        SELECT c.class_id, c.name, c.subject, c.grade_level, c.term
        FROM teacher_classes c
        JOIN class_student_map m ON c.class_id=m.class_id
        WHERE m.student_id=? AND c.archived=FALSE
        ORDER BY c.name
    """, [student_id]).fetchall()
    con.close()
    return [{"class_id": r[0], "name": r[1], "subject": r[2],
             "grade_level": r[3], "term": r[4]} for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# LESSON PLANS
# ══════════════════════════════════════════════════════════════════════════════

def create_lesson_plan(class_id: str, teacher_id: str,
                       lesson_date: date, topic: str,
                       duration_min: int = 50, **content: Any) -> str:
    lid = f"lsn_{uuid.uuid4().hex[:12]}"
    con = _con()
    con.execute("""
        INSERT INTO teacher_lesson_plans
            (lesson_id, class_id, teacher_id, lesson_date, topic, duration_min,
             hook, objectives_json, direct_instruction, guided_practice,
             independent_practice, differentiated_json, exit_ticket,
             standards_tags_json, resource_ids_json, notes, ai_generated)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        lid, class_id, teacher_id, lesson_date, topic, duration_min,
        content.get("hook", ""),
        json.dumps(content.get("objectives", [])),
        content.get("direct_instruction", ""),
        content.get("guided_practice", ""),
        content.get("independent_practice", ""),
        json.dumps(content.get("differentiated", {})),
        content.get("exit_ticket", ""),
        json.dumps(content.get("standards_tags", [])),
        json.dumps(content.get("resource_ids", [])),
        content.get("notes", ""),
        content.get("ai_generated", False),
    ])
    con.close()
    return lid


def get_lesson(lesson_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT * FROM teacher_lesson_plans WHERE lesson_id=?", [lesson_id]
    ).fetchone()
    con.close()
    return _lesson_row_to_dict(row) if row else None


def list_lessons(class_id: str, start_date: date | None = None,
                 end_date: date | None = None) -> list[dict]:
    con = _con()
    q = "SELECT * FROM teacher_lesson_plans WHERE class_id=?"
    params: list[Any] = [class_id]
    if start_date:
        q += " AND lesson_date >= ?"
        params.append(start_date)
    if end_date:
        q += " AND lesson_date <= ?"
        params.append(end_date)
    q += " ORDER BY lesson_date ASC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [_lesson_row_to_dict(r) for r in rows]


def list_lessons_for_teacher(teacher_id: str, start_date: date | None = None,
                              end_date: date | None = None) -> list[dict]:
    con = _con()
    q = "SELECT * FROM teacher_lesson_plans WHERE teacher_id=?"
    params: list[Any] = [teacher_id]
    if start_date:
        q += " AND lesson_date >= ?"
        params.append(start_date)
    if end_date:
        q += " AND lesson_date <= ?"
        params.append(end_date)
    q += " ORDER BY lesson_date ASC, class_id ASC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [_lesson_row_to_dict(r) for r in rows]


def _lesson_row_to_dict(r: tuple) -> dict:
    return {
        "lesson_id": r[0], "class_id": r[1], "teacher_id": r[2],
        "lesson_date": str(r[3]),
        "topic": r[4], "duration_min": r[5],
        "hook": r[6] or "",
        "objectives": json.loads(r[7] or "[]"),
        "direct_instruction": r[8] or "",
        "guided_practice": r[9] or "",
        "independent_practice": r[10] or "",
        "differentiated": json.loads(r[11] or "{}"),
        "exit_ticket": r[12] or "",
        "standards_tags": json.loads(r[13] or "[]"),
        "resource_ids": json.loads(r[14] or "[]"),
        "notes": r[15] or "",
        "ai_generated": bool(r[16]),
        "created_ts": str(r[17])[:16],
        "updated_ts": str(r[18])[:16],
    }


def update_lesson(lesson_id: str, **kwargs: Any) -> None:
    allowed = {
        "topic", "duration_min", "hook", "objectives_json",
        "direct_instruction", "guided_practice", "independent_practice",
        "differentiated_json", "exit_ticket", "standards_tags_json",
        "notes", "resource_ids_json",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_ts"] = datetime.now()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [lesson_id]
    con = _con()
    con.execute(
        f"UPDATE teacher_lesson_plans SET {set_clause} WHERE lesson_id=?", vals
    )
    con.close()


def delete_lesson(lesson_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM teacher_lesson_plans WHERE lesson_id=?", [lesson_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# ASSESSMENTS
# ══════════════════════════════════════════════════════════════════════════════

def create_assessment(class_id: str, teacher_id: str, title: str,
                      assessment_type: str = "quiz", topic: str = "",
                      instructions: str = "",
                      questions: list[dict] | None = None,
                      rubric: dict | None = None,
                      bloom_coverage: dict | None = None,
                      difficulty_dist: dict | None = None,
                      standards_tags: list[str] | None = None,
                      time_estimate_min: int = 0,
                      ai_generated: bool = False) -> str:
    aid = f"asgmt_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO teacher_assessments
            (assessment_id, class_id, teacher_id, title, assessment_type, topic,
             instructions, questions_json, rubric_json, bloom_coverage_json,
             difficulty_dist_json, standards_tags_json, time_estimate_min, ai_generated)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        aid, class_id, teacher_id, title, assessment_type, topic,
        instructions,
        json.dumps(questions or []),
        json.dumps(rubric or {}),
        json.dumps(bloom_coverage or {}),
        json.dumps(difficulty_dist or {}),
        json.dumps(standards_tags or []),
        time_estimate_min, ai_generated,
    ])
    con.close()
    return aid


def list_assessments(class_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT assessment_id, class_id, teacher_id, title, assessment_type,
               topic, time_estimate_min, ai_generated, created_ts
        FROM teacher_assessments WHERE class_id=? ORDER BY created_ts DESC
    """, [class_id]).fetchall()
    con.close()
    return [
        {"assessment_id": r[0], "class_id": r[1], "teacher_id": r[2],
         "title": r[3], "assessment_type": r[4], "topic": r[5],
         "time_estimate_min": r[6], "ai_generated": bool(r[7]),
         "created_ts": str(r[8])[:16]}
        for r in rows
    ]


def get_assessment(assessment_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT * FROM teacher_assessments WHERE assessment_id=?", [assessment_id]
    ).fetchone()
    con.close()
    if not row:
        return None
    return {
        "assessment_id": row[0], "class_id": row[1], "teacher_id": row[2],
        "title": row[3], "assessment_type": row[4], "topic": row[5],
        "instructions": row[6],
        "questions": json.loads(row[7] or "[]"),
        "rubric": json.loads(row[8] or "{}"),
        "bloom_coverage": json.loads(row[9] or "{}"),
        "difficulty_dist": json.loads(row[10] or "{}"),
        "standards_tags": json.loads(row[11] or "[]"),
        "time_estimate_min": row[12], "ai_generated": bool(row[13]),
        "created_ts": str(row[14])[:16],
    }


def all_assessments_for_teacher(teacher_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT assessment_id, class_id, title, assessment_type, topic, created_ts
        FROM teacher_assessments WHERE teacher_id=? ORDER BY created_ts DESC
    """, [teacher_id]).fetchall()
    con.close()
    return [{"assessment_id": r[0], "class_id": r[1], "title": r[2],
             "assessment_type": r[3], "topic": r[4],
             "created_ts": str(r[5])[:16]} for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# GRADEBOOK
# ══════════════════════════════════════════════════════════════════════════════

def save_grade(assessment_id: str, class_id: str, student_id: str,
               score: float, max_score: float = 100.0,
               feedback: dict | None = None,
               overall_comment: str = "",
               raw_response: str = "",
               ai_graded: bool = False,
               teacher_reviewed: bool = False) -> str:
    eid = f"grd_{uuid.uuid4().hex[:10]}"
    pct = round(score / max_score * 100, 1) if max_score else 0.0
    con = _con()
    con.execute("""
        INSERT OR REPLACE INTO gradebook_entries
            (entry_id, assessment_id, class_id, student_id, raw_response,
             score, max_score, pct, feedback_json, overall_comment,
             ai_graded, teacher_reviewed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [eid, assessment_id, class_id, student_id, raw_response,
          score, max_score, pct, json.dumps(feedback or {}),
          overall_comment, ai_graded, teacher_reviewed])
    con.close()
    return eid


def get_gradebook(class_id: str, assessment_id: str | None = None) -> list[dict]:
    con = _con()
    q = "SELECT * FROM gradebook_entries WHERE class_id=?"
    params: list[Any] = [class_id]
    if assessment_id:
        q += " AND assessment_id=?"
        params.append(assessment_id)
    q += " ORDER BY student_id, graded_ts DESC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [
        {"entry_id": r[0], "assessment_id": r[1], "class_id": r[2],
         "student_id": r[3], "raw_response": r[4],
         "score": r[5], "max_score": r[6], "pct": r[7],
         "feedback": json.loads(r[8] or "{}"),
         "overall_comment": r[9],
         "ai_graded": bool(r[10]), "teacher_reviewed": bool(r[11]),
         "graded_ts": str(r[12])[:16]}
        for r in rows
    ]


def update_grade(entry_id: str, score: float | None = None,
                 overall_comment: str | None = None,
                 teacher_reviewed: bool | None = None) -> None:
    con = _con()
    if score is not None:
        con.execute("UPDATE gradebook_entries SET score=? WHERE entry_id=?",
                    [score, entry_id])
    if overall_comment is not None:
        con.execute("UPDATE gradebook_entries SET overall_comment=? WHERE entry_id=?",
                    [overall_comment, entry_id])
    if teacher_reviewed is not None:
        con.execute("UPDATE gradebook_entries SET teacher_reviewed=? WHERE entry_id=?",
                    [teacher_reviewed, entry_id])
    con.close()


def class_grade_summary(class_id: str) -> list[dict]:
    """Per-student average score across all assessments in a class."""
    con = _con()
    rows = con.execute("""
        SELECT student_id, COUNT(*) as count, AVG(pct) as avg_pct,
               MIN(pct) as min_pct, MAX(pct) as max_pct
        FROM gradebook_entries WHERE class_id=?
        GROUP BY student_id
        ORDER BY avg_pct DESC
    """, [class_id]).fetchall()
    con.close()
    return [{"student_id": r[0], "count": r[1],
             "avg_pct": round(r[2] or 0, 1),
             "min_pct": round(r[3] or 0, 1),
             "max_pct": round(r[4] or 0, 1)} for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# PARENT REPORTS
# ══════════════════════════════════════════════════════════════════════════════

def save_parent_report(student_id: str, class_id: str, period: str,
                       content: str, tone: str = "Professional",
                       language: str = "English",
                       status: str = "draft") -> str:
    rid = f"rpt_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO parent_reports
            (report_id, student_id, class_id, period, content, tone, language, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, [rid, student_id, class_id, period, content, tone, language, status])
    con.close()
    return rid


def list_parent_reports(class_id: str, period: str | None = None) -> list[dict]:
    con = _con()
    q = "SELECT report_id, student_id, class_id, period, tone, language, status, created_ts FROM parent_reports WHERE class_id=?"
    params: list[Any] = [class_id]
    if period:
        q += " AND period=?"
        params.append(period)
    q += " ORDER BY created_ts DESC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [{"report_id": r[0], "student_id": r[1], "class_id": r[2],
             "period": r[3], "tone": r[4], "language": r[5],
             "status": r[6], "created_ts": str(r[7])[:16]} for r in rows]


def get_parent_report(report_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT * FROM parent_reports WHERE report_id=?", [report_id]
    ).fetchone()
    con.close()
    if not row:
        return None
    return {"report_id": row[0], "student_id": row[1], "class_id": row[2],
            "period": row[3], "content": row[4], "tone": row[5],
            "language": row[6], "status": row[7],
            "sent_ts": str(row[8]) if row[8] else None,
            "created_ts": str(row[9])[:16]}


def update_report_status(report_id: str, status: str) -> None:
    con = _con()
    params: list[Any] = [status, report_id]
    if status == "sent":
        con.execute(
            "UPDATE parent_reports SET status=?, sent_ts=NOW() WHERE report_id=?",
            params
        )
    else:
        con.execute(
            "UPDATE parent_reports SET status=? WHERE report_id=?", params
        )
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# RESOURCE LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

def save_resource(teacher_id: str, filename: str, file_type: str,
                  extracted_text: str,
                  ai_summary: str = "",
                  vocab: list[str] | None = None,
                  discussion_qs: list[str] | None = None,
                  tags: list[str] | None = None,
                  standards_tags: list[str] | None = None,
                  grade_level: str = "",
                  subject: str = "",
                  file_size_kb: int = 0) -> str:
    rid = f"res_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO teacher_resources
            (resource_id, teacher_id, filename, file_type, extracted_text,
             ai_summary, vocab_json, discussion_qs_json, tags_json,
             standards_tags_json, grade_level, subject, file_size_kb)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [rid, teacher_id, filename, file_type, extracted_text[:50_000],
          ai_summary, json.dumps(vocab or []),
          json.dumps(discussion_qs or []),
          json.dumps(tags or []),
          json.dumps(standards_tags or []),
          grade_level, subject, file_size_kb])
    con.close()
    return rid


def search_resources(teacher_id: str, query: str = "",
                     subject: str = "", grade_level: str = "") -> list[dict]:
    con = _con()
    q = """SELECT resource_id, filename, file_type, ai_summary, tags_json,
                  standards_tags_json, grade_level, subject, file_size_kb, created_ts
           FROM teacher_resources WHERE teacher_id=?"""
    params: list[Any] = [teacher_id]
    if subject:
        q += " AND subject=?"
        params.append(subject)
    if grade_level:
        q += " AND grade_level=?"
        params.append(grade_level)
    q += " ORDER BY created_ts DESC"
    rows = con.execute(q, params).fetchall()
    con.close()

    results = [
        {"resource_id": r[0], "filename": r[1], "file_type": r[2],
         "ai_summary": r[3] or "", "tags": json.loads(r[4] or "[]"),
         "standards_tags": json.loads(r[5] or "[]"),
         "grade_level": r[6], "subject": r[7],
         "file_size_kb": r[8], "created_ts": str(r[9])[:16]}
        for r in rows
    ]

    if query:
        ql = query.lower()
        results = [
            r for r in results
            if ql in r["filename"].lower()
            or ql in r["ai_summary"].lower()
            or any(ql in t.lower() for t in r["tags"])
        ]
    return results


def get_resource_text(resource_id: str) -> str:
    con = _con()
    row = con.execute(
        "SELECT extracted_text FROM teacher_resources WHERE resource_id=?",
        [resource_id]
    ).fetchone()
    con.close()
    return row[0] if row else ""


def delete_resource(resource_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM teacher_resources WHERE resource_id=?", [resource_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def log_communication(teacher_id: str, comm_type: str, content: str,
                      class_id: str = "", student_id: str = "",
                      subject_line: str = "", follow_up: str = "") -> str:
    cid = f"comm_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO class_communications
            (comm_id, teacher_id, class_id, student_id, comm_type,
             subject_line, content, follow_up)
        VALUES (?,?,?,?,?,?,?,?)
    """, [cid, teacher_id, class_id, student_id, comm_type,
          subject_line, content, follow_up])
    con.close()
    return cid


def list_communications(teacher_id: str, student_id: str | None = None,
                        class_id: str | None = None,
                        comm_type: str | None = None,
                        limit: int = 50) -> list[dict]:
    con = _con()
    q = "SELECT * FROM class_communications WHERE teacher_id=?"
    params: list[Any] = [teacher_id]
    if student_id:
        q += " AND student_id=?"
        params.append(student_id)
    if class_id:
        q += " AND class_id=?"
        params.append(class_id)
    if comm_type:
        q += " AND comm_type=?"
        params.append(comm_type)
    q += f" ORDER BY ts DESC LIMIT {int(limit)}"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [
        {"comm_id": r[0], "teacher_id": r[1], "class_id": r[2],
         "student_id": r[3], "comm_type": r[4], "subject_line": r[5],
         "content": r[6], "followup": r[7], "ts": str(r[8])[:16]}
        for r in rows
    ]


def save_communication(teacher_id: str, class_id: str, student_id: str,
                       comm_type: str, content: str, followup: str = "") -> str:
    """Convenience alias for log_communication with standardised parameter names."""
    return log_communication(
        teacher_id=teacher_id, comm_type=comm_type, content=content,
        class_id=class_id, student_id=student_id, follow_up=followup,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ALERTS
# ══════════════════════════════════════════════════════════════════════════════

def _upsert_alert(class_id: str, student_id: str, alert_type: str,
                  message: str, severity: str = "medium",
                  data: dict | None = None) -> tuple[str, bool]:
    """Create one open alert per class/student/type, refreshing it on repeat sweeps."""
    con = _con()
    existing = con.execute(
        """
        SELECT alert_id FROM teacher_alerts
        WHERE class_id=? AND student_id=? AND alert_type=? AND acknowledged=FALSE
        ORDER BY created_ts DESC LIMIT 1
        """,
        [class_id, student_id, alert_type],
    ).fetchone()
    if existing:
        con.execute(
            """
            UPDATE teacher_alerts
            SET message=?, severity=?, data_json=?, created_ts=NOW()
            WHERE alert_id=?
            """,
            [message, severity, json.dumps(data or {}), existing[0]],
        )
        con.close()
        return str(existing[0]), False

    aid = f"alrt_{uuid.uuid4().hex[:10]}"
    con.execute("""
        INSERT INTO teacher_alerts
            (alert_id, class_id, student_id, alert_type, message, severity, data_json)
        VALUES (?,?,?,?,?,?,?)
    """, [aid, class_id, student_id, alert_type, message, severity,
          json.dumps(data or {})])
    con.close()
    return aid, True


def create_alert(class_id: str, student_id: str, alert_type: str,
                 message: str, severity: str = "medium",
                 data: dict | None = None) -> str:
    alert_id, _ = _upsert_alert(
        class_id, student_id, alert_type, message, severity, data
    )
    return alert_id


def list_alerts(teacher_id: str, class_id: str | None = None,
                acknowledged: bool = False,
                include_acknowledged: bool = False) -> list[dict]:
    # include_acknowledged=True overrides the acknowledged filter
    ack_filter = acknowledged if not include_acknowledged else True
    con = _con()
    q = """
        SELECT a.alert_id, a.class_id, a.student_id, a.alert_type,
               a.message, a.severity, a.data_json, a.acknowledged, a.created_ts,
               c.name as class_name, s.display_name as student_name
        FROM teacher_alerts a
        LEFT JOIN teacher_classes c ON a.class_id = c.class_id
        LEFT JOIN scholar_students s ON a.student_id = s.student_id
        WHERE c.teacher_id=?
    """
    params: list[Any] = [teacher_id]
    if not include_acknowledged:
        q += " AND a.acknowledged=?"
        params.append(ack_filter)
    if class_id:
        q += " AND a.class_id=?"
        params.append(class_id)
    q += " ORDER BY a.severity DESC, a.created_ts DESC"
    rows = con.execute(q, params).fetchall()
    con.close()
    return [
        {"alert_id": r[0], "class_id": r[1], "student_id": r[2],
         "alert_type": r[3], "message": r[4], "severity": r[5],
         "data": json.loads(r[6] or "{}"), "acknowledged": bool(r[7]),
         "ts": str(r[8])[:16], "created_ts": str(r[8])[:16],
         "class_name": r[9] or r[1],
         "student_name": r[10] or r[2]}
        for r in rows
    ]


def acknowledge_alert(alert_id: str) -> None:
    con = _con()
    con.execute("UPDATE teacher_alerts SET acknowledged=TRUE WHERE alert_id=?",
                [alert_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEACHER WORKFLOW ACTIONS, AI DRAFTS, AND EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════

def create_or_update_action(
    teacher_id: str,
    action_type: str,
    title: str,
    detail: str = "",
    priority: str = "normal",
    class_id: str = "",
    student_id: str = "",
    source_key: str = "",
    source: dict | None = None,
    due_date: date | None = None,
) -> str:
    stable_key = source_key or f"manual:{uuid.uuid4().hex[:12]}"
    con = _con()
    existing = con.execute(
        "SELECT action_id FROM teacher_action_items WHERE teacher_id=? AND source_key=?",
        [teacher_id, stable_key],
    ).fetchone()
    if existing:
        con.execute(
            """
            UPDATE teacher_action_items
            SET class_id=?, student_id=?, action_type=?, title=?, detail=?,
                priority=?, status='open', due_date=?, source_json=?,
                updated_ts=NOW(), resolved_ts=NULL
            WHERE action_id=?
            """,
            [class_id, student_id, action_type, title, detail, priority,
             due_date, json.dumps(source or {}), existing[0]],
        )
        action_id = str(existing[0])
    else:
        action_id = f"act_{uuid.uuid4().hex[:12]}"
        con.execute(
            """
            INSERT INTO teacher_action_items
                (action_id, teacher_id, class_id, student_id, action_type,
                 title, detail, priority, status, due_date, source_key, source_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            [action_id, teacher_id, class_id, student_id, action_type,
             title, detail, priority, due_date, stable_key,
             json.dumps(source or {})],
        )
    con.close()
    return action_id


def list_teacher_actions(teacher_id: str, status: str = "open",
                         limit: int = 50) -> list[dict]:
    con = _con()
    rows = con.execute(
        """
        SELECT action_id, teacher_id, class_id, student_id, action_type,
               title, detail, priority, status, due_date, source_key,
               source_json, created_ts, updated_ts, resolved_ts
        FROM teacher_action_items
        WHERE teacher_id=? AND status=?
        ORDER BY
            CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                          WHEN 'normal' THEN 2 ELSE 3 END,
            due_date ASC NULLS LAST, updated_ts DESC
        LIMIT ?
        """,
        [teacher_id, status, int(limit)],
    ).fetchall()
    con.close()
    return [
        {
            "action_id": r[0], "teacher_id": r[1], "class_id": r[2] or "",
            "student_id": r[3] or "", "action_type": r[4], "title": r[5],
            "detail": r[6] or "", "priority": r[7], "status": r[8],
            "due_date": str(r[9]) if r[9] else "", "source_key": r[10],
            "source": json.loads(r[11] or "{}"),
            "created_ts": str(r[12])[:16], "updated_ts": str(r[13])[:16],
            "resolved_ts": str(r[14])[:16] if r[14] else "",
        }
        for r in rows
    ]


def resolve_teacher_action(action_id: str) -> None:
    con = _con()
    con.execute(
        """
        UPDATE teacher_action_items
        SET status='resolved', resolved_ts=NOW(), updated_ts=NOW()
        WHERE action_id=?
        """,
        [action_id],
    )
    con.close()


def save_ai_artifact_draft(
    teacher_id: str,
    artifact_type: str,
    title: str,
    payload: dict,
    class_id: str = "",
    source: dict | None = None,
    model_name: str = "",
) -> str:
    draft_id = f"draft_{uuid.uuid4().hex[:12]}"
    con = _con()
    con.execute(
        """
        INSERT INTO ai_artifact_drafts
            (draft_id, teacher_id, class_id, artifact_type, title,
             payload_json, source_json, model_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [draft_id, teacher_id, class_id, artifact_type, title,
         json.dumps(payload), json.dumps(source or {}), model_name],
    )
    con.close()
    return draft_id


def list_ai_artifact_drafts(teacher_id: str, status: str = "draft",
                            limit: int = 30) -> list[dict]:
    con = _con()
    rows = con.execute(
        """
        SELECT draft_id, teacher_id, class_id, artifact_type, title,
               payload_json, source_json, model_name, status,
               destination_id, created_ts, updated_ts, approved_ts
        FROM ai_artifact_drafts
        WHERE teacher_id=? AND status=?
        ORDER BY updated_ts DESC LIMIT ?
        """,
        [teacher_id, status, int(limit)],
    ).fetchall()
    con.close()
    return [
        {
            "draft_id": r[0], "teacher_id": r[1], "class_id": r[2] or "",
            "artifact_type": r[3], "title": r[4],
            "payload": json.loads(r[5] or "{}"),
            "source": json.loads(r[6] or "{}"), "model_name": r[7] or "",
            "status": r[8], "destination_id": r[9] or "",
            "created_ts": str(r[10])[:16], "updated_ts": str(r[11])[:16],
            "approved_ts": str(r[12])[:16] if r[12] else "",
        }
        for r in rows
    ]


def record_evidence_event(
    student_id: str,
    class_id: str,
    teacher_id: str,
    source_type: str,
    score: float,
    max_score: float = 100.0,
    topic: str = "",
    standard_code: str = "",
    source_id: str = "",
    evidence: dict | None = None,
) -> str:
    evidence_id = f"evd_{uuid.uuid4().hex[:12]}"
    con = _con()
    con.execute(
        """
        INSERT INTO student_evidence_events
            (evidence_id, student_id, class_id, teacher_id, topic,
             standard_code, source_type, source_id, score, max_score,
             evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [evidence_id, student_id, class_id, teacher_id, topic,
         standard_code, source_type, source_id, score, max_score,
         json.dumps(evidence or {})],
    )
    con.close()
    return evidence_id


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS HELPERS (read scholar tables)
# ══════════════════════════════════════════════════════════════════════════════

def class_mastery_heatmap(class_id: str,
                          top_n_topics: int = 15) -> list[dict]:
    """
    Return mastery data per student × topic for a class.
    Returns list of {student_id, display_name, topic, avg_score, count}.
    """
    enrolled = list_class_students(class_id)
    if not enrolled:
        return []
    student_ids = [s["student_id"] for s in enrolled]
    name_map = {s["student_id"]: s["display_name"] for s in enrolled}

    placeholders = ",".join("?" * len(student_ids))
    con = _con()
    rows = con.execute(f"""
        SELECT student_id, topic, AVG(score) as avg_score, COUNT(*) as cnt
        FROM scholar_mastery
        WHERE student_id IN ({placeholders})
        GROUP BY student_id, topic
        ORDER BY cnt DESC
    """, student_ids).fetchall()
    con.close()

    # Find top topics across all students
    topic_counts: dict[str, int] = {}
    for r in rows:
        topic_counts[r[1]] = topic_counts.get(r[1], 0) + int(r[3])
    top_topics = sorted(topic_counts, key=lambda t: topic_counts[t], reverse=True)[:top_n_topics]

    return [
        {"student_id": r[0],
         "display_name": name_map.get(r[0], r[0]),
         "topic": r[1],
         "avg_score": round(float(r[2]), 3),
         "count": int(r[3])}
        for r in rows if r[1] in top_topics
    ]


def at_risk_students(class_id: str, mastery_threshold: float = 0.6,
                     weak_topic_min: int = 2,
                     inactive_days: int = 10) -> list[dict]:
    """
    Identify students at risk in a class.
    Returns list of {student_id, display_name, weak_topics, last_session_days}.
    """
    enrolled = list_class_students(class_id)
    if not enrolled:
        return []
    student_ids = [s["student_id"] for s in enrolled]
    name_map = {s["student_id"]: s["display_name"] for s in enrolled}
    placeholders = ",".join("?" * len(student_ids))

    con = _con()
    # Mastery per student per topic
    mastery_rows = con.execute(f"""
        SELECT student_id, topic, AVG(score) as avg_score
        FROM scholar_mastery WHERE student_id IN ({placeholders})
        GROUP BY student_id, topic
    """, student_ids).fetchall()

    # Last session per student
    session_rows = con.execute(f"""
        SELECT student_id, MAX(started_ts) as last_ts
        FROM scholar_study_sessions WHERE student_id IN ({placeholders})
        GROUP BY student_id
    """, student_ids).fetchall()
    con.close()

    last_session: dict[str, datetime | None] = {r[0]: r[1] for r in session_rows}
    weak_topics: dict[str, list[str]] = {}
    for r in mastery_rows:
        if float(r[2]) < mastery_threshold:
            weak_topics.setdefault(r[0], []).append(r[1])

    now = datetime.now()
    results = []
    for sid in student_ids:
        wt = weak_topics.get(sid, [])
        last_ts = last_session.get(sid)
        days_inactive = (now - last_ts).days if last_ts else 999
        if len(wt) >= weak_topic_min or days_inactive >= inactive_days:
            results.append({
                "student_id": sid,
                "display_name": name_map.get(sid, sid),
                "weak_topics": wt,
                "weak_topic_count": len(wt),
                "last_session_days": days_inactive,
                "severity": "high" if len(wt) >= 4 or days_inactive >= 14 else "medium",
            })
    return sorted(results, key=lambda x: x["weak_topic_count"], reverse=True)


def student_mastery_trend(student_id: str, days: int = 30) -> list[dict]:
    """Return mastery scores per topic over the last N days."""
    con = _con()
    rows = con.execute(f"""
        SELECT topic, CAST(ts AS DATE) as day, AVG(score) as avg_score
        FROM scholar_mastery
        WHERE student_id=?
          AND ts >= NOW() - INTERVAL {int(days)} DAY
        GROUP BY topic, CAST(ts AS DATE)
        ORDER BY day ASC
    """, [student_id]).fetchall()
    con.close()
    return [{"topic": r[0], "day": str(r[1]), "avg_score": round(float(r[2]), 3)}
            for r in rows]


def generate_alert_sweep(teacher_id: str) -> int:
    """
    Scan all active classes for at-risk students, create alerts for new ones.
    Returns the count of new alerts created.
    """
    classes = list_classes(teacher_id)
    new_count = 0
    for cls in classes:
        at_risk = at_risk_students(
            cls["class_id"],
            mastery_threshold=float(cls.get("mastery_threshold", 0.6)),
        )
        for s in at_risk:
            msg_parts = []
            if s["weak_topic_count"] >= 2:
                msg_parts.append(
                    f"{s['weak_topic_count']} topics below mastery: "
                    + ", ".join(s["weak_topics"][:3])
                )
            if s["last_session_days"] >= 10:
                msg_parts.append(f"No study session in {s['last_session_days']} days")
            if msg_parts:
                _, created = _upsert_alert(
                    class_id=cls["class_id"],
                    student_id=s["student_id"],
                    alert_type="mastery_drop" if s["weak_topic_count"] >= 2 else "inactive",
                    message="; ".join(msg_parts),
                    severity=s["severity"],
                    data={"weak_topics": s["weak_topics"],
                          "days_inactive": s["last_session_days"]},
                )
                if created:
                    new_count += 1
    return new_count


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def lesson_gen_prompt(topic: str, subject: str, grade_level: str,
                      standards_set: str, duration_min: int,
                      standards_context: str = "",
                      extra_instructions: str = "") -> str:
    diff_note = (
        "Also generate a DIFFERENTIATED section with three versions:\n"
        "  BELOW GRADE: simplified version with additional scaffolding\n"
        "  ON GRADE: standard version\n"
        "  ABOVE GRADE: extension challenge + enrichment prompt"
    )
    return (
        f"You are an expert educator creating a lesson plan.\n\n"
        f"TOPIC: {topic}\n"
        f"SUBJECT: {subject}\n"
        f"GRADE LEVEL: {grade_level}\n"
        f"STANDARDS: {standards_set}\n"
        f"CLASS DURATION: {duration_min} minutes\n"
        f"{f'STANDARDS CONTEXT: {standards_context}' if standards_context else ''}\n"
        f"{f'EXTRA INSTRUCTIONS: {extra_instructions}' if extra_instructions else ''}\n\n"
        "Generate a complete lesson plan with the following sections. "
        "Use section headers exactly as shown.\n\n"
        "HOOK:\n[engaging 3-5 minute opening activity or question]\n\n"
        "LEARNING OBJECTIVES:\n[3-5 measurable objectives, each starting with a Bloom's verb; "
        "tag each with Bloom's level in brackets]\n\n"
        "DIRECT INSTRUCTION:\n[teacher-facing lecture/explanation notes, ~10-15 min]\n\n"
        "GUIDED PRACTICE:\n[class activity with full instructions, ~15 min]\n\n"
        "INDEPENDENT PRACTICE:\n[student task, ~10 min]\n\n"
        f"{diff_note}\n\n"
        "EXIT TICKET:\n[1-2 formative questions to check understanding]\n\n"
        "STANDARDS TAGS:\n[list the specific standard codes addressed, e.g. CCSS.MATH.6.RP.A.1]"
    )


def curriculum_outline_prompt(subject: str, grade_level: str, term_weeks: int,
                               standards_set: str,
                               big_ideas: list[str],
                               extra_context: str = "") -> str:
    big_ideas_str = "\n".join(f"- {b}" for b in big_ideas) if big_ideas else "(none)"
    return (
        f"You are a curriculum design expert.\n\n"
        f"SUBJECT: {subject}\n"
        f"GRADE LEVEL: {grade_level}\n"
        f"TERM LENGTH: {term_weeks} weeks\n"
        f"STANDARDS: {standards_set}\n"
        f"BIG IDEAS: \n{big_ideas_str}\n"
        f"{f'ADDITIONAL CONTEXT: {extra_context}' if extra_context else ''}\n\n"
        "Generate a full course outline. For each UNIT include:\n"
        "  UNIT N: [title]\n"
        "  Weeks: [e.g., Weeks 1-3]\n"
        "  Essential Questions: [2-3]\n"
        "  Key Topics: [5-8 bullet points]\n"
        "  Standards: [list relevant standard codes]\n"
        "  Assessments: [formative + summative ideas]\n\n"
        f"Create approximately {max(3, term_weeks // 3)} units. "
        "Ensure logical concept spiraling (Bloom's progression). "
        "Be specific, not generic."
    )


def quiz_gen_prompt(topic: str, subject: str, grade_level: str,
                    n_questions: int, question_types: list[str],
                    bloom_distribution: dict[str, int],
                    difficulty: str = "on_grade",
                    standards_context: str = "") -> str:
    bloom_str = "; ".join(
        f"{level}: {pct}%" for level, pct in bloom_distribution.items() if pct > 0
    )
    types_str = ", ".join(question_types)
    diff_label = {
        "below_grade": "BELOW GRADE LEVEL (simplified vocabulary, direct recall)",
        "on_grade": "ON GRADE LEVEL (standard expectations)",
        "above_grade": "ABOVE GRADE LEVEL (extension/enrichment, higher-order thinking)",
    }.get(difficulty, "ON GRADE LEVEL")
    return (
        f"You are an expert teacher creating an assessment.\n\n"
        f"TOPIC: {topic}\n"
        f"SUBJECT: {subject}\n"
        f"GRADE LEVEL: {grade_level} — {diff_label}\n"
        f"NUMBER OF QUESTIONS: {n_questions}\n"
        f"QUESTION TYPES TO USE: {types_str}\n"
        f"BLOOM'S DISTRIBUTION: {bloom_str}\n"
        f"{f'STANDARDS CONTEXT: {standards_context}' if standards_context else ''}\n\n"
        "Generate the complete question set. For each question output:\n"
        "  Q[N] [TYPE] [BLOOM_LEVEL]: [question text]\n"
        "  [For MC: list options A, B, C, D]\n"
        "  ANSWER: [correct answer]\n"
        "  EXPLANATION: [1-2 sentence rationale]\n\n"
        "Ensure questions span the Bloom's distribution above. "
        "Be specific and avoid trivial or ambiguous phrasing."
    )


def rubric_gen_prompt(assignment_type: str, learning_objectives: list[str],
                      point_scale: str = "4-point") -> str:
    objectives_str = "\n".join(f"- {o}" for o in learning_objectives)
    return (
        f"You are an expert educator creating an assessment rubric.\n\n"
        f"ASSIGNMENT TYPE: {assignment_type}\n"
        f"LEARNING OBJECTIVES:\n{objectives_str}\n"
        f"POINT SCALE: {point_scale}\n\n"
        "Generate a detailed rubric. For each criterion output:\n"
        "  CRITERION: [name]\n"
        "  WEIGHT: [percentage of total]\n"
        "  [Score 4/Excellent]: [specific descriptor]\n"
        "  [Score 3/Proficient]: [specific descriptor]\n"
        "  [Score 2/Developing]: [specific descriptor]\n"
        "  [Score 1/Beginning]: [specific descriptor]\n\n"
        "Create 4-6 meaningful criteria that map to the learning objectives. "
        "Descriptors must be specific, observable, and unambiguous."
    )


def ai_grade_prompt(question: str, expected_answer: str,
                    student_response: str, rubric_criteria: list[str],
                    subject: str, grade_level: str) -> str:
    criteria_str = "\n".join(f"- {c}" for c in rubric_criteria[:8])
    return (
        f"You are an expert {subject} teacher grading a student response.\n\n"
        f"GRADE LEVEL: {grade_level}\n"
        f"QUESTION: {question}\n"
        f"EXPECTED ANSWER: {expected_answer}\n"
        f"STUDENT RESPONSE: {student_response}\n\n"
        f"RUBRIC CRITERIA:\n{criteria_str}\n\n"
        "Provide your assessment in this format:\n"
        "SCORE: [0-100 percentage]\n"
        "STRENGTHS: [what the student got right, specifically]\n"
        "GAPS: [what is missing or incorrect, specifically]\n"
        "FEEDBACK: [warm, growth-oriented comment the student will read; "
        "2-3 sentences, specific to their response]\n"
        "BLOOM_LEVEL_DEMONSTRATED: [which Bloom's level the response shows]"
    )


def parent_report_prompt(student_name: str, subject: str, grade_level: str,
                         period: str,
                         avg_mastery: float = 0.0,
                         strong_topics: list[str] | None = None,
                         weak_topics: list[str] | None = None,
                         total_sessions: int = 0,
                         tone: str = "Professional",
                         language: str = "English",
                         teacher_notes: str = "",
                         # legacy params kept for compatibility
                         class_name: str = "",
                         mastery_data: list[dict] | None = None,
                         grade_summary: dict | None = None,
                         study_hours: float | None = None) -> str:
    # Support legacy call-style using mastery_data / grade_summary
    if mastery_data is not None:
        strong_topics = strong_topics or [d["topic"] for d in mastery_data
                                           if d.get("avg_score", 0) >= 0.8][:3]
        weak_topics   = weak_topics   or [d["topic"] for d in mastery_data
                                           if d.get("avg_score", 0) < 0.6][:3]
    if grade_summary is not None and avg_mastery == 0.0:
        avg_mastery = float(grade_summary.get("avg_pct", 0) or 0)
    if study_hours is not None and total_sessions == 0:
        total_sessions = int(study_hours)

    strong = strong_topics or []
    weak   = weak_topics   or []
    tone_instruction = {
        "Professional": "Use formal, professional language appropriate for official school communications.",
        "Warm":         "Use warm, encouraging, and personal language. Celebrate growth.",
        "Direct":       "Be concise and direct. Focus on facts and action items.",
    }.get(tone, "Professional")
    lang_instruction = (
        f"Write the entire report in {language}." if language != "English" else ""
    )
    return (
        f"You are a caring, professional teacher writing a progress report. "
        f"{tone_instruction} {lang_instruction}\n\n"
        f"STUDENT: {student_name}\n"
        f"SUBJECT: {subject}\n"
        f"GRADE LEVEL: {grade_level}\n"
        f"REPORTING PERIOD: {period}\n"
        f"STUDY SESSIONS THIS PERIOD: {total_sessions}\n"
        f"AVERAGE MASTERY: {avg_mastery:.1f}%\n"
        f"STRONG AREAS: {', '.join(strong) if strong else 'General effort'}\n"
        f"AREAS FOR GROWTH: {', '.join(weak) if weak else 'Consistent performance'}\n"
        f"{f'TEACHER NOTES: {teacher_notes}' if teacher_notes else ''}\n\n"
        "Write a complete progress report with these sections:\n"
        "ACADEMIC PROGRESS: [reference the actual topics and mastery data above; 2-3 sentences]\n"
        "STRENGTHS: [specific, genuine praise tied to the data; 2 sentences]\n"
        "AREAS FOR GROWTH: [constructive, specific, forward-looking; 2 sentences]\n"
        "STUDY HABITS: [comment on engagement and consistency; 1-2 sentences]\n"
        "NEXT STEPS: [1-2 specific recommendations for the student/family]\n\n"
        "Do NOT be vague. Reference the student by name. Make it feel personal and genuine."
    )


def resource_analysis_prompt(filename: str, extracted_text: str,
                              grade_level: str = "", subject: str = "") -> str:
    excerpt = extracted_text[:3000]
    return (
        f"You are an expert educator analyzing a teaching resource.\n\n"
        f"FILE: {filename}\n"
        f"{f'GRADE LEVEL: {grade_level}' if grade_level else ''}\n"
        f"{f'SUBJECT: {subject}' if subject else ''}\n\n"
        f"CONTENT EXCERPT:\n{excerpt}\n\n"
        "Analyze this resource and respond in this EXACT format:\n\n"
        "SUMMARY: [3-sentence summary of the resource content and purpose]\n\n"
        "TOPICS: [comma-separated list of 5-8 key topic tags]\n\n"
        "GRADE_LEVEL_ESTIMATE: [e.g. 'Grade 6-8' or 'High School']\n\n"
        "SUBJECT_ESTIMATE: [e.g. 'Biology', 'Algebra']\n\n"
        "VOCABULARY:\n- [term 1]\n- [term 2]\n[list 6-10 key vocabulary terms]\n\n"
        "DISCUSSION_QUESTIONS:\n1. [question]\n2. [question]\n"
        "[5 discussion questions at varying Bloom's levels]\n\n"
        "STANDARDS_TAGS: [possible standard codes this resource addresses, e.g. NGSS.LS1.A]"
    )


def conference_prep_prompt(student_name: str, subject: str = "",
                           grade_level: str = "",
                           avg_mastery: float = 0.0,
                           strong_topics: list[str] | None = None,
                           weak_topics: list[str] | None = None,
                           total_sessions: int = 0,
                           prior_communication_summary: str = "",
                           conference_context: str = "",
                           teacher_notes: str = "",
                           # legacy params
                           class_name: str = "",
                           mastery_data: list[dict] | None = None,
                           grade_summary: dict | None = None,
                           study_hours: float | None = None,
                           prior_comms: list[dict] | None = None) -> str:
    if mastery_data is not None:
        strong_topics = strong_topics or [d["topic"] for d in mastery_data
                                           if d.get("avg_score", 0) >= 0.8][:3]
        weak_topics   = weak_topics   or [d["topic"] for d in mastery_data
                                           if d.get("avg_score", 0) < 0.6][:3]
    if prior_comms is not None and not prior_communication_summary:
        prior_communication_summary = "; ".join(
            c.get("content","")[:100] for c in prior_comms[:3]
        )
    strong = strong_topics or []
    weak   = weak_topics   or []
    return (
        f"You are preparing a teacher for a parent-teacher conference.\n\n"
        f"STUDENT: {student_name}\n"
        f"SUBJECT: {subject}\n"
        f"GRADE LEVEL: {grade_level}\n"
        f"AVERAGE MASTERY: {avg_mastery:.1f}%\n"
        f"STRONG TOPICS: {', '.join(strong) or 'See below'}\n"
        f"WEAK TOPICS: {', '.join(weak) or 'None flagged'}\n"
        f"STUDY SESSIONS: {total_sessions}\n"
        f"PRIOR COMMUNICATIONS: {prior_communication_summary or 'None on record'}\n"
        f"{f'CONFERENCE CONTEXT: {conference_context}' if conference_context else ''}\n"
        f"{f'TEACHER NOTES: {teacher_notes}' if teacher_notes else ''}\n\n"
        "Generate a 1-page conference prep brief:\n\n"
        "PERFORMANCE SUMMARY: [3 sentences, data-backed]\n\n"
        "2 STRENGTHS TO HIGHLIGHT:\n1. [specific strength]\n2. [specific strength]\n\n"
        "2 GROWTH AREAS TO DISCUSS:\n1. [specific area + suggested strategy]\n2. [specific area + suggested strategy]\n\n"
        "1 SHARED GOAL: [one goal teacher + family can work on together]\n\n"
        "QUESTIONS TO ASK THE FAMILY:\n1. [Q]\n2. [Q]\n3. [Q]\n\n"
        "FOLLOW-UP ACTIONS: [what teacher commits to after the meeting]"
    )
