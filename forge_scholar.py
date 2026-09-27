"""
forge_scholar.py — Titans Forge Scholar: Student Learning OS backend
=====================================================================

All database schema, CRUD helpers, mastery engine, quiz generation prompts,
study plan logic, and system-prompt routing for the Scholar education product.

Storage: medical_vault/scholar.duckdb  (separate from clinical medical_master.duckdb)

Architecture
────────────
  • forge_scholar.py  → pure backend: schema + helpers + prompt builders
  • pages/19–23       → Streamlit UI consuming this module
  • forge_config.query_local() → Ollama inference (no MLX by default)

Education Levels
────────────────
  elementary   — Grades K-5
  middle       — Grades 6-8
  high         — Grades 9-12
  college      — Undergraduate
  professional — Graduate / Med / Law / Licensing

Help Modes (integrity continuum)
─────────────────────────────────
  hint_only   — Redirect + Socratic questions only
  guided      — Step-by-step hints, similar examples, no answer
  explain     — Full concept explanation, no direct solution
  full        — Complete explanation + solution
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

# ── DB path ───────────────────────────────────────────────────────────────────
VAULT_ROOT   = Path.home() / "Vault"
SCHOLAR_DB   = VAULT_ROOT / "medical_vault" / "scholar.duckdb"

# ── Education level constants ─────────────────────────────────────────────────
EDU_LEVELS = ["elementary", "middle", "high", "college", "professional"]
EDU_LABELS = {
    "elementary":   "Elementary (K-5)",
    "middle":       "Middle School (6-8)",
    "high":         "High School (9-12)",
    "college":      "College / Undergraduate",
    "professional": "Graduate / Professional",
}

# ── Help mode constants ───────────────────────────────────────────────────────
HELP_MODES = ["hint_only", "guided", "explain", "full"]
HELP_MODE_LABELS = {
    "hint_only": "Hint Only (Socratic)",
    "guided":    "Guided (hints + examples)",
    "explain":   "Full Explanation",
    "full":      "Full Answer",
}

# ── Subject constants ─────────────────────────────────────────────────────────
SUBJECTS = [
    "Math", "Algebra", "Geometry", "Calculus", "Statistics",
    "Biology", "Chemistry", "Physics", "Earth Science", "Anatomy",
    "English / Writing", "Literature", "History", "Social Studies", "Geography",
    "Computer Science", "Economics", "Psychology", "Foreign Language",
    "Art / Music", "Medical", "Law", "Engineering", "Other",
]

# ── DB connection helper ──────────────────────────────────────────────────────
def _con() -> duckdb.DuckDBPyConnection:
    """Return a new connection to the scholar database."""
    SCHOLAR_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(SCHOLAR_DB))


def _rollback_quietly(con: duckdb.DuckDBPyConnection) -> None:
    try:
        con.rollback()
    except Exception:
        pass


# ── Schema initialisation ─────────────────────────────────────────────────────
def init_scholar_db() -> None:
    """Create all Scholar tables and sequences (idempotent)."""
    con = _con()
    try:
        # Sequences
        for seq in [
            "scholar_mastery_seq",
            "scholar_chat_msg_seq",
            "scholar_quiz_result_seq",
            "scholar_study_session_seq",
        ]:
            try:
                con.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1")
            except Exception:
                _rollback_quietly(con)

        # Students
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_students (
                student_id     VARCHAR PRIMARY KEY,
                display_name   VARCHAR NOT NULL,
                edu_level      VARCHAR NOT NULL,
                grade_year     VARCHAR,
                goals_json     TEXT DEFAULT '[]',
                settings_json  TEXT DEFAULT '{}',
                created_ts     TIMESTAMP DEFAULT NOW(),
                updated_ts     TIMESTAMP DEFAULT NOW()
            )
        """)

        # Courses
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_courses (
                course_id      VARCHAR PRIMARY KEY,
                student_id     VARCHAR NOT NULL,
                title          VARCHAR NOT NULL,
                subject        VARCHAR,
                edu_level      VARCHAR,
                instructor     VARCHAR,
                term           VARCHAR,
                start_date     DATE,
                end_date       DATE,
                syllabus_text  TEXT DEFAULT '',
                notes_text     TEXT DEFAULT '',
                created_ts     TIMESTAMP DEFAULT NOW()
            )
        """)

        # Assignments
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_assignments (
                assignment_id  VARCHAR PRIMARY KEY,
                course_id      VARCHAR NOT NULL,
                student_id     VARCHAR NOT NULL,
                title          VARCHAR NOT NULL,
                description    TEXT DEFAULT '',
                due_date       DATE,
                assignment_type VARCHAR DEFAULT 'homework',
                priority       VARCHAR DEFAULT 'medium',
                status         VARCHAR DEFAULT 'not_started',
                rubric_text    TEXT DEFAULT '',
                created_ts     TIMESTAMP DEFAULT NOW(),
                updated_ts     TIMESTAMP DEFAULT NOW()
            )
        """)

        # Skills / learning objectives
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_skills (
                skill_id         VARCHAR PRIMARY KEY,
                student_id       VARCHAR NOT NULL,
                course_id        VARCHAR,
                name             VARCHAR NOT NULL,
                subject          VARCHAR,
                standard         VARCHAR,
                parent_skill_id  VARCHAR,
                created_ts       TIMESTAMP DEFAULT NOW()
            )
        """)

        # Mastery events
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_mastery (
                id             BIGINT PRIMARY KEY DEFAULT nextval('scholar_mastery_seq'),
                student_id     VARCHAR NOT NULL,
                skill_id       VARCHAR,
                course_id      VARCHAR,
                topic          VARCHAR NOT NULL,
                source         VARCHAR DEFAULT 'chat',
                score          DOUBLE DEFAULT 0.5,
                correct        BOOLEAN,
                question_text  TEXT,
                answer_text    TEXT,
                feedback_text  TEXT,
                ts             TIMESTAMP DEFAULT NOW()
            )
        """)

        # Chat sessions
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_chat_sessions (
                session_id     VARCHAR PRIMARY KEY,
                student_id     VARCHAR,
                course_id      VARCHAR,
                edu_level      VARCHAR,
                subject        VARCHAR,
                help_mode      VARCHAR DEFAULT 'guided',
                started_ts     TIMESTAMP DEFAULT NOW(),
                ended_ts       TIMESTAMP,
                message_count  INTEGER DEFAULT 0,
                topics_json    TEXT DEFAULT '[]'
            )
        """)

        # Chat messages
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_chat_messages (
                id             BIGINT PRIMARY KEY DEFAULT nextval('scholar_chat_msg_seq'),
                session_id     VARCHAR NOT NULL,
                role           VARCHAR NOT NULL,
                content        TEXT NOT NULL,
                ts             TIMESTAMP DEFAULT NOW(),
                mastery_id     BIGINT
            )
        """)

        # Study sessions
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_study_sessions (
                id             BIGINT PRIMARY KEY DEFAULT nextval('scholar_study_session_seq'),
                student_id     VARCHAR NOT NULL,
                course_id      VARCHAR,
                topic          VARCHAR,
                started_ts     TIMESTAMP DEFAULT NOW(),
                ended_ts       TIMESTAMP,
                duration_min   INTEGER,
                session_type   VARCHAR DEFAULT 'tutor',
                outcome        VARCHAR DEFAULT 'pending',
                notes          TEXT DEFAULT ''
            )
        """)

        # Quiz items (generated questions)
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_quiz_items (
                item_id        VARCHAR PRIMARY KEY,
                student_id     VARCHAR NOT NULL,
                course_id      VARCHAR,
                topic          VARCHAR NOT NULL,
                question       TEXT NOT NULL,
                expected_answer TEXT,
                difficulty     VARCHAR DEFAULT 'medium',
                item_type      VARCHAR DEFAULT 'short_answer',
                options_json   TEXT,
                source         VARCHAR DEFAULT 'generated',
                created_ts     TIMESTAMP DEFAULT NOW()
            )
        """)

        # Quiz results
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_quiz_results (
                id             BIGINT PRIMARY KEY DEFAULT nextval('scholar_quiz_result_seq'),
                item_id        VARCHAR NOT NULL,
                student_id     VARCHAR NOT NULL,
                student_answer TEXT,
                score          DOUBLE,
                correct        BOOLEAN,
                feedback_text  TEXT,
                ts             TIMESTAMP DEFAULT NOW()
            )
        """)

        # SM-2 spaced repetition schedule (one row per student+topic)
        con.execute("""
            CREATE TABLE IF NOT EXISTS scholar_review_schedule (
                student_id    VARCHAR NOT NULL,
                topic         VARCHAR NOT NULL,
                ease_factor   DOUBLE  DEFAULT 2.5,
                interval_days INTEGER DEFAULT 1,
                repetitions   INTEGER DEFAULT 0,
                next_review   DATE    DEFAULT CURRENT_DATE,
                last_review   TIMESTAMP,
                PRIMARY KEY (student_id, topic)
            )
        """)

        con.close()
    except Exception as exc:
        _rollback_quietly(con)
        con.close()
        raise exc


# ══════════════════════════════════════════════════════════════════════════════
# CRUD — Students
# ══════════════════════════════════════════════════════════════════════════════

def create_student(display_name: str, edu_level: str, grade_year: str = "",
                   goals: list[str] | None = None, settings: dict | None = None) -> str:
    """Create a student profile, return student_id."""
    sid = f"stu_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO scholar_students
            (student_id, display_name, edu_level, grade_year, goals_json, settings_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [sid, display_name, edu_level, grade_year,
          json.dumps(goals or []), json.dumps(settings or {})])
    con.close()
    return sid


def list_students() -> list[dict]:
    """Return all student profiles ordered by updated_ts desc."""
    con = _con()
    rows = con.execute("""
        SELECT student_id, display_name, edu_level, grade_year, goals_json, settings_json, updated_ts
        FROM scholar_students ORDER BY updated_ts DESC
    """).fetchall()
    con.close()
    return [
        {
            "student_id":    r[0],
            "display_name":  r[1],
            "edu_level":     r[2],
            "grade_year":    r[3],
            "goals":         _json_load(r[4], []),
            "settings":      _json_load(r[5], {}),
            "updated_ts":    r[6],
        }
        for r in rows
    ]


def get_student(student_id: str) -> dict | None:
    """Return a single student dict or None."""
    con = _con()
    row = con.execute("""
        SELECT student_id, display_name, edu_level, grade_year, goals_json, settings_json, updated_ts
        FROM scholar_students WHERE student_id = ?
    """, [student_id]).fetchone()
    con.close()
    if not row:
        return None
    return {
        "student_id":   row[0],
        "display_name": row[1],
        "edu_level":    row[2],
        "grade_year":   row[3],
        "goals":        _json_load(row[4], []),
        "settings":     _json_load(row[5], {}),
        "updated_ts":   row[6],
    }


def update_student_settings(student_id: str, settings: dict) -> None:
    con = _con()
    con.execute("""
        UPDATE scholar_students SET settings_json = ?, updated_ts = NOW()
        WHERE student_id = ?
    """, [json.dumps(settings), student_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# CRUD — Courses
# ══════════════════════════════════════════════════════════════════════════════

def create_course(student_id: str, title: str, subject: str = "",
                  edu_level: str = "", instructor: str = "", term: str = "",
                  start_date: str = "", end_date: str = "") -> str:
    """Create a course, return course_id."""
    cid = f"crs_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO scholar_courses
            (course_id, student_id, title, subject, edu_level, instructor,
             term, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [cid, student_id, title, subject, edu_level, instructor, term,
          start_date or None, end_date or None])
    con.close()
    return cid


def list_courses(student_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT course_id, title, subject, edu_level, instructor, term, start_date, end_date
        FROM scholar_courses WHERE student_id = ? ORDER BY created_ts DESC
    """, [student_id]).fetchall()
    con.close()
    return [
        {
            "course_id":   r[0],
            "title":       r[1],
            "subject":     r[2],
            "edu_level":   r[3],
            "instructor":  r[4],
            "term":        r[5],
            "start_date":  r[6],
            "end_date":    r[7],
        }
        for r in rows
    ]


def extract_text_from_upload(file_bytes: bytes, filename: str) -> str:
    """
    Parse uploaded file bytes into plain text.
    Supports PDF (via PyMuPDF or pdfminer fallback), DOCX, and plain TXT.
    Returns extracted text (may be truncated at 50 000 chars for DB storage).
    """
    ext = Path(filename).suffix.lower()
    text = ""

    if ext == ".pdf":
        # Try PyMuPDF (fitz) first — fast and accurate
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = [page.get_text() for page in doc]
            text = "\n\n".join(pages)
            doc.close()
        except ImportError:
            # Fallback to pdfminer
            try:
                from pdfminer.high_level import extract_text_to_fp
                from pdfminer.layout import LAParams
                import io
                output = io.StringIO()
                extract_text_to_fp(io.BytesIO(file_bytes), output, laparams=LAParams())
                text = output.getvalue()
            except ImportError:
                text = "[PDF parsing unavailable — install PyMuPDF: pip install pymupdf]"
        except Exception as exc:
            text = f"[PDF parse error: {exc}]"

    elif ext in (".docx",):
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            text = "[DOCX parsing unavailable — install python-docx]"
        except Exception as exc:
            text = f"[DOCX parse error: {exc}]"

    elif ext in (".txt", ".md", ".rst"):
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            text = f"[Text decode error: {exc}]"

    else:
        text = f"[Unsupported file type: {ext}]"

    return text[:50_000]  # DB ceiling



    con = _con()
    con.execute("""
        UPDATE scholar_courses
        SET syllabus_text = CASE WHEN ? != '' THEN ? ELSE syllabus_text END,
            notes_text    = CASE WHEN ? != '' THEN ? ELSE notes_text END
        WHERE course_id = ?
    """, [syllabus_text, syllabus_text, notes_text, notes_text, course_id])
    con.close()


def get_course(course_id: str) -> dict | None:
    con = _con()
    row = con.execute("""
        SELECT course_id, student_id, title, subject, edu_level, instructor,
               term, start_date, end_date, syllabus_text, notes_text
        FROM scholar_courses WHERE course_id = ?
    """, [course_id]).fetchone()
    con.close()
    if not row:
        return None
    return {
        "course_id": row[0], "student_id": row[1], "title": row[2],
        "subject": row[3], "edu_level": row[4], "instructor": row[5],
        "term": row[6], "start_date": row[7], "end_date": row[8],
        "syllabus_text": row[9] or "", "notes_text": row[10] or "",
    }


def delete_course(course_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM scholar_courses WHERE course_id = ?", [course_id])
    con.execute("DELETE FROM scholar_assignments WHERE course_id = ?", [course_id])
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# CRUD — Assignments
# ══════════════════════════════════════════════════════════════════════════════

def create_assignment(course_id: str, student_id: str, title: str,
                      description: str = "", due_date: str = "",
                      assignment_type: str = "homework",
                      priority: str = "medium") -> str:
    aid = f"asgn_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO scholar_assignments
            (assignment_id, course_id, student_id, title, description,
             due_date, assignment_type, priority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [aid, course_id, student_id, title, description,
          due_date or None, assignment_type, priority])
    con.close()
    return aid


def list_assignments(student_id: str, status_filter: str | None = None,
                     days_ahead: int = 30) -> list[dict]:
    """Return assignments for a student, ordered by due_date asc."""
    con = _con()
    query = """
        SELECT a.assignment_id, a.course_id, c.title AS course_title,
               a.title, a.description, a.due_date, a.assignment_type,
               a.priority, a.status
        FROM scholar_assignments a
        LEFT JOIN scholar_courses c ON a.course_id = c.course_id
        WHERE a.student_id = ?
    """
    params: list[Any] = [student_id]
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)
    if days_ahead:
        query += f" AND (a.due_date IS NULL OR a.due_date <= CURRENT_DATE + INTERVAL {int(days_ahead)} DAY)"
    query += " ORDER BY a.due_date ASC NULLS LAST"
    rows = con.execute(query, params).fetchall()
    con.close()
    return [
        {
            "assignment_id":   r[0],
            "course_id":       r[1],
            "course_title":    r[2] or "",
            "title":           r[3],
            "description":     r[4] or "",
            "due_date":        r[5],
            "assignment_type": r[6] or "homework",
            "priority":        r[7] or "medium",
            "status":          r[8] or "not_started",
        }
        for r in rows
    ]


def update_assignment_status(assignment_id: str, status: str) -> None:
    con = _con()
    con.execute("""
        UPDATE scholar_assignments SET status = ?, updated_ts = NOW()
        WHERE assignment_id = ?
    """, [status, assignment_id])
    con.close()


def delete_assignment(assignment_id: str) -> None:
    con = _con()
    con.execute("DELETE FROM scholar_assignments WHERE assignment_id = ?", [assignment_id])
    con.close()


def get_urgent_assignments(student_id: str, days: int = 7) -> list[dict]:
    """Assignments due in the next `days` days that are not done."""
    con = _con()
    rows = con.execute(f"""
        SELECT a.assignment_id, a.course_id, c.title AS course_title,
               a.title, a.due_date, a.assignment_type, a.priority, a.status
        FROM scholar_assignments a
        LEFT JOIN scholar_courses c ON a.course_id = c.course_id
        WHERE a.student_id = ?
          AND a.status NOT IN ('done', 'submitted')
          AND a.due_date IS NOT NULL
          AND a.due_date <= CURRENT_DATE + INTERVAL {int(days)} DAY
        ORDER BY a.due_date ASC
    """, [student_id]).fetchall()
    con.close()
    return [
        {
            "assignment_id": r[0], "course_id": r[1], "course_title": r[2] or "",
            "title": r[3], "due_date": r[4], "assignment_type": r[5] or "homework",
            "priority": r[6] or "medium", "status": r[7] or "not_started",
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Mastery Engine
# ══════════════════════════════════════════════════════════════════════════════

def record_mastery_event(student_id: str, topic: str, score: float,
                         correct: bool | None = None, source: str = "chat",
                         course_id: str = "", question_text: str = "",
                         answer_text: str = "", feedback_text: str = "") -> int:
    """Record one mastery observation, update SM-2 schedule. Returns new row id."""
    con = _con()
    row = con.execute("""
        INSERT INTO scholar_mastery
            (student_id, course_id, topic, source, score, correct,
             question_text, answer_text, feedback_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """, [student_id, course_id or None, topic, source, float(score),
          correct, question_text, answer_text, feedback_text]).fetchone()
    con.close()
    event_id = row[0] if row else -1
    _update_sm2(student_id, topic, float(score), correct)
    return event_id


def _update_sm2(student_id: str, topic: str, score: float,
                correct: bool | None) -> None:
    """Apply SM-2 algorithm to update the review schedule for a topic.

    Quality (q) is mapped 0-5 from score:
        score >= 0.9 → q=5, >=0.8→4, >=0.6→3, >=0.4→2, else→1
    SM-2 rules:
        correct (q>=3): interval *= ease_factor, ease_factor updated, reps++
        wrong   (q<3):  interval=1, reps=0, ease_factor max(1.3, ef-0.2)
    """
    # Map score to quality 0-5
    if score >= 0.9:
        q = 5
    elif score >= 0.8:
        q = 4
    elif score >= 0.6:
        q = 3
    elif score >= 0.4:
        q = 2
    else:
        q = 1

    con = _con()
    existing = con.execute(
        "SELECT ease_factor, interval_days, repetitions FROM scholar_review_schedule "
        "WHERE student_id=? AND topic=?",
        [student_id, topic],
    ).fetchone()

    if existing:
        ef, interval, reps = existing
    else:
        ef, interval, reps = 2.5, 1, 0

    if q >= 3:
        reps     += 1
        interval  = max(1, round(interval * ef)) if reps > 1 else 1
        ef        = max(1.3, ef + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    else:
        reps     = 0
        interval = 1
        ef       = max(1.3, ef - 0.2)

    from datetime import date, timedelta
    next_review = (date.today() + timedelta(days=int(interval))).isoformat()

    if existing:
        con.execute(
            """UPDATE scholar_review_schedule
               SET ease_factor=?, interval_days=?, repetitions=?,
                   next_review=?, last_review=NOW()
               WHERE student_id=? AND topic=?""",
            [ef, interval, reps, next_review, student_id, topic],
        )
    else:
        con.execute(
            """INSERT INTO scholar_review_schedule
               (student_id, topic, ease_factor, interval_days, repetitions, next_review, last_review)
               VALUES (?, ?, ?, ?, ?, ?, NOW())""",
            [student_id, topic, ef, interval, reps, next_review],
        )
    con.close()


def get_spaced_repetition_queue(student_id: str, limit: int = 10) -> list[dict]:
    """Return topics due for SM-2 review today (next_review <= today)."""
    con = _con()
    rows = con.execute(f"""
        SELECT rs.topic, rs.next_review, rs.interval_days, rs.ease_factor,
               rs.repetitions, COALESCE(m.avg_score, 0.5) AS avg_score
        FROM scholar_review_schedule rs
        LEFT JOIN (
            SELECT topic, AVG(score) AS avg_score
            FROM scholar_mastery
            WHERE student_id = ?
            GROUP BY topic
        ) m ON rs.topic = m.topic
        WHERE rs.student_id = ?
          AND rs.next_review <= CURRENT_DATE
        ORDER BY rs.next_review ASC
        LIMIT {int(limit)}
    """, [student_id, student_id]).fetchall()
    con.close()
    return [
        {
            "topic":         r[0],
            "next_review":   r[1],
            "interval_days": r[2],
            "ease_factor":   round(float(r[3] or 2.5), 2),
            "repetitions":   r[4] or 0,
            "avg_score":     round(float(r[5] or 0.5), 3),
        }
        for r in rows
    ]


def get_mastery_summary(student_id: str, limit: int = 40) -> list[dict]:
    """Return per-topic mastery averages, worst performers first."""
    con = _con()
    rows = con.execute("""
        SELECT topic,
               AVG(score)          AS avg_score,
               COUNT(*)            AS observations,
               SUM(CASE WHEN correct THEN 1 ELSE 0 END) AS correct_count,
               MAX(ts)             AS last_seen
        FROM scholar_mastery
        WHERE student_id = ?
        GROUP BY topic
        ORDER BY avg_score ASC
        LIMIT ?
    """, [student_id, limit]).fetchall()
    con.close()
    return [
        {
            "topic":         r[0],
            "avg_score":     round(float(r[1] or 0.5), 3),
            "observations":  r[2],
            "correct_count": r[3] or 0,
            "last_seen":     r[4],
        }
        for r in rows
    ]


def get_weak_topics(student_id: str, threshold: float = 0.65,
                    limit: int = 8) -> list[dict]:
    """Return topics where average mastery score is below threshold."""
    all_topics = get_mastery_summary(student_id, limit=100)
    return [t for t in all_topics if t["avg_score"] < threshold][:limit]


# ══════════════════════════════════════════════════════════════════════════════
# Chat sessions
# ══════════════════════════════════════════════════════════════════════════════

def new_chat_session(student_id: str = "", course_id: str = "",
                     edu_level: str = "high", subject: str = "",
                     help_mode: str = "guided") -> str:
    sid = f"chat_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO scholar_chat_sessions
            (session_id, student_id, course_id, edu_level, subject, help_mode)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [sid, student_id or None, course_id or None, edu_level, subject, help_mode])
    con.close()
    return sid


def save_chat_message(session_id: str, role: str, content: str,
                      mastery_id: int | None = None) -> None:
    con = _con()
    con.execute("""
        INSERT INTO scholar_chat_messages (session_id, role, content, mastery_id)
        VALUES (?, ?, ?, ?)
    """, [session_id, role, content, mastery_id])
    con.execute("""
        UPDATE scholar_chat_sessions
        SET message_count = message_count + 1
        WHERE session_id = ?
    """, [session_id])
    con.close()


def get_chat_history(session_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT role, content, ts FROM scholar_chat_messages
        WHERE session_id = ? ORDER BY id ASC
    """, [session_id]).fetchall()
    con.close()
    return [{"role": r[0], "content": r[1], "ts": r[2]} for r in rows]


def close_chat_session(session_id: str) -> None:
    con = _con()
    con.execute("""
        UPDATE scholar_chat_sessions
        SET ended_ts = NOW()
        WHERE session_id = ?
    """, [session_id])
    con.close()


def get_recent_sessions(student_id: str, limit: int = 10) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT session_id, subject, edu_level, help_mode, started_ts, message_count
        FROM scholar_chat_sessions
        WHERE student_id = ?
        ORDER BY started_ts DESC LIMIT ?
    """, [student_id, limit]).fetchall()
    con.close()
    return [
        {
            "session_id": r[0], "subject": r[1], "edu_level": r[2],
            "help_mode": r[3], "started_ts": r[4], "message_count": r[5],
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Quiz items + results
# ══════════════════════════════════════════════════════════════════════════════

def save_quiz_items(items: list[dict], student_id: str, course_id: str = "",
                    topic: str = "") -> list[str]:
    """Persist a list of quiz item dicts, return their item_ids."""
    ids = []
    con = _con()
    for item in items:
        iid = f"qi_{uuid.uuid4().hex[:8]}"
        con.execute("""
            INSERT INTO scholar_quiz_items
                (item_id, student_id, course_id, topic, question,
                 expected_answer, difficulty, item_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [iid, student_id, course_id or None,
              item.get("topic", topic), item.get("question", ""),
              item.get("expected_answer", item.get("answer", "")),
              item.get("difficulty", "medium"), item.get("type", "short_answer")])
        ids.append(iid)
    con.close()
    return ids


def record_quiz_result(item_id: str, student_id: str, student_answer: str,
                       score: float, correct: bool | None, feedback: str = "") -> None:
    con = _con()
    con.execute("""
        INSERT INTO scholar_quiz_results
            (item_id, student_id, student_answer, score, correct, feedback_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [item_id, student_id, student_answer, float(score), correct, feedback])
    con.close()


def get_quiz_performance(student_id: str, topic: str = "") -> dict:
    """Return accuracy stats for recent quiz attempts."""
    con = _con()
    query = """
        SELECT COUNT(*), SUM(CASE WHEN correct THEN 1 ELSE 0 END), AVG(score)
        FROM scholar_quiz_results qr
        JOIN scholar_quiz_items qi ON qr.item_id = qi.item_id
        WHERE qr.student_id = ?
    """
    params: list[Any] = [student_id]
    if topic:
        query += " AND qi.topic ILIKE ?"
        params.append(f"%{topic}%")
    row = con.execute(query, params).fetchone()
    con.close()
    total     = row[0] or 0
    correct   = row[1] or 0
    avg_score = float(row[2] or 0)
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "avg_score": round(avg_score, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Study session tracking
# ══════════════════════════════════════════════════════════════════════════════

def start_study_session(student_id: str, course_id: str = "", topic: str = "",
                        session_type: str = "tutor") -> int:
    con = _con()
    row = con.execute("""
        INSERT INTO scholar_study_sessions
            (student_id, course_id, topic, session_type)
        VALUES (?, ?, ?, ?)
        RETURNING id
    """, [student_id, course_id or None, topic, session_type]).fetchone()
    con.close()
    return row[0] if row else -1


def end_study_session(session_id: int, outcome: str = "completed",
                      notes: str = "") -> None:
    con = _con()
    con.execute("""
        UPDATE scholar_study_sessions
        SET ended_ts   = NOW(),
            duration_min = CAST(DATEDIFF('minute', started_ts, NOW()) AS INTEGER),
            outcome    = ?,
            notes      = ?
        WHERE id = ?
    """, [outcome, notes, session_id])
    con.close()


def get_study_stats(student_id: str, days: int = 30) -> dict:
    con = _con()
    row = con.execute(f"""
        SELECT COUNT(*) AS sessions,
               SUM(duration_min) AS total_min,
               AVG(duration_min) AS avg_min
        FROM scholar_study_sessions
        WHERE student_id = ?
          AND started_ts >= NOW() - INTERVAL {int(days)} DAY
    """, [student_id]).fetchone()
    con.close()
    return {
        "sessions":   row[0] or 0,
        "total_min":  int(row[1] or 0),
        "avg_min":    round(float(row[2] or 0), 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# System Prompt Routing
# ══════════════════════════════════════════════════════════════════════════════

_LEVEL_CONTEXT = {
    "elementary": (
        "The student is in elementary school (grades K-5). "
        "Use very simple language. Short sentences. Be warm, encouraging, and patient. "
        "Use analogies from everyday life. Never overwhelm. Always praise effort."
    ),
    "middle": (
        "The student is in middle school (grades 6-8). "
        "Be friendly and patient. Explain step by step. Use real-world examples. "
        "Build confidence. Match the student's course level."
    ),
    "high": (
        "The student is in high school (grades 9-12). "
        "Be clear and precise. Use course-level vocabulary. "
        "Connect to AP/IB standards where relevant. Challenge the student to think critically."
    ),
    "college": (
        "The student is in college (undergraduate). "
        "Be rigorous. Use technical vocabulary appropriate to the course. "
        "Expect the student to engage with course material. Push deeper understanding."
    ),
    "professional": (
        "The student is a graduate or professional-level learner. "
        "Be evidence-based, precise, and thorough. "
        "Cite reasoning chains. Acknowledge uncertainty. "
        "Help build expert-level mastery of the subject."
    ),
}

_HELP_MODE_INSTRUCTIONS = {
    "hint_only": (
        "IMPORTANT: Do NOT give the direct answer. "
        "Instead: ask Socratic questions, point to the relevant concept, "
        "and give a small nudge toward the next step. "
        "If the student is clearly stuck, give one small concrete hint. "
        "Never solve the problem for them."
    ),
    "guided": (
        "Guide the student step by step. "
        "Do NOT give the final answer directly. "
        "Explain the relevant concept first. Then walk through a SIMILAR example "
        "(not the exact problem). Ask the student to try each step. "
        "Correct misconceptions as they arise."
    ),
    "explain": (
        "Explain the concept fully and clearly. "
        "Use examples and analogies. "
        "At the end, work through a similar example to demonstrate. "
        "Do not directly solve the student's exact homework problem — "
        "help them understand so they can solve it themselves."
    ),
    "full": (
        "Give a full, complete explanation and solution. "
        "Show all steps. Explain the reasoning at each step. "
        "Point to any concepts the student should review for deeper understanding."
    ),
}

_SUBJECT_CONTEXT = {
    "Math":       "Focus on procedure clarity, correct notation, and conceptual understanding of why the method works.",
    "Algebra":    "Show algebraic steps explicitly. Check for sign errors and variable isolation.",
    "Geometry":   "Emphasize proof structure, theorems, and geometric intuition.",
    "Calculus":   "Emphasize limits, continuity, and notation precision. Show derivative/integral steps.",
    "Biology":    "Use correct biological vocabulary. Explain mechanisms and processes.",
    "Chemistry":  "Show balanced equations. Explain the underlying atomic/molecular mechanism.",
    "Physics":    "Set up the problem with a free-body diagram or diagram when helpful. Show units.",
    "English / Writing": "Focus on thesis clarity, evidence support, argument structure, and style.",
    "History":    "Contextualize events. Explain causes, consequences, and perspectives.",
    "Medical":    "Be evidence-based. Acknowledge clinical complexity and safety. Never provide patient-specific advice.",
    "Law":        "Ground in legal principles. Acknowledge jurisdiction variation. Do not provide legal advice.",
}


def build_tutor_system_prompt(
    edu_level: str,
    help_mode: str,
    subject: str = "",
    course_title: str = "",
    student_name: str = "",
) -> str:
    """Build the full system prompt for the tutor agent."""
    name_part = f" Your student's name is {student_name}." if student_name else ""
    course_part = f" The current course is: {course_title}." if course_title else ""
    subject_hint = _SUBJECT_CONTEXT.get(subject, "")
    subject_part = f" {subject_hint}" if subject_hint else ""

    level_ctx   = _LEVEL_CONTEXT.get(edu_level, _LEVEL_CONTEXT["high"])
    mode_instr  = _HELP_MODE_INSTRUCTIONS.get(help_mode, _HELP_MODE_INSTRUCTIONS["guided"])

    return (
        f"You are a dedicated, expert academic tutor powered by Titans Forge Scholar.{name_part}\n\n"
        f"STUDENT LEVEL: {level_ctx}\n\n"
        f"TUTOR MODE: {mode_instr}\n\n"
        f"{course_part}{subject_part}\n\n"
        "Always be encouraging. Detect confusion early and address misconceptions directly. "
        "Never mock or dismiss a wrong answer — use it as a teaching moment. "
        "After your response, if appropriate, suggest one follow-up question the student should think about."
    ).strip()


def build_quiz_generation_prompt(
    topic: str,
    edu_level: str,
    subject: str = "",
    num_questions: int = 5,
    difficulty: str = "medium",
    course_context: str = "",
) -> str:
    """Build the prompt to ask the local model to generate quiz questions."""
    level_label = EDU_LABELS.get(edu_level, edu_level)
    course_note = f"Course context:\n{course_context[:1000]}\n\n" if course_context else ""

    return (
        f"You are a quiz generator for {level_label} students studying {subject or topic}.\n\n"
        f"{course_note}"
        f"Generate exactly {num_questions} {difficulty}-difficulty short-answer quiz questions "
        f"on the topic: \"{topic}\".\n\n"
        "For each question output EXACTLY this JSON object (one per line, no extra text):\n"
        '{"question": "<question text>", "answer": "<expected answer>", '
        '"difficulty": "<easy|medium|hard>", "topic": "<topic>"}\n\n'
        "Rules:\n"
        "- Questions must be appropriate for the level\n"
        "- Answers should be concise but complete\n"
        "- Cover different aspects of the topic\n"
        "- Output ONLY the JSON lines, nothing else before or after"
    )


def build_grade_answer_prompt(
    question: str,
    expected_answer: str,
    student_answer: str,
    edu_level: str = "high",
) -> str:
    """Build the prompt to grade a student's answer and give feedback."""
    return (
        f"You are grading a student answer at the {EDU_LABELS.get(edu_level, edu_level)} level.\n\n"
        f"Question: {question}\n"
        f"Expected answer: {expected_answer}\n"
        f"Student's answer: {student_answer}\n\n"
        "Grade this answer and respond with ONLY this JSON object:\n"
        '{"score": <0.0-1.0>, "correct": <true|false>, '
        '"feedback": "<brief encouraging feedback, point out what is right and what is missing>"}\n\n'
        "- score 1.0 = fully correct, 0.5 = partially correct, 0.0 = incorrect\n"
        "- Be encouraging even when wrong\n"
        "- Output ONLY the JSON, nothing else"
    )


def build_study_plan_prompt(
    student_name: str,
    edu_level: str,
    assignments: list[dict],
    weak_topics: list[dict],
    study_stats: dict,
    available_minutes: int = 90,
) -> str:
    """Build the prompt to generate a personalized daily study plan."""
    level_label = EDU_LABELS.get(edu_level, edu_level)
    asgn_lines = "\n".join(
        f"- {a['title']} ({a['course_title']}) — due {a['due_date']} [{a['priority']} priority, {a['status']}]"
        for a in assignments[:10]
    ) or "No upcoming assignments."
    weak_lines = "\n".join(
        f"- {t['topic']}: {t['avg_score']*100:.0f}% mastery ({t['observations']} data points)"
        for t in weak_topics[:6]
    ) or "No weak topics detected yet."

    return (
        f"You are building a personalized study plan for {student_name}, a {level_label} student.\n\n"
        f"Available study time today: {available_minutes} minutes\n\n"
        f"UPCOMING ASSIGNMENTS:\n{asgn_lines}\n\n"
        f"WEAKEST TOPICS (needs review):\n{weak_lines}\n\n"
        f"RECENT STUDY ACTIVITY: {study_stats.get('sessions', 0)} sessions, "
        f"{study_stats.get('total_min', 0)} total minutes in last 30 days.\n\n"
        "Create a specific study plan for TODAY. Respond with ONLY a JSON object:\n"
        '{"summary": "<1-sentence summary>", "sessions": ['
        '{"topic": "<topic>", "duration_min": <int>, "activity": "<what to do>", '
        '"priority": "<urgent|high|medium>", "reason": "<why this matters today>"}]}\n\n'
        "Rules:\n"
        "- Total duration_min must not exceed the available time\n"
        "- Prioritize items due soon or critical weaknesses\n"
        "- Be specific about the activity (not just 'study' — say 'practice factoring problems')\n"
        "- Output ONLY the JSON, nothing else"
    )


# ══════════════════════════════════════════════════════════════════════════════
# JSON parsing helpers
# ══════════════════════════════════════════════════════════════════════════════

def _json_load(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def parse_quiz_items(raw_output: str, topic: str = "") -> list[dict]:
    """Parse line-delimited JSON quiz items from model output."""
    items = []
    for line in raw_output.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if "question" in obj:
                obj.setdefault("topic", topic)
                items.append(obj)
        except Exception:
            pass
    return items


def parse_grade_result(raw_output: str) -> dict:
    """Parse the grading JSON from model output."""
    raw = raw_output.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {"score": 0.5, "correct": None, "feedback": raw[:200]}
    try:
        return json.loads(raw[start:end])
    except Exception:
        return {"score": 0.5, "correct": None, "feedback": raw[:200]}


def parse_study_plan(raw_output: str) -> dict:
    """Parse the study plan JSON from model output."""
    raw = raw_output.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {"summary": "Could not generate plan.", "sessions": []}
    try:
        return json.loads(raw[start:end])
    except Exception:
        return {"summary": "Could not parse plan.", "sessions": []}


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard summary helper
# ══════════════════════════════════════════════════════════════════════════════

def get_scholar_dashboard_data(student_id: str) -> dict:
    """One-call snapshot for the Student Home dashboard."""
    student     = get_student(student_id)
    courses     = list_courses(student_id)
    urgent      = get_urgent_assignments(student_id, days=7)
    all_asgn    = list_assignments(student_id, days_ahead=30)
    weak        = get_weak_topics(student_id)
    due_review  = get_spaced_repetition_queue(student_id, limit=5)
    stats       = get_study_stats(student_id, days=30)
    quiz_perf   = get_quiz_performance(student_id)

    return {
        "student":      student,
        "courses":      courses,
        "urgent":       urgent,
        "assignments":  all_asgn,
        "weak_topics":  weak,
        "due_review":   due_review,
        "study_stats":  stats,
        "quiz_perf":    quiz_perf,
    }
