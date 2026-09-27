"""
forge_admin.py — Titans Forge Scholar: Administrator / Principal Backend
=========================================================================

School-level data aggregation layer.
Sits above forge_teacher.py — reads teacher data, never modifies it.

Tables (in scholar.duckdb):
  admin_profiles       — principal / VP accounts
  schools              — school definitions
  school_classes_link  — maps teacher_classes → school_id
  admin_observations   — classroom walkthrough / observation records
  pd_records           — professional development tracking
  school_announcements — broadcast messages to all teachers
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from forge_scholar import SCHOLAR_DB

ADMIN_ROLES = ["principal", "vice_principal", "department_head", "admin_staff"]
OBSERVATION_TYPES = ["walkthrough", "formal", "informal", "peer", "self"]
REPORT_TYPES = [
    "school_board",
    "state_compliance",
    "parent_newsletter",
    "staff_briefing",
    "department_review",
    "custom",
]
GRADE_BANDS = ["K–2", "3–5", "6–8", "9–12", "K–12", "Higher Ed", "Mixed"]


def _con() -> duckdb.DuckDBPyConnection:
    SCHOLAR_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(SCHOLAR_DB))


def init_admin_db() -> None:
    con = _con()

    con.execute("""
        CREATE TABLE IF NOT EXISTS schools (
            school_id       TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            district_id     TEXT DEFAULT '',
            grade_bands     TEXT DEFAULT '',
            enrollment      INTEGER DEFAULT 0,
            address         TEXT DEFAULT '',
            principal_name  TEXT DEFAULT '',
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS admin_profiles (
            admin_id        TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            role            TEXT DEFAULT 'principal',
            school_id       TEXT NOT NULL,
            email           TEXT DEFAULT '',
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS school_classes_link (
            link_id         TEXT PRIMARY KEY,
            school_id       TEXT NOT NULL,
            class_id        TEXT NOT NULL,
            teacher_id      TEXT NOT NULL,
            linked_ts       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(school_id, class_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS admin_observations (
            obs_id          TEXT PRIMARY KEY,
            school_id       TEXT NOT NULL,
            teacher_id      TEXT NOT NULL,
            admin_id        TEXT NOT NULL,
            obs_type        TEXT DEFAULT 'walkthrough',
            class_id        TEXT DEFAULT '',
            rating          INTEGER DEFAULT 3,
            strengths       TEXT DEFAULT '',
            growth_areas    TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            follow_up       TEXT DEFAULT '',
            observed_date   DATE,
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS pd_records (
            pd_id           TEXT PRIMARY KEY,
            school_id       TEXT NOT NULL,
            teacher_id      TEXT NOT NULL,
            title           TEXT NOT NULL,
            pd_type         TEXT DEFAULT 'workshop',
            hours           FLOAT DEFAULT 0.0,
            provider        TEXT DEFAULT '',
            completed_date  DATE,
            notes           TEXT DEFAULT '',
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS school_announcements (
            ann_id          TEXT PRIMARY KEY,
            school_id       TEXT NOT NULL,
            admin_id        TEXT NOT NULL,
            title           TEXT NOT NULL,
            body            TEXT DEFAULT '',
            priority        TEXT DEFAULT 'normal',
            target_role     TEXT DEFAULT 'all',
            created_ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.close()


# ── School CRUD ────────────────────────────────────────────────────────────────
def create_school(name: str, district_id: str = "", grade_bands: str = "K–12",
                  enrollment: int = 0, address: str = "",
                  principal_name: str = "") -> str:
    sid = f"sch_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO schools (school_id, name, district_id, grade_bands,
                             enrollment, address, principal_name)
        VALUES (?,?,?,?,?,?,?)
    """, [sid, name, district_id, grade_bands, enrollment, address, principal_name])
    con.close()
    return sid


def list_schools(district_id: str = "") -> list[dict]:
    con = _con()
    q = "SELECT * FROM schools"
    params: list[Any] = []
    if district_id:
        q += " WHERE district_id=?"
        params.append(district_id)
    q += " ORDER BY name"
    rows = con.execute(q, params).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


def get_school(school_id: str) -> dict | None:
    con = _con()
    row = con.execute("SELECT * FROM schools WHERE school_id=?", [school_id]).fetchone()
    desc = [d[0] for d in con.description] if row else []
    con.close()
    return dict(zip(desc, row)) if row else None


def update_school(school_id: str, **kwargs: Any) -> None:
    allowed = {"name","district_id","grade_bands","enrollment","address","principal_name"}
    con = _con()
    for k, v in kwargs.items():
        if k in allowed:
            con.execute(f"UPDATE schools SET {k}=? WHERE school_id=?", [v, school_id])
    con.close()


# ── Admin profiles ─────────────────────────────────────────────────────────────
def create_admin(display_name: str, school_id: str,
                  role: str = "principal", email: str = "") -> str:
    aid = f"adm_{uuid.uuid4().hex[:10]}"
    con = _con()
    con.execute("""
        INSERT INTO admin_profiles (admin_id, display_name, role, school_id, email)
        VALUES (?,?,?,?,?)
    """, [aid, display_name, role, school_id, email])
    con.close()
    return aid


def list_admins(school_id: str = "") -> list[dict]:
    con = _con()
    q = "SELECT * FROM admin_profiles"
    params: list[Any] = []
    if school_id:
        q += " WHERE school_id=?"
        params.append(school_id)
    q += " ORDER BY display_name"
    rows = con.execute(q, params).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


# ── Class linking ─────────────────────────────────────────────────────────────
def link_class_to_school(school_id: str, class_id: str,
                          teacher_id: str) -> None:
    lid = f"lnk_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT OR IGNORE INTO school_classes_link
            (link_id, school_id, class_id, teacher_id)
        VALUES (?,?,?,?)
    """, [lid, school_id, class_id, teacher_id])
    con.close()


def unlink_class(school_id: str, class_id: str) -> None:
    con = _con()
    con.execute(
        "DELETE FROM school_classes_link WHERE school_id=? AND class_id=?",
        [school_id, class_id]
    )
    con.close()


def list_school_classes(school_id: str) -> list[dict]:
    """Return all teacher_classes linked to this school with teacher info."""
    con = _con()
    rows = con.execute("""
        SELECT tc.class_id, tc.teacher_id, tc.name, tc.subject,
               tc.grade_level, tc.term, tc.notes AS description,
               COALESCE(tp.display_name, tc.teacher_id) as teacher_name,
               l.linked_ts
        FROM school_classes_link l
        JOIN teacher_classes tc ON l.class_id = tc.class_id
        LEFT JOIN teacher_profiles tp ON tc.teacher_id = tp.teacher_id
        WHERE l.school_id=?
        ORDER BY tc.subject, tc.name
    """, [school_id]).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


# ── School-wide analytics ─────────────────────────────────────────────────────
def school_performance_summary(school_id: str) -> dict:
    """
    Aggregate mastery and grade data across all classes linked to school.
    Returns high-level KPIs.
    """
    classes = list_school_classes(school_id)
    if not classes:
        return {"total_students": 0, "avg_mastery": 0,
                "at_risk_count": 0, "total_classes": 0}

    class_ids = [c["class_id"] for c in classes]
    con = _con()

    # Total enrolled students
    placeholders = ",".join("?" * len(class_ids))
    total_students = con.execute(f"""
        SELECT COUNT(DISTINCT student_id)
        FROM class_members
        WHERE class_id IN ({placeholders})
    """, class_ids).fetchone()[0] or 0

    # Average mastery (from scholar_mastery)
    avg_mastery = con.execute(f"""
        SELECT AVG(avg_score)
        FROM (
            SELECT student_id, AVG(score) as avg_score
            FROM scholar_mastery
            WHERE student_id IN (
                SELECT DISTINCT student_id FROM class_members
                WHERE class_id IN ({placeholders})
            )
            GROUP BY student_id
        )
    """, class_ids).fetchone()[0] or 0

    # At-risk: students below 60% avg mastery
    at_risk_count = con.execute(f"""
        SELECT COUNT(*)
        FROM (
            SELECT student_id, AVG(score) as avg_score
            FROM scholar_mastery
            WHERE student_id IN (
                SELECT DISTINCT student_id FROM class_members
                WHERE class_id IN ({placeholders})
            )
            GROUP BY student_id
            HAVING avg_score < 0.6
        )
    """, class_ids).fetchone()[0] or 0

    # Intervention plans active
    active_interventions = con.execute(f"""
        SELECT COUNT(*)
        FROM intervention_plans
        WHERE class_id IN ({placeholders}) AND status='active'
    """, class_ids).fetchone()[0] or 0

    # Open assignments
    open_assignments = con.execute(f"""
        SELECT COUNT(*) FROM assignments
        WHERE class_id IN ({placeholders}) AND status='published'
    """, class_ids).fetchone()[0] or 0

    con.close()
    return {
        "total_classes":       len(classes),
        "total_students":      total_students,
        "avg_mastery_pct":     round(avg_mastery * 100, 1),
        "at_risk_count":       at_risk_count,
        "active_interventions": active_interventions,
        "open_assignments":    open_assignments,
    }


def school_at_risk_rollup(school_id: str,
                           mastery_threshold: float = 0.6) -> list[dict]:
    """All at-risk students across the school with class context."""
    classes = list_school_classes(school_id)
    if not classes:
        return []
    class_ids = [c["class_id"] for c in classes]
    class_map = {c["class_id"]: c for c in classes}
    placeholders = ",".join("?" * len(class_ids))
    con = _con()
    rows = con.execute(f"""
        SELECT cm.student_id, cm.class_id,
               COALESCE(s.display_name, cm.student_id) as student_name,
               s.grade_level,
               AVG(m.score) as avg_mastery,
               COUNT(DISTINCT CASE WHEN m.score < {mastery_threshold} THEN m.topic END) as weak_topics
        FROM class_members cm
        LEFT JOIN scholar_students s ON cm.student_id = s.student_id
        LEFT JOIN scholar_mastery m ON cm.student_id = m.student_id
        WHERE cm.class_id IN ({placeholders})
        GROUP BY cm.student_id, cm.class_id, s.display_name, s.grade_level
        HAVING avg_mastery < {mastery_threshold} OR avg_mastery IS NULL
        ORDER BY avg_mastery ASC NULLS FIRST
    """, class_ids).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    result = []
    for r in rows:
        d = dict(zip(desc, r))
        d["class_name"]   = class_map.get(d["class_id"], {}).get("name","")
        d["teacher_name"] = class_map.get(d["class_id"], {}).get("teacher_name","")
        d["avg_mastery_pct"] = round((d.get("avg_mastery") or 0) * 100, 1)
        result.append(d)
    return result


def school_teacher_summary(school_id: str) -> list[dict]:
    """Per-teacher aggregate: class count, avg student mastery, open alerts."""
    classes = list_school_classes(school_id)
    if not classes:
        return []

    from itertools import groupby
    teacher_classes_map: dict[str, list[dict]] = {}
    for c in classes:
        tid = c["teacher_id"]
        teacher_classes_map.setdefault(tid, []).append(c)

    con = _con()
    result = []
    for tid, t_classes in teacher_classes_map.items():
        class_ids = [c["class_id"] for c in t_classes]
        ph = ",".join("?" * len(class_ids))
        teacher_name = t_classes[0].get("teacher_name", tid)

        # Avg mastery
        avg_m = con.execute(f"""
            SELECT AVG(score) FROM scholar_mastery
            WHERE student_id IN (
                SELECT DISTINCT student_id FROM class_members
                WHERE class_id IN ({ph})
            )
        """, class_ids).fetchone()[0] or 0

        # Open assignments
        open_a = con.execute(f"""
            SELECT COUNT(*) FROM assignments
            WHERE class_id IN ({ph}) AND status='published'
        """, class_ids).fetchone()[0] or 0

        # Active intervention plans
        active_ip = con.execute(f"""
            SELECT COUNT(*) FROM intervention_plans
            WHERE class_id IN ({ph}) AND status='active'
        """, class_ids).fetchone()[0] or 0

        # Unacknowledged alerts
        alerts = con.execute("""
            SELECT COUNT(*) FROM teacher_alerts
            WHERE teacher_id=? AND acknowledged=FALSE
        """, [tid]).fetchone()[0] or 0

        result.append({
            "teacher_id":   tid,
            "teacher_name": teacher_name,
            "class_count":  len(t_classes),
            "subjects":     list({c["subject"] for c in t_classes if c["subject"]}),
            "avg_mastery_pct": round(avg_m * 100, 1),
            "open_assignments": open_a,
            "active_interventions": active_ip,
            "unack_alerts": alerts,
        })
    con.close()
    return sorted(result, key=lambda x: x["avg_mastery_pct"])


def school_subject_performance(school_id: str) -> list[dict]:
    """Per-subject avg mastery across all classes at school."""
    classes = list_school_classes(school_id)
    if not classes:
        return []

    subjects: dict[str, list[str]] = {}
    for c in classes:
        subj = c.get("subject","Unknown") or "Unknown"
        subjects.setdefault(subj, []).append(c["class_id"])

    con = _con()
    result = []
    for subj, cids in subjects.items():
        ph = ",".join("?" * len(cids))
        avg_m = con.execute(f"""
            SELECT AVG(score) FROM scholar_mastery
            WHERE student_id IN (
                SELECT DISTINCT student_id FROM class_members
                WHERE class_id IN ({ph})
            )
        """, cids).fetchone()[0] or 0
        student_count = con.execute(f"""
            SELECT COUNT(DISTINCT student_id) FROM class_members
            WHERE class_id IN ({ph})
        """, cids).fetchone()[0] or 0
        result.append({
            "subject":      subj,
            "class_count":  len(cids),
            "student_count": student_count,
            "avg_mastery_pct": round(avg_m * 100, 1),
        })
    con.close()
    return sorted(result, key=lambda x: x["avg_mastery_pct"])


def school_standards_coverage(school_id: str) -> dict[str, list[dict]]:
    """Aggregate standards coverage across all teachers at school."""
    classes = list_school_classes(school_id)
    if not classes:
        return {}
    class_ids = [c["class_id"] for c in classes]
    ph = ",".join("?" * len(class_ids))
    con = _con()
    rows = con.execute(f"""
        SELECT standard_code, standard_desc,
               coverage_level, COUNT(*) as teacher_count
        FROM standards_coverage
        WHERE class_id IN ({ph})
        GROUP BY standard_code, standard_desc, coverage_level
        ORDER BY standard_code
    """, class_ids).fetchall()
    con.close()
    # Group by standard
    standards: dict[str, dict] = {}
    for code, desc, level, cnt in rows:
        if code not in standards:
            standards[code] = {"code": code, "desc": desc, "levels": {}}
        standards[code]["levels"][level] = int(cnt)
    # Determine dominant coverage level
    level_priority = {"mastered":3,"covered":2,"in_progress":1,"not_started":0}
    result = []
    for code, s in standards.items():
        dominant = max(s["levels"], key=lambda l: level_priority.get(l,0))
        result.append({
            "standard_code": code,
            "standard_desc": s["desc"],
            "coverage_level": dominant,
            "teacher_count":  sum(s["levels"].values()),
        })
    return {"standards": result}


# ── Observations ──────────────────────────────────────────────────────────────
def save_observation(school_id: str, teacher_id: str, admin_id: str,
                      obs_type: str = "walkthrough",
                      class_id: str = "", rating: int = 3,
                      strengths: str = "", growth_areas: str = "",
                      notes: str = "", follow_up: str = "",
                      observed_date: date | None = None) -> str:
    oid = f"obs_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO admin_observations
            (obs_id, school_id, teacher_id, admin_id, obs_type,
             class_id, rating, strengths, growth_areas, notes,
             follow_up, observed_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [oid, school_id, teacher_id, admin_id, obs_type,
          class_id, rating, strengths, growth_areas, notes,
          follow_up, observed_date or date.today()])
    con.close()
    return oid


def list_observations(school_id: str, teacher_id: str = "") -> list[dict]:
    con = _con()
    q = """
        SELECT o.*, COALESCE(tp.display_name, o.teacher_id) as teacher_name
        FROM admin_observations o
        LEFT JOIN teacher_profiles tp ON o.teacher_id = tp.teacher_id
        WHERE o.school_id=?
    """
    params: list[Any] = [school_id]
    if teacher_id:
        q += " AND o.teacher_id=?"
        params.append(teacher_id)
    q += " ORDER BY o.observed_date DESC"
    rows = con.execute(q, params).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


# ── PD Records ────────────────────────────────────────────────────────────────
def save_pd_record(school_id: str, teacher_id: str, title: str,
                    pd_type: str = "workshop", hours: float = 1.0,
                    provider: str = "", completed_date: date | None = None,
                    notes: str = "") -> str:
    pid = f"pd_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO pd_records
            (pd_id, school_id, teacher_id, title, pd_type,
             hours, provider, completed_date, notes)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [pid, school_id, teacher_id, title, pd_type,
          hours, provider, completed_date or date.today(), notes])
    con.close()
    return pid


def pd_summary(school_id: str) -> list[dict]:
    """PD hours per teacher."""
    con = _con()
    rows = con.execute("""
        SELECT p.teacher_id,
               COALESCE(tp.display_name, p.teacher_id) as teacher_name,
               SUM(p.hours) as total_hours,
               COUNT(*) as sessions,
               MAX(p.completed_date) as last_completed
        FROM pd_records p
        LEFT JOIN teacher_profiles tp ON p.teacher_id = tp.teacher_id
        WHERE p.school_id=?
        GROUP BY p.teacher_id, tp.display_name
        ORDER BY total_hours DESC
    """, [school_id]).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


# ── Announcements ─────────────────────────────────────────────────────────────
def post_announcement(school_id: str, admin_id: str, title: str,
                       body: str, priority: str = "normal",
                       target_role: str = "all") -> str:
    aid = f"ann_{uuid.uuid4().hex[:8]}"
    con = _con()
    con.execute("""
        INSERT INTO school_announcements
            (ann_id, school_id, admin_id, title, body, priority, target_role)
        VALUES (?,?,?,?,?,?,?)
    """, [aid, school_id, admin_id, title, body, priority, target_role])
    con.close()
    return aid


def list_announcements(school_id: str) -> list[dict]:
    con = _con()
    rows = con.execute("""
        SELECT * FROM school_announcements
        WHERE school_id=? ORDER BY created_ts DESC LIMIT 20
    """, [school_id]).fetchall()
    desc = [d[0] for d in con.description]
    con.close()
    return [dict(zip(desc, r)) for r in rows]


# ── AI Prompt Builders ────────────────────────────────────────────────────────
def school_report_prompt(school_name: str, report_type: str,
                          summary: dict, at_risk_count: int,
                          teacher_count: int, date_range: str = "current") -> str:
    type_desc = {
        "school_board":    "a formal board report suitable for a school board meeting",
        "state_compliance":"a state/district compliance summary highlighting key metrics",
        "parent_newsletter":"a warm, accessible parent newsletter",
        "staff_briefing":  "a concise staff briefing for teachers",
        "department_review":"a department performance review",
        "custom":          "a comprehensive school performance report",
    }.get(report_type, "a school performance report")

    avg_m  = summary.get("avg_mastery_pct", 0)
    n_stu  = summary.get("total_students", 0)
    n_cls  = summary.get("total_classes", 0)
    n_int  = summary.get("active_interventions", 0)

    return (
        f"You are a professional school administrator drafting {type_desc}.\n"
        f"School: {school_name} | Period: {date_range}\n\n"
        f"KEY METRICS:\n"
        f"  Total students:        {n_stu}\n"
        f"  Total classes:         {n_cls}\n"
        f"  Teacher count:         {teacher_count}\n"
        f"  Average mastery:       {avg_m:.1f}%\n"
        f"  At-risk students:      {at_risk_count}\n"
        f"  Active interventions:  {n_int}\n\n"
        f"Write a complete, professional {report_type.replace('_',' ')} report. Include:\n"
        f"1. EXECUTIVE SUMMARY (2–3 paragraphs)\n"
        f"2. STUDENT PERFORMANCE (data-driven analysis)\n"
        f"3. AT-RISK POPULATION (status and action being taken)\n"
        f"4. STRENGTHS & HIGHLIGHTS\n"
        f"5. AREAS OF FOCUS (what's being addressed)\n"
        f"6. NEXT STEPS & COMMITMENTS\n\n"
        f"Tone: professional, data-backed, and constructively forward-looking."
    )


def ai_admin_brief_prompt(school_name: str, summary: dict,
                           teacher_summaries: list[dict],
                           at_risk_students: list[dict]) -> str:
    top_concerns = []
    for t in teacher_summaries[:3]:
        if t.get("avg_mastery_pct", 100) < 65:
            top_concerns.append(
                f"{t['teacher_name']} ({t.get('avg_mastery_pct',0):.0f}% avg mastery)"
            )
    concerns_str = "; ".join(top_concerns) or "No major concerns identified"
    at_risk_n    = len(at_risk_students)

    return (
        f"You are an expert instructional coach advising a school principal.\n"
        f"School: {school_name}\n"
        f"School-wide avg mastery: {summary.get('avg_mastery_pct',0):.1f}%\n"
        f"At-risk students: {at_risk_n}\n"
        f"Active interventions: {summary.get('active_interventions',0)}\n"
        f"Classes with performance concerns: {concerns_str}\n\n"
        f"Write a brief, actionable daily brief for the principal covering:\n"
        f"1. TODAY'S PRIORITY: What deserves immediate attention?\n"
        f"2. POSITIVE TRENDS: What's working across the school?\n"
        f"3. 3 QUICK WINS: Actions the principal can take today\n"
        f"4. WATCH LIST: Students or classes to check on this week\n\n"
        f"Be concise, direct, and practical."
    )
