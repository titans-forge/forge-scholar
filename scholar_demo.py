"""A self-contained, fictional fractions classroom for the public Scholar demo.

Every database path is explicit. Nothing in this module imports the Forge Vault,
calls a model, or reads real student records. The answer review applies visible
rules to a small, authored fixture; it is evidence for teacher review, not a
diagnosis of what a student is thinking.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterator
from urllib.parse import quote


CLASSROOM = {
    "id": "public_fraction_workshop_5",
    "name": "Grade 5 · Fraction workshop",
    "grade": "5",
    "subject": "Mathematics",
    "is_fictional": True,
    "method": "observed_answer_rules_v1",
}

QUESTIONS = (
    {
        "id": "equal_parts",
        "prompt": "1/4 + 1/4 = ?",
        "expected_answer": "1/2",
        "explanation": "One quarter plus one quarter makes two quarters, or one half. The pieces stay the same size.",
    },
    {
        "id": "common_unit",
        "prompt": "1/2 + 1/3 = ?",
        "expected_answer": "5/6",
        "explanation": "Use equal-sized pieces: 1/2 is 3/6 and 1/3 is 2/6, so the sum is 5/6.",
    },
    {
        "id": "compare_parts",
        "prompt": "Which is greater: 3/8 or 1/2?",
        "expected_answer": "1/2",
        "explanation": "One half is four eighths. Four eighths is greater than three eighths.",
    },
)

# Display names are invented. IDs are deliberately distinct from the original
# Forge workspace demo IDs, and this fixture lives in its own SQLite file.
STUDENTS = (
    ("fictional_avery", "Avery", ("2/8", "2/5", "1/2")),
    ("fictional_jordan", "Jordan", ("2/8", "2/5", "3/8")),
    ("fictional_mina", "Mina", ("1/2", "5/6", "1/2")),
    ("fictional_theo", "Theo", ("2/8", "5/6", "1/2")),
    ("fictional_lena", "Lena", ("1/2", "2/5", "1/2")),
    ("fictional_omar", "Omar", ("1/2", "5/6", "3/8")),
    ("fictional_sam", "Sam", ("2/8", "2/5", "1/2")),
    ("fictional_nora", "Nora", ("1/2", "5/6", "1/2")),
)

PATTERNS = (
    {
        "id": "adding_denominators",
        "title": "Adding the denominators",
        "description": "These answers are consistent with adding both the numerators and denominators. A short conversation can check the student's reasoning.",
    },
    {
        "id": "numerator_only_comparison",
        "title": "Comparing the top numbers",
        "description": "Choosing 3/8 over 1/2 may mean the student compared 3 with 1 without accounting for the size of the pieces. Ask the student to explain.",
    },
)

_PATTERN_ANSWERS = {
    ("equal_parts", Fraction(2, 8)): "adding_denominators",
    ("common_unit", Fraction(2, 5)): "adding_denominators",
    ("compare_parts", Fraction(3, 8)): "numerator_only_comparison",
}


class StaleLessonError(ValueError):
    """The lesson changed after the teacher reviewed this version."""


def _path(db_path: str | Path) -> Path:
    if not str(db_path).strip() or str(db_path) == ":memory:":
        raise ValueError("Provide an explicit path for the persistent demo database.")
    return Path(db_path).expanduser().resolve()


@contextmanager
def _connection(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open an existing database only; reads never create a database by accident."""
    path = _path(db_path)
    uri = f"file:{quote(str(path), safe='/')}?mode=rw"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def initialize_demo(db_path: str | Path) -> None:
    """Create the explicit local database and seed missing fictional rows.

    Repeat calls preserve saved answers, teacher drafts, and approvals. There is
    no reset or delete operation, and no connection to the live Scholar DB.
    """
    path = _path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS demo_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS demo_students (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                display_order INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS demo_responses (
                student_id TEXT NOT NULL REFERENCES demo_students(id),
                question_id TEXT NOT NULL,
                answer TEXT NOT NULL,
                PRIMARY KEY (student_id, question_id)
            );
            CREATE TABLE IF NOT EXISTS demo_lesson (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                activities_json TEXT NOT NULL,
                teacher_note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('draft', 'approved')),
                version INTEGER NOT NULL CHECK (version >= 1),
                updated_at TEXT NOT NULL,
                approved_at TEXT
            );
            """
        )
        con.execute(
            "INSERT OR IGNORE INTO demo_metadata (key, value) VALUES ('fixture_version', '1')"
        )
        for index, (student_id, name, answers) in enumerate(STUDENTS):
            con.execute(
                "INSERT OR IGNORE INTO demo_students (id, name, display_order) VALUES (?, ?, ?)",
                (student_id, name, index),
            )
            con.executemany(
                "INSERT OR IGNORE INTO demo_responses (student_id, question_id, answer) VALUES (?, ?, ?)",
                [(student_id, q["id"], answer) for q, answer in zip(QUESTIONS, answers)],
            )


def _fraction(answer: str) -> Fraction | None:
    try:
        return Fraction(answer.strip())
    except (ValueError, ZeroDivisionError):
        return None


def _percent(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 1) if denominator else 0.0


def _lesson(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["activities"] = json.loads(result.pop("activities_json"))
    return result


def get_lesson(db_path: str | Path) -> dict | None:
    """Return the current teacher lesson draft or approved version."""
    with _connection(db_path) as con:
        return _lesson(con.execute("SELECT * FROM demo_lesson WHERE id = 1").fetchone())


def get_classroom(db_path: str | Path) -> dict:
    """Review exact saved answers and derive counts from those answers.

    Pattern matches are transparent rules, not a model-generated assessment.
    Equivalent fraction notation is accepted as correct (for example, 2/4).
    """
    with _connection(db_path) as con:
        student_rows = con.execute(
            "SELECT * FROM demo_students ORDER BY display_order, id"
        ).fetchall()
        responses = {
            (row["student_id"], row["question_id"]): row["answer"]
            for row in con.execute("SELECT * FROM demo_responses").fetchall()
        }
        current_lesson = _lesson(
            con.execute("SELECT * FROM demo_lesson WHERE id = 1").fetchone()
        )

    students = []
    patterns = [{**pattern, "evidence": []} for pattern in PATTERNS]
    patterns_by_id = {pattern["id"]: pattern for pattern in patterns}
    questions = [{**question, "answers": []} for question in QUESTIONS]
    for row in student_rows:
        student = {"id": row["id"], "name": row["name"], "answers": []}
        for question in questions:
            answer = responses.get((row["id"], question["id"]))
            if answer is None:
                continue
            value = _fraction(answer)
            correct = value == _fraction(question["expected_answer"])
            pattern_id = None if correct else _PATTERN_ANSWERS.get((question["id"], value))
            student["answers"].append(
                {
                    "question_id": question["id"],
                    "prompt": question["prompt"],
                    "answer": answer,
                    "expected_answer": question["expected_answer"],
                    "correct": correct,
                    "pattern_id": pattern_id,
                    "explanation": question["explanation"],
                }
            )
            question["answers"].append(
                {"student_id": row["id"], "student_name": row["name"], "answer": answer, "correct": correct}
            )
            if pattern_id:
                patterns_by_id[pattern_id]["evidence"].append(
                    {
                        "student_id": row["id"],
                        "student_name": row["name"],
                        "question_id": question["id"],
                        "prompt": question["prompt"],
                        "answer": answer,
                        "expected_answer": question["expected_answer"],
                    }
                )
        student["correct_count"] = sum(answer["correct"] for answer in student["answers"])
        student["total_questions"] = len(student["answers"])
        student["accuracy_percent"] = _percent(student["correct_count"], student["total_questions"])
        students.append(student)

    for question in questions:
        question["correct_count"] = sum(answer["correct"] for answer in question["answers"])
        question["response_count"] = len(question["answers"])
        question["accuracy_percent"] = _percent(question["correct_count"], question["response_count"])
    for pattern in patterns:
        # Preserve classroom order, while counting unique students only once.
        ids = {entry["student_id"] for entry in pattern["evidence"]}
        pattern["student_ids"] = [student["id"] for student in students if student["id"] in ids]
        pattern["student_names"] = [student["name"] for student in students if student["id"] in ids]
        pattern["student_count"] = len(ids)
        pattern["response_count"] = len(pattern["evidence"])
    patterns.sort(key=lambda pattern: (-pattern["student_count"], -pattern["response_count"], pattern["id"]))

    correct_count = sum(student["correct_count"] for student in students)
    response_count = sum(student["total_questions"] for student in students)
    summary = {
        "student_count": len(students),
        "response_count": response_count,
        "correct_count": correct_count,
        "accuracy_percent": _percent(correct_count, response_count),
        "needs_support_count": sum(student["correct_count"] < student["total_questions"] for student in students),
    }

    denominator_pattern = patterns_by_id["adding_denominators"]
    comparison_pattern = patterns_by_id["numerator_only_comparison"]
    if denominator_pattern["student_count"]:
        recommended = {
            "title": "Keep the pieces the same size",
            "objective": "Add fractions using equal-sized pieces, then check the answer with a model.",
            "activities": [
                "Shade one quarter twice on the same-sized whole. Count two quarters and show that 2/4 = 1/2; the pieces do not become eighths.",
                "Build a common unit: show 1/2 as 3/6 and 1/3 as 2/6, then combine five sixths.",
                "Compare 3/8 with 1/2 using equal-length bars. Rename 1/2 as 4/8 and ask which amount is greater.",
            ],
            "success_check": "Ask each student to solve 1/3 + 1/3 and explain why the denominator stays 3.",
            "reason": f"{denominator_pattern['student_count']} of {len(students)} students selected answers consistent with adding denominators. Use their answers to check the reasoning before choosing support.",
            "target_student_ids": denominator_pattern["student_ids"],
        }
    elif comparison_pattern["student_count"]:
        recommended = {
            "title": "Compare pieces on the same whole",
            "objective": "Compare fractions by showing equal-sized pieces of the same-sized whole.",
            "activities": [
                "Place equal-length bars for 3/8 and 1/2 side by side.",
                "Rename 1/2 as 4/8, then compare three pieces with four pieces.",
                "Ask students to explain why the top number alone cannot tell them which fraction is greater.",
            ],
            "success_check": "Compare 2/5 and 1/2, using a diagram to explain the answer.",
            "reason": f"{comparison_pattern['student_count']} of {len(students)} students chose 3/8 over 1/2. Ask them to explain and use fraction bars to check their reasoning.",
            "target_student_ids": comparison_pattern["student_ids"],
        }
    else:
        recommended = {
            "title": "Check the reasoning, then choose the next challenge",
            "objective": "Explain fraction answers with a diagram before moving on.",
            "activities": [
                "Ask students to explain one addition answer using equal-sized pieces.",
                "Discuss any incorrect answer that did not match the visible review rules.",
                "Use the explanations to decide whether to revisit fractions or extend the lesson.",
            ],
            "success_check": "Solve a fresh fraction question and explain the size of each piece.",
            "reason": "No saved answer currently matches the two review patterns. This does not establish mastery; review the answers and student explanations.",
            "target_student_ids": [student["id"] for student in students if student["correct_count"] < student["total_questions"]],
        }
    return {
        "classroom": dict(CLASSROOM),
        "summary": summary,
        "questions": questions,
        "students": students,
        "patterns": patterns,
        "recommended_lesson": recommended,
        "current_lesson": current_lesson,
    }


def save_lesson_draft(
    db_path: str | Path,
    *,
    title: str,
    objective: str,
    activities: list[str],
    teacher_note: str = "",
) -> dict:
    """Save a teacher-edited draft. Every edit invalidates the prior approval."""
    title = title.strip()
    objective = objective.strip()
    if not title or not objective:
        raise ValueError("A lesson needs a title and learning objective.")
    if not isinstance(activities, list) or any(not isinstance(activity, str) for activity in activities):
        raise ValueError("Activities must be a list of text instructions.")
    cleaned = [activity.strip() for activity in activities if activity.strip()]
    if not cleaned:
        raise ValueError("A lesson needs at least one activity.")
    with _connection(db_path) as con:
        # Obtain the write lock before reading the version so two saves cannot
        # independently read the same version and silently replace each other.
        con.execute("BEGIN IMMEDIATE")
        previous = con.execute("SELECT version FROM demo_lesson WHERE id = 1").fetchone()
        version = previous["version"] + 1 if previous else 1
        con.execute(
            """INSERT INTO demo_lesson
               (id, title, objective, activities_json, teacher_note, status, version, updated_at, approved_at)
               VALUES (1, ?, ?, ?, ?, 'draft', ?, ?, NULL)
               ON CONFLICT(id) DO UPDATE SET
               title = excluded.title, objective = excluded.objective,
               activities_json = excluded.activities_json, teacher_note = excluded.teacher_note,
               status = 'draft', version = excluded.version,
               updated_at = excluded.updated_at, approved_at = NULL""",
            (title, objective, json.dumps(cleaned), teacher_note.strip(), version, _now()),
        )
        result = _lesson(con.execute("SELECT * FROM demo_lesson WHERE id = 1").fetchone())
    assert result is not None
    return result


def approve_lesson(db_path: str | Path, *, expected_version: int) -> dict:
    """Approve the reviewed draft version, or reject a stale approval attempt."""
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ValueError("The reviewed lesson version must be an integer.")
    with _connection(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM demo_lesson WHERE id = 1").fetchone()
        if row is None:
            raise ValueError("Save and review a lesson draft before approving it.")
        if row["version"] != expected_version:
            raise StaleLessonError("The lesson changed. Review the current version before approving it.")
        if row["status"] == "draft":
            con.execute(
                "UPDATE demo_lesson SET status = 'approved', approved_at = ?, updated_at = ? WHERE id = 1 AND version = ?",
                (_now(), _now(), expected_version),
            )
        result = _lesson(con.execute("SELECT * FROM demo_lesson WHERE id = 1").fetchone())
    assert result is not None
    return result


def get_student_preview(db_path: str | Path, student_id: str) -> dict:
    """Show a fictional student's answers and only the approved lesson.

    Teacher notes remain in the teacher workspace and are never returned here.

    This is a preview helper for the single-user demo, not authentication or a
    production authorization boundary.
    """
    classroom = get_classroom(db_path)
    student = next((student for student in classroom["students"] if student["id"] == student_id), None)
    if student is None:
        raise KeyError(f"Unknown fictional student: {student_id}")
    lesson = classroom["current_lesson"]
    student_lesson = None
    if lesson and lesson["status"] == "approved":
        student_lesson = {key: value for key, value in lesson.items() if key != "teacher_note"}
    return {
        "student": student,
        "lesson": student_lesson,
        "is_fictional": True,
    }
