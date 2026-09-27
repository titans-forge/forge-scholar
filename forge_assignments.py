"""
forge_assignments.py — Titans Forge Scholar: Assignment Workflow System
=======================================================================

Full assignment lifecycle:
  Teacher creates → Publishes → Students view & submit → AI grades →
  Teacher reviews → Feedback returned to student

Tables: assignments, student_submissions, submission_feedback
Storage: scholar.duckdb
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from forge_scholar import SCHOLAR_DB

ASSIGNMENT_TYPES = [
    "homework", "quiz", "essay", "project", "lab_report",
    "problem_set", "presentation", "reading_response", "portfolio", "other",
]

SUBMISSION_STATUS = ["draft", "submitted", "returned", "late"]
ASSIGNMENT_STATUS = ["draft", "published", "closed", "archived"]


def _con() -> duckdb.DuckDBPyConnection:
    SCHOLAR_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(SCHOLAR_DB))


def init_assignments_db() -> None:
    con = _con()

    con.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            assignment_id   TEXT PRIMARY KEY,
            class_id        TEXT NOT NULL,
            teacher_id      TEXT NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT DEFAULT '',
            instructions    TEXT DEFAULT '',
            assignment_type TEXT DEFAULT 'homework',
            subject         TEXT DEFAULT '',
            grade_level     TEXT DEFAULT '',
            points_possible FLOAT DEFAULT 100.0,
            rubric_json     TEXT DEFAULT '{}',
            resources_json  TEXT DEFAULT '[]',
            status          TEXT DEFAULT 'draft',
            due_date        DATE,
            published_ts    TIMESTAMP,
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ai_grading_on   BOOLEAN DEFAULT TRUE,
            allow_late      BOOLEAN DEFAULT TRUE,
            allow_resubmit  BOOLEAN DEFAULT FALSE
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS student_submissions (
            submission_id   TEXT PRIMARY KEY,
            assignment_id   TEXT NOT NULL,
            student_id      TEXT NOT NULL,
            class_id        TEXT NOT NULL,
            content         TEXT DEFAULT '',
            file_ref        TEXT DEFAULT '',
            status          TEXT DEFAULT 'draft',
            submitted_ts    TIMESTAMP,
            is_late         BOOLEAN DEFAULT FALSE,
            attempt         INTEGER DEFAULT 1,
            word_count      INTEGER DEFAULT 0,
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS submission_feedback (
            feedback_id     TEXT PRIMARY KEY,
            submission_id   TEXT NOT NULL,
            assignment_id   TEXT NOT NULL,
            student_id      TEXT NOT NULL,
            score           FLOAT,
            max_score       FLOAT DEFAULT 100.0,
            pct             FLOAT,
            strengths       TEXT DEFAULT '',
            improvements    TEXT DEFAULT '',
            overall_comment TEXT DEFAULT '',
            rubric_scores   TEXT DEFAULT '{}',
            ai_graded       BOOLEAN DEFAULT FALSE,
            teacher_reviewed BOOLEAN DEFAULT FALSE,
            returned_ts     TIMESTAMP,
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.close()


# ── Assignment CRUD ────────────────────────────────────────────────────────────
def create_assignment(class_id: str, teacher_id: str, title: str,
                      description: str = "", instructions: str = "",
                      assignment_type: str = "homework",
                      subject: str = "", grade_level: str = "",
                      points_possible: float = 100.0,
                      due_date: date | None = None,
                      rubric: dict | None = None,
                      ai_grading_on: bool = True,
                      allow_late: bool = True,
                      allow_resubmit: bool = False) -> str:
    aid = f"asgn_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO assignments
            (assignment_id, class_id, teacher_id, title, description,
             instructions, assignment_type, subject, grade_level,
             points_possible, rubric_json, status, due_date,
             ai_grading_on, allow_late, allow_resubmit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [aid, class_id, teacher_id, title, description,
          instructions, assignment_type, subject, grade_level,
          points_possible, json.dumps(rubric or {}), "draft",
          due_date, ai_grading_on, allow_late, allow_resubmit])
    con.close()
    return aid


def publish_assignment(assignment_id: str) -> None:
    con = _con()
    con.execute("""
        UPDATE assignments
        SET status='published', published_ts=CURRENT_TIMESTAMP,
            updated_ts=CURRENT_TIMESTAMP
        WHERE assignment_id=?
    """, [assignment_id])
    con.close()


def close_assignment(assignment_id: str) -> None:
    con = _con()
    con.execute("""
        UPDATE assignments
        SET status='closed', updated_ts=CURRENT_TIMESTAMP
        WHERE assignment_id=?
    """, [assignment_id])
    con.close()


def update_assignment(assignment_id: str, **kwargs: Any) -> None:
    allowed = {"title","description","instructions","due_date",
                "points_possible","rubric_json","ai_grading_on",
                "allow_late","allow_resubmit","status"}
    con = _con()
    for k, v in kwargs.items():
        if k in allowed:
            if k == "rubric_json" and isinstance(v, dict):
                v = json.dumps(v)
            con.execute(
                f"UPDATE assignments SET {k}=?, updated_ts=CURRENT_TIMESTAMP "
                f"WHERE assignment_id=?", [v, assignment_id]
            )
    con.close()


def get_assignment(assignment_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT * FROM assignments WHERE assignment_id=?", [assignment_id]
    ).fetchone()
    desc = [d[0] for d in con.description] if row else []
    con.close()
    if not row:
        return None
    d = dict(zip(desc, row))
    d["rubric"] = json.loads(d.pop("rubric_json", "{}") or "{}")
    return d


def list_assignments(class_id: str, status: str | None = None,
                     include_closed: bool = False) -> list[dict]:
    con = _con()
    q = "SELECT * FROM assignments WHERE class_id=?"
    params: list[Any] = [class_id]
    if status:
        q += " AND status=?"
        params.append(status)
    elif not include_closed:
        q += " AND status IN ('draft','published')"
    q += " ORDER BY due_date ASC NULLS LAST, created_ts DESC"
    rows = con.execute(q, params).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    result = []
    for r in rows:
        d = dict(zip(desc, r))
        d["rubric"] = json.loads(d.pop("rubric_json", "{}") or "{}")
        result.append(d)
    return result


def list_student_assignments(student_id: str, class_id: str = "",
                              status_filter: str = "") -> list[dict]:
    """Return assignments visible to a student with their submission status."""
    con = _con()
    q = """
        SELECT a.*, sub.submission_id, sub.status as sub_status,
               sub.submitted_ts, fb.score, fb.pct
        FROM assignments a
        LEFT JOIN student_submissions sub
            ON a.assignment_id=sub.assignment_id AND sub.student_id=?
        LEFT JOIN submission_feedback fb
            ON sub.submission_id=fb.submission_id
        WHERE a.status='published'
    """
    params: list[Any] = [student_id]
    if class_id:
        q += " AND a.class_id=?"
        params.append(class_id)
    q += " ORDER BY a.due_date ASC NULLS LAST"
    rows = con.execute(q, params).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


def delete_assignment(assignment_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM student_submissions WHERE assignment_id=?",
                [assignment_id])
    con.execute("DELETE FROM assignments WHERE assignment_id=?",
                [assignment_id])
    con.close()


# ── Submission CRUD ────────────────────────────────────────────────────────────
def save_submission(assignment_id: str, student_id: str, class_id: str,
                    content: str, status: str = "submitted",
                    file_ref: str = "") -> str:
    # Check if draft exists
    con = _con()
    existing = con.execute("""
        SELECT submission_id, attempt FROM student_submissions
        WHERE assignment_id=? AND student_id=?
        ORDER BY created_ts DESC LIMIT 1
    """, [assignment_id, student_id]).fetchone()
    con.close()

    if existing and existing[1] == 1 and status == "draft":
        # Update existing draft
        sid = existing[0]
        con = _con()
        con.execute("""
            UPDATE student_submissions
            SET content=?, status=?, updated_ts=CURRENT_TIMESTAMP,
                word_count=?
            WHERE submission_id=?
        """, [content, status, len(content.split()), sid])
        con.close()
        return sid

    sid = f"sub_{uuid.uuid4().hex[:10]}"
    attempt = (existing[1] + 1) if existing else 1
    is_late = False
    # Check due date
    asgn = get_assignment(assignment_id)
    if asgn and asgn.get("due_date") and status == "submitted":
        is_late = date.today() > asgn["due_date"]
    sub_ts = datetime.now() if status == "submitted" else None
    con = _con()
    con.execute("""
        INSERT INTO student_submissions
            (submission_id, assignment_id, student_id, class_id, content,
             file_ref, status, submitted_ts, is_late, attempt, word_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [sid, assignment_id, student_id, class_id, content,
          file_ref, status, sub_ts, is_late, attempt,
          len(content.split())])
    con.close()
    return sid


def get_submission(submission_id: str) -> dict | None:
    con = _con()
    row = con.execute(
        "SELECT * FROM student_submissions WHERE submission_id=?",
        [submission_id]
    ).fetchone()
    desc = [d[0] for d in con.description] if row else []
    con.close()
    return dict(zip(desc, row)) if row else None


def list_submissions(assignment_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT s.*, COALESCE(st.display_name, s.student_id) as student_name
        FROM student_submissions s
        LEFT JOIN scholar_students st ON s.student_id=st.student_id
        WHERE s.assignment_id=?
        ORDER BY s.submitted_ts ASC NULLS LAST
    """, [assignment_id]).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


def get_student_submission(assignment_id: str, student_id: str) -> dict | None:
    con = _con()
    row = con.execute("""
        SELECT * FROM student_submissions
        WHERE assignment_id=? AND student_id=?
        ORDER BY created_ts DESC LIMIT 1
    """, [assignment_id, student_id]).fetchone()
    desc = [d[0] for d in con.description] if row else []
    con.close()
    return dict(zip(desc, row)) if row else None


# ── Feedback CRUD ──────────────────────────────────────────────────────────────
def save_feedback(submission_id: str, assignment_id: str, student_id: str,
                  score: float, max_score: float = 100.0,
                  strengths: str = "", improvements: str = "",
                  overall_comment: str = "",
                  rubric_scores: dict | None = None,
                  ai_graded: bool = False,
                  teacher_reviewed: bool = False) -> str:
    fid = f"fb_{uuid.uuid4().hex[:10]}"
    pct = round(score / max_score * 100, 1) if max_score else 0.0
    returned_ts = datetime.now() if teacher_reviewed else None
    con = _con()
    con.execute("""
        INSERT OR REPLACE INTO submission_feedback
            (feedback_id, submission_id, assignment_id, student_id,
             score, max_score, pct, strengths, improvements,
             overall_comment, rubric_scores, ai_graded,
             teacher_reviewed, returned_ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [fid, submission_id, assignment_id, student_id,
          score, max_score, pct, strengths, improvements,
          overall_comment, json.dumps(rubric_scores or {}),
          ai_graded, teacher_reviewed, returned_ts])
    # Mark submission as returned
    if teacher_reviewed:
        con.execute("""
            UPDATE student_submissions SET status='returned',
            updated_ts=CURRENT_TIMESTAMP WHERE submission_id=?
        """, [submission_id])
    con.close()
    return fid


def get_feedback(submission_id: str) -> dict | None:
    con = _con()
    row = con.execute("""
        SELECT * FROM submission_feedback
        WHERE submission_id=? ORDER BY created_ts DESC LIMIT 1
    """, [submission_id]).fetchone()
    desc = [d[0] for d in con.description] if row else []
    con.close()
    if not row:
        return None
    d = dict(zip(desc, row))
    d["rubric_scores"] = json.loads(d.get("rubric_scores", "{}") or "{}")
    return d


# ── Analytics ─────────────────────────────────────────────────────────────────
def assignment_stats(assignment_id: str) -> dict:
    con = _con()
    subs = con.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='submitted' OR status='returned' THEN 1 ELSE 0 END) as submitted,
               SUM(CASE WHEN is_late THEN 1 ELSE 0 END) as late
        FROM student_submissions WHERE assignment_id=?
    """, [assignment_id]).fetchone()
    scores = con.execute("""
        SELECT AVG(pct), MIN(pct), MAX(pct)
        FROM submission_feedback WHERE assignment_id=?
    """, [assignment_id]).fetchone()
    con.close()
    return {
        "total_submissions": subs[0] if subs else 0,
        "submitted": subs[1] if subs else 0,
        "late": subs[2] if subs else 0,
        "avg_pct": round(scores[0] or 0, 1) if scores else 0,
        "min_pct": round(scores[1] or 0, 1) if scores else 0,
        "max_pct": round(scores[2] or 0, 1) if scores else 0,
    }


def student_assignment_stats(student_id: str, class_id: str = "") -> dict:
    con = _con()
    q = """
        SELECT COUNT(a.assignment_id) as total_assigned,
               SUM(CASE WHEN s.status IN ('submitted','returned') THEN 1 ELSE 0 END) as submitted,
               SUM(CASE WHEN s.is_late THEN 1 ELSE 0 END) as late,
               AVG(fb.pct) as avg_score
        FROM assignments a
        LEFT JOIN student_submissions s
            ON a.assignment_id=s.assignment_id AND s.student_id=?
        LEFT JOIN submission_feedback fb
            ON s.submission_id=fb.submission_id
        WHERE a.status IN ('published','closed')
    """
    params: list[Any] = [student_id]
    if class_id:
        q += " AND a.class_id=?"
        params.append(class_id)
    row = con.execute(q, params).fetchone()
    con.close()
    return {
        "total_assigned": row[0] or 0,
        "submitted": row[1] or 0,
        "late": row[2] or 0,
        "avg_score": round(row[3] or 0, 1),
        "completion_pct": round((row[1] or 0) / (row[0] or 1) * 100, 1),
    }


# ── AI Prompt builders ─────────────────────────────────────────────────────────
def ai_grade_assignment_prompt(assignment_title: str, instructions: str,
                                student_response: str, rubric: dict | None = None,
                                points_possible: float = 100.0,
                                subject: str = "",
                                grade_level: str = "") -> str:
    rubric_text = ""
    if rubric:
        criteria = rubric.get("criteria", rubric.get("raw", ""))
        if isinstance(criteria, list):
            rubric_text = "\n".join(f"- {c}" for c in criteria[:8])
        elif isinstance(criteria, str):
            rubric_text = criteria[:600]
    return (
        f"You are a fair, constructive teacher grading a student assignment.\n"
        f"Subject: {subject} | Grade Level: {grade_level}\n"
        f"Assignment: {assignment_title}\n"
        f"Points possible: {points_possible}\n"
        f"Instructions given to student: {instructions[:400]}\n"
        f"{f'Rubric criteria:{chr(10)}{rubric_text}' if rubric_text else ''}\n\n"
        f"STUDENT SUBMISSION:\n{student_response[:2000]}\n\n"
        f"Grade this submission. Respond in EXACT format:\n\n"
        f"SCORE: [number out of {points_possible}]\n"
        f"STRENGTHS: [2-3 specific things the student did well]\n"
        f"IMPROVEMENTS: [2-3 specific, actionable things to improve]\n"
        f"OVERALL_COMMENT: [1-2 sentence teacher-voice comment to the student]\n\n"
        f"Be fair, specific, and encouraging. Do not be vague."
    )


def ai_writing_assist_prompt(assignment_title: str, instructions: str,
                               student_draft: str, grade_level: str = "",
                               assist_mode: str = "review") -> str:
    modes = {
        "review":    "Review this draft. Point out 3 strengths and 3 specific improvements.",
        "outline":   "Help the student create a detailed outline for this assignment.",
        "ideas":     "Give the student 5 ideas/angles they could explore for this topic.",
        "citations": "Suggest how to strengthen the argument with evidence and citations.",
        "grammar":   "Point out grammar, spelling, and clarity issues without rewriting.",
    }
    task = modes.get(assist_mode, modes["review"])
    return (
        f"You are a supportive writing tutor (grade level: {grade_level}).\n"
        f"Assignment: {assignment_title}\n"
        f"Instructions: {instructions[:300]}\n\n"
        f"STUDENT DRAFT:\n{student_draft[:1500]}\n\n"
        f"Task: {task}\n\n"
        f"Be encouraging and specific. Do not write the assignment for the student."
    )
