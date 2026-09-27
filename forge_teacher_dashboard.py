"""
forge_teacher_dashboard.py - snapshot + demo data for Teacher Home.

Keeps the Streamlit page presentation-focused while centralising the
classroom intelligence queries that power the educator command center.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

import duckdb

from forge_admin import init_admin_db
from forge_assignments import init_assignments_db
from forge_scholar import SCHOLAR_DB, init_scholar_db
from forge_teacher import (
    acknowledge_alert,
    at_risk_students,
    class_mastery_heatmap,
    init_teacher_db,
    list_alerts,
    list_ai_artifact_drafts,
    list_classes,
    list_class_students,
    list_lessons_for_teacher,
    list_teachers,
    list_teacher_actions,
    resolve_teacher_action,
)

DEMO_TEACHER_ID = "tchr_demo_titans_forge"
DEMO_CLASS_PREFIX = "cls_demo_tf_"
DEMO_STUDENT_PREFIX = "stu_demo_tf_"
DEMO_SCHOOL_ID = "sch_demo_titans_forge"
DEMO_ADMIN_ID = "adm_demo_titans_forge"


def _con() -> duckdb.DuckDBPyConnection:
    SCHOLAR_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(SCHOLAR_DB))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _pct(value: float | int | None) -> int:
    return round(float(value or 0) * 100)


def _score_band(score: float) -> str:
    if score >= 0.78:
        return "ready"
    if score >= 0.62:
        return "watch"
    return "urgent"


def _subject_matter_brief(cls: dict[str, Any], topics: list[dict[str, Any]]) -> dict[str, Any]:
    topic = (topics[0]["topic"] if topics else "Core skill").strip()
    score = float(topics[0]["score"] if topics else 0)
    subject = cls.get("subject", "General")

    subject_templates = {
        "Biology": {
            "standard": "NGSS.HS-LS1-7",
            "learning_target": "Use evidence to explain how matter and energy move through cellular processes.",
            "misconception": "Students often name the inputs and outputs without explaining the energy transfer.",
            "teacher_move": "Ask students to trace one carbon atom and one energy transfer through the model.",
            "check_question": "In a yeast respiration lab, what evidence would show that energy transfer occurred?",
            "exit_ticket": "Explain how one observation from the lab supports a claim about cellular respiration.",
            "vocab": ["glucose", "ATP", "carbon dioxide"],
            "artifact": "annotated lab model",
        },
        "Mathematics": {
            "standard": "CCSS.MATH.HSA-REI.C.6",
            "learning_target": "Choose and justify a strategy for solving a system of linear equations.",
            "misconception": "Students treat slope and intercept as labels instead of quantities with meaning.",
            "teacher_move": "Have students compare two solution paths and defend which one is more efficient.",
            "check_question": "A line has slope 3 and crosses y at -2. What changes in the equation and graph?",
            "exit_ticket": "Solve one system and write why your chosen strategy was efficient.",
            "vocab": ["slope", "intercept", "solution"],
            "artifact": "worked example with strategy note",
        },
        "English Language Arts": {
            "standard": "CCSS.ELA-LITERACY.RL.9-10.1",
            "learning_target": "Build an evidence chain that connects a theme claim to precise textual details.",
            "misconception": "Students quote a strong line but leave the reasoning between evidence and theme implicit.",
            "teacher_move": "Model the missing because-clause between a quote and the theme claim.",
            "check_question": "Which sentence best explains how the quote proves the theme rather than restating it?",
            "exit_ticket": "Write a claim, embed one quote, and add a because-clause that explains the connection.",
            "vocab": ["claim", "evidence", "commentary"],
            "artifact": "evidence chain paragraph",
        },
        "Social Studies": {
            "standard": "C3.D2.His.14.9-12",
            "learning_target": "Evaluate competing civic claims by weighing source evidence, context, and consequences.",
            "misconception": "Students treat a source's point of view as proof that the source is unreliable rather than evidence to interpret.",
            "teacher_move": "Place two sources side by side and separate claim, evidence, perspective, and limitation.",
            "check_question": "Which piece of evidence most directly supports the claim about how an institution shaped the outcome?",
            "exit_ticket": "Write one civic claim, cite two pieces of evidence, and explain one source limitation.",
            "vocab": ["claim", "context", "perspective"],
            "artifact": "source comparison brief",
        },
    }
    template = subject_templates.get(
        subject,
        {
            "standard": cls.get("standards_set") or "Course priority standard",
            "learning_target": f"Explain and apply the core idea behind {topic}.",
            "misconception": "Students can complete familiar examples but struggle to explain the underlying reasoning.",
            "teacher_move": "Use one worked example, one non-example, and one student explanation repair.",
            "check_question": f"What is the most important idea someone must understand to use {topic} correctly?",
            "exit_ticket": f"Explain {topic} in your own words and apply it to one new example.",
            "vocab": ["claim", "evidence", "strategy"],
            "artifact": "reasoning check",
        },
    )
    return {
        "class_id": cls["class_id"],
        "class_name": cls["name"],
        "subject": subject,
        "grade_level": cls.get("grade_level", ""),
        "topic": topic,
        "score": score,
        "mastery_pct": _pct(score),
        **template,
    }


def seed_titans_forge_teacher_demo() -> str:
    """Reset and seed a polished demo classroom without touching real data."""
    init_scholar_db()
    init_teacher_db()
    init_assignments_db()
    init_admin_db()

    today = date.today()
    now = datetime.now()
    con = _con()

    # Clear only deterministic demo rows, including linked workflow objects.
    con.execute(
        "DELETE FROM submission_feedback WHERE assignment_id LIKE ?",
        ["asgn_demo_tf_%"],
    )
    con.execute(
        "DELETE FROM student_submissions WHERE assignment_id LIKE ?",
        ["asgn_demo_tf_%"],
    )
    con.execute("DELETE FROM assignments WHERE assignment_id LIKE ?", ["asgn_demo_tf_%"])
    con.execute("DELETE FROM intervention_progress WHERE plan_id LIKE ?", ["ip_demo_tf_%"])
    con.execute("DELETE FROM intervention_plans WHERE class_id LIKE ?", [DEMO_CLASS_PREFIX + "%"])
    con.execute("DELETE FROM standards_coverage WHERE class_id LIKE ?", [DEMO_CLASS_PREFIX + "%"])
    con.execute("DELETE FROM parent_reports WHERE class_id LIKE ?", [DEMO_CLASS_PREFIX + "%"])
    con.execute("DELETE FROM class_communications WHERE teacher_id=?", [DEMO_TEACHER_ID])
    con.execute("DELETE FROM teacher_resources WHERE teacher_id=?", [DEMO_TEACHER_ID])
    con.execute("DELETE FROM teacher_action_items WHERE teacher_id=?", [DEMO_TEACHER_ID])
    con.execute("DELETE FROM ai_artifact_drafts WHERE teacher_id=?", [DEMO_TEACHER_ID])
    con.execute("DELETE FROM student_evidence_events WHERE teacher_id=?", [DEMO_TEACHER_ID])
    con.execute("DELETE FROM school_classes_link WHERE class_id LIKE ?", [DEMO_CLASS_PREFIX + "%"])
    con.execute("DELETE FROM admin_profiles WHERE admin_id=?", [DEMO_ADMIN_ID])
    con.execute("DELETE FROM schools WHERE school_id=?", [DEMO_SCHOOL_ID])
    for table, column in [
        ("teacher_alerts", "class_id"),
        ("gradebook_entries", "class_id"),
        ("teacher_assessments", "class_id"),
        ("teacher_lesson_plans", "class_id"),
        ("class_student_map", "class_id"),
        ("teacher_classes", "class_id"),
    ]:
        con.execute(f"DELETE FROM {table} WHERE {column} LIKE ?", [DEMO_CLASS_PREFIX + "%"])
    for table in ["scholar_mastery", "scholar_study_sessions", "scholar_review_schedule"]:
        con.execute(f"DELETE FROM {table} WHERE student_id LIKE ?", [DEMO_STUDENT_PREFIX + "%"])
    con.execute("DELETE FROM scholar_students WHERE student_id LIKE ?", [DEMO_STUDENT_PREFIX + "%"])
    con.execute("DELETE FROM teacher_profiles WHERE teacher_id=?", [DEMO_TEACHER_ID])

    academic_start = today.year if today.month >= 7 else today.year - 1
    school_year = f"{academic_start}-{str(academic_start + 1)[-2:]}"

    con.execute(
        """
        INSERT INTO teacher_profiles
            (teacher_id, display_name, subjects_json, grade_levels_json, school)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            DEMO_TEACHER_ID,
            "Maya Johnson",
            _dump(["Biology", "Mathematics", "English Language Arts", "Social Studies"]),
            _dump(["High School (9-12)"]),
            "Titans Forge Demo Academy",
        ],
    )
    con.execute(
        """
        INSERT INTO schools
            (school_id, name, grade_bands, enrollment, principal_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        [DEMO_SCHOOL_ID, "Titans Forge Demo Academy", "9-12", 720, "Dr. Avery Cole"],
    )
    con.execute(
        """
        INSERT INTO admin_profiles
            (admin_id, display_name, role, school_id, email)
        VALUES (?, ?, ?, ?, ?)
        """,
        [DEMO_ADMIN_ID, "Dr. Avery Cole", "principal", DEMO_SCHOOL_ID,
         "avery.cole@titansforge.example"],
    )

    classes = [
        {
            "id": "cls_demo_tf_biology",
            "name": "Biology 10 - Period 2",
            "subject": "Biology",
            "grade": "High School (9-12)",
            "term": "Current Term",
            "threshold": 0.70,
            "topics": ["Photosynthesis", "Cellular Respiration", "Enzymes", "Data Claims"],
            "lesson": "Cellular Respiration Lab: Evidence from Yeast",
            "standards": [
                "NGSS.HS-LS1-7", "NGSS.HS-LS1-5",
                "NGSS.HS-LS1-3", "NGSS.HS-ETS1-2",
            ],
            "check_question": "Which yeast-lab observation is evidence that cellular respiration transferred energy?",
            "answer": "A change in carbon dioxide production paired with substrate use supports the energy-transfer claim.",
            "resource": "Cellular Respiration Lab Evidence Guide",
        },
        {
            "id": "cls_demo_tf_algebra",
            "name": "Algebra I - Period 4",
            "subject": "Mathematics",
            "grade": "High School (9-12)",
            "term": "Current Term",
            "threshold": 0.68,
            "topics": ["Linear Equations", "Slope", "Systems", "Function Notation"],
            "lesson": "Systems of Equations: Choosing a Strategy",
            "standards": [
                "CCSS.MATH.HSA-REI.C.6", "CCSS.MATH.HSF-IF.A.2",
                "CCSS.MATH.HSF-IF.B.4", "CCSS.MATH.HSA-CED.A.3",
            ],
            "check_question": "When is substitution more efficient than elimination for solving a system?",
            "answer": "Substitution is efficient when one variable is already isolated or has coefficient one.",
            "resource": "Systems Strategy Comparison Mat",
        },
        {
            "id": "cls_demo_tf_humanities",
            "name": "World Literature - Period 6",
            "subject": "English Language Arts",
            "grade": "High School (9-12)",
            "term": "Current Term",
            "threshold": 0.72,
            "topics": ["Theme Evidence", "Claim Structure", "Rhetorical Moves", "Close Reading"],
            "lesson": "Building Evidence Chains for Literary Analysis",
            "standards": [
                "CCSS.ELA-LITERACY.RL.9-10.1", "CCSS.ELA-LITERACY.W.9-10.2",
                "CCSS.ELA-LITERACY.RL.9-10.2", "CCSS.ELA-LITERACY.W.9-10.9",
            ],
            "check_question": "Which sentence explains how a quotation proves a theme instead of merely repeating it?",
            "answer": "The strongest sentence names the reasoning that connects the textual detail to the theme claim.",
            "resource": "Evidence Chain Annotation Protocol",
        },
        {
            "id": "cls_demo_tf_social_studies",
            "name": "Civics & Society - Period 7",
            "subject": "Social Studies",
            "grade": "High School (9-12)",
            "term": "Current Term",
            "threshold": 0.70,
            "topics": ["Civic Claims", "Source Analysis", "Institutions", "Historical Context"],
            "lesson": "Evaluating Evidence in Civic Claims",
            "standards": [
                "C3.D2.His.14.9-12", "C3.D2.Civ.10.9-12",
                "C3.D2.Eco.1.9-12", "C3.D2.Geo.4.9-12",
            ],
            "check_question": "Which source detail most directly supports the claim about how an institution shaped the outcome?",
            "answer": "The strongest detail is specific evidence tied to the institution's decision and the observed consequence.",
            "resource": "Civic Source Comparison Protocol",
        },
    ]

    students_by_class = {
        "cls_demo_tf_biology": [
            ("Mateo Rivera", "urgent"),
            ("Cora Bennett", "urgent"),
            ("Ari Patel", "watch"),
            ("Samir Okafor", "watch"),
            ("Iris Martinez", "watch"),
            ("Darius Cole", "watch"),
            ("Mei Lin", "watch"),
            ("Rafael Ortiz", "watch"),
            ("Nia Brooks", "ready"),
            ("Lena Chen", "ready"),
            ("Grace Kim", "ready"),
            ("Jonah Lewis", "ready"),
            ("Amina Yusuf", "ready"),
            ("Caleb Foster", "ready"),
            ("Sienna Blake", "ready"),
            ("Eli Turner", "ready"),
            ("Fatima Noor", "ready"),
            ("Logan Bell", "ready"),
            ("Maya Singh", "ready"),
            ("Nolan Reed", "ready"),
            ("Olivia Grant", "ready"),
            ("Parker Young", "ready"),
            ("Quinn Adams", "ready"),
            ("Ruby Flores", "ready"),
        ],
        "cls_demo_tf_algebra": [
            ("Elena Garcia", "urgent"),
            ("Andre Williams", "urgent"),
            ("Kai Thompson", "watch"),
            ("Zara Ali", "watch"),
            ("Noah Price", "watch"),
            ("Bianca Cruz", "watch"),
            ("Cameron Hill", "watch"),
            ("Dev Patel", "watch"),
            ("Priya Shah", "ready"),
            ("Owen Miller", "ready"),
            ("Miles Carter", "ready"),
            ("Tessa Nguyen", "ready"),
            ("Emery Scott", "ready"),
            ("Finn Walker", "ready"),
            ("Gabriela Ruiz", "ready"),
            ("Harper King", "ready"),
            ("Isaac James", "ready"),
            ("Jada Moore", "ready"),
            ("Kendall Ross", "ready"),
            ("Leo Martin", "ready"),
            ("Mina Cho", "ready"),
            ("Nico Santos", "ready"),
            ("Paige Evans", "ready"),
            ("Ronan Baker", "ready"),
        ],
        "cls_demo_tf_humanities": [
            ("Malik Johnson", "urgent"),
            ("Layla Brown", "urgent"),
            ("Theo Davis", "watch"),
            ("Hannah Reed", "watch"),
            ("Xavier Green", "watch"),
            ("Yara Haddad", "watch"),
            ("Zoe Peterson", "watch"),
            ("Adrian Wells", "watch"),
            ("Amara Wilson", "ready"),
            ("Sofia Rossi", "ready"),
            ("Eve Morgan", "ready"),
            ("Luis Hernandez", "ready"),
            ("June Park", "ready"),
            ("Brielle Stone", "ready"),
            ("Chase Howard", "ready"),
            ("Dahlia Ahmed", "ready"),
            ("Ethan Wright", "ready"),
            ("Freya Collins", "ready"),
            ("Gavin Murphy", "ready"),
            ("Hazel Rivera", "ready"),
            ("Imani Clarke", "ready"),
            ("Jasper Lee", "ready"),
            ("Keira Bennett", "ready"),
            ("Luca Romano", "ready"),
        ],
        "cls_demo_tf_social_studies": [
            ("Jordan Ellis", "urgent"),
            ("Talia Brooks", "urgent"),
            ("Jae Kim", "watch"),
            ("Mariam Saleh", "watch"),
            ("Diego Morales", "watch"),
            ("Nia Wallace", "watch"),
            ("Omar Haddad", "watch"),
            ("Sage Cooper", "watch"),
            ("Avery Johnson", "ready"),
            ("Bella Nguyen", "ready"),
            ("Colin Price", "ready"),
            ("Demi Clark", "ready"),
            ("Elias Ford", "ready"),
            ("Farah Khan", "ready"),
            ("Giselle Ward", "ready"),
            ("Hugo Torres", "ready"),
            ("Isla James", "ready"),
            ("Jonas Reed", "ready"),
            ("Kira Patel", "ready"),
            ("Liam Brooks", "ready"),
            ("Malia Chen", "ready"),
            ("Nate Wilson", "ready"),
            ("Opal Green", "ready"),
            ("Rhea Davis", "ready"),
        ],
    }

    class_by_id = {c["id"]: c for c in classes}
    for order, cls in enumerate(classes):
        con.execute(
            """
            INSERT INTO teacher_classes
                (class_id, teacher_id, name, subject, grade_level, term,
                 school_year, standards_set, grading_scale, mastery_threshold, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                cls["id"],
                DEMO_TEACHER_ID,
                cls["name"],
                cls["subject"],
                cls["grade"],
                cls["term"],
                school_year,
                "Next Generation Science Standards (NGSS)" if cls["subject"] == "Biology" else "Common Core (CCSS)",
                "Percentage (0-100)",
                cls["threshold"],
                "Demo class seeded for Titans Forge educator walkthrough.",
            ],
        )
        con.execute(
            """
            INSERT INTO school_classes_link
                (link_id, school_id, class_id, teacher_id)
            VALUES (?, ?, ?, ?)
            """,
            [f"lnk_demo_tf_{order}", DEMO_SCHOOL_ID, cls["id"], DEMO_TEACHER_ID],
        )

        differentiated = {
            "below_grade": "Chunk vocabulary, provide sentence frames, and run a 5-minute guided example before release.",
            "on_grade": "Students complete the core task and defend one answer using evidence.",
            "above_grade": "Add a transfer challenge that asks students to critique a flawed explanation.",
        }
        con.execute(
            """
            INSERT INTO teacher_lesson_plans
                (lesson_id, class_id, teacher_id, lesson_date, topic, duration_min,
                 hook, objectives_json, direct_instruction, guided_practice,
                 independent_practice, differentiated_json, exit_ticket,
                 standards_tags_json, resource_ids_json, notes, ai_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"lsn_demo_tf_{order}",
                cls["id"],
                DEMO_TEACHER_ID,
                today,
                cls["lesson"],
                50,
                "Open with a student-facing misconception prompt and a quick vote.",
                _dump([
                    "Use evidence to justify a strategy or explanation.",
                    "Identify the misconception most likely to cause an error.",
                    "Revise an answer using precise academic language.",
                ]),
                "Model the reasoning move, name the success criteria, and show one annotated example.",
                "Students work in pairs to sort examples by reasoning quality, then repair one weak response.",
                "Students complete an individual check for understanding aligned to the same reasoning move.",
                _dump(differentiated),
                "Write one claim, one evidence point, and one confidence rating.",
                _dump(cls["standards"]),
                "[]",
                "Prepared by Titans Forge demo seeder.",
                True,
            ],
        )

        for lesson_offset, lesson_topic in [
            (1, f"{cls['topics'][1]}: Guided Reasoning Workshop"),
            (3, f"{cls['topics'][2]}: Transfer and Application"),
        ]:
            con.execute(
                """
                INSERT INTO teacher_lesson_plans
                    (lesson_id, class_id, teacher_id, lesson_date, topic, duration_min,
                     hook, objectives_json, direct_instruction, guided_practice,
                     independent_practice, differentiated_json, exit_ticket,
                     standards_tags_json, resource_ids_json, notes, ai_generated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"lsn_demo_tf_{order}_{lesson_offset}", cls["id"],
                    DEMO_TEACHER_ID, today + timedelta(days=lesson_offset),
                    lesson_topic, 50,
                    "Start with an anonymous student response and ask the class to improve it.",
                    _dump([f"Explain {lesson_topic} using precise evidence.",
                           "Compare two strategies and justify the stronger one."]),
                    "Model one complete reasoning chain and annotate each decision.",
                    "Pairs use a worked-example protocol, then compare revisions.",
                    "Students complete a short transfer task independently.",
                    _dump(differentiated),
                    f"Explain the most important reasoning move in {lesson_topic}.",
                    _dump(cls["standards"][:2]), "[]",
                    "Date-relative Titans Forge demo lesson.", True,
                ],
            )

        assessment_id = f"asgmt_demo_tf_{order}"
        con.execute(
            """
            INSERT INTO teacher_assessments
                (assessment_id, class_id, teacher_id, title, assessment_type, topic,
                 instructions, questions_json, rubric_json, bloom_coverage_json,
                 difficulty_dist_json, standards_tags_json, time_estimate_min, ai_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                assessment_id,
                cls["id"],
                DEMO_TEACHER_ID,
                f"{cls['subject']} Checkpoint: {cls['topics'][0]}",
                "quiz",
                cls["topics"][0],
                "Short formative checkpoint used by the demo dashboard.",
                _dump([
                    {
                        "num": 1, "type": "Short Answer", "bloom": "Understand",
                        "text": cls["check_question"], "options": [],
                        "answer": cls["answer"],
                        "explanation": "A strong response makes the reasoning and evidence connection explicit.",
                    },
                    {
                        "num": 2, "type": "Multiple Choice", "bloom": "Analyze",
                        "text": f"Which response best demonstrates mastery of {cls['topics'][0]}?",
                        "options": ["A) A memorized definition", "B) A claim with relevant evidence",
                                    "C) An unrelated example", "D) A confidence rating only"],
                        "answer": "B", "explanation": "Mastery requires an evidence-backed explanation.",
                    },
                    {
                        "num": 3, "type": "Short Answer", "bloom": "Apply",
                        "text": f"Apply {cls['topics'][0]} to a new example and justify your approach.",
                        "options": [], "answer": "Answers vary; reasoning must satisfy the success criteria.",
                        "explanation": "The item checks transfer rather than recall.",
                    },
                ]),
                _dump({
                    "Reasoning": {"weight": 50, "proficient": "Reasoning is complete and accurate."},
                    "Evidence": {"weight": 30, "proficient": "Evidence is relevant and explicitly connected."},
                    "Precision": {"weight": 20, "proficient": "Academic language is precise."},
                }),
                _dump({"Understand": 40, "Apply": 40, "Analyze": 20}),
                _dump({"on_grade": 75, "challenge": 25}),
                _dump(cls["standards"]),
                15,
                True,
            ],
        )

        for sidx, standard in enumerate(cls["standards"]):
            coverage = ["covered", "in_progress", "in_progress", "not_started"][sidx]
            con.execute(
                """
                INSERT INTO standards_coverage
                    (entry_id, class_id, teacher_id, standard_code,
                     standard_desc, lessons_count, last_taught_ts,
                     coverage_level, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [f"sc_demo_tf_{order}_{sidx}", cls["id"], DEMO_TEACHER_ID,
                 standard, f"Priority standard for {cls['topics'][sidx]}",
                 max(0, 3 - sidx), now - timedelta(days=sidx + 1), coverage,
                 "Evidence is derived from current lessons and checkpoints."],
            )

        con.execute(
            """
            INSERT INTO teacher_resources
                (resource_id, teacher_id, filename, file_type, extracted_text,
                 ai_summary, vocab_json, discussion_qs_json, tags_json,
                 standards_tags_json, grade_level, subject, file_size_kb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [f"res_demo_tf_{order}", DEMO_TEACHER_ID, cls["resource"] + ".md",
             "markdown", f"Teacher-facing protocol for {cls['lesson']}.",
             f"A classroom-ready guide for teaching {cls['topics'][0]} through evidence and reasoning.",
             _dump(cls["topics"][:3]), _dump([cls["check_question"]]),
             _dump(["demo", "core-subject", "teacher-reviewed"]),
             _dump(cls["standards"][:2]), cls["grade"], cls["subject"], 18],
        )

        for assignment_kind, assignment_status, due_offset in [
            ("practice", "published", 2),
            ("evidence", "closed", -2),
        ]:
            assignment_id = f"asgn_demo_tf_{order}_{assignment_kind}"
            con.execute(
                """
                INSERT INTO assignments
                    (assignment_id, class_id, teacher_id, title, description,
                     instructions, assignment_type, subject, grade_level,
                     points_possible, rubric_json, status, due_date,
                     published_ts, ai_grading_on, allow_late, allow_resubmit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [assignment_id, cls["id"], DEMO_TEACHER_ID,
                 f"{cls['topics'][0]} {'Practice' if assignment_kind == 'practice' else 'Evidence Task'}",
                 f"Use evidence and reasoning to demonstrate understanding of {cls['topics'][0]}.",
                 "Show your reasoning, cite or label evidence, and finish with a confidence rating.",
                 "homework" if assignment_kind == "practice" else "quiz",
                 cls["subject"], cls["grade"], 100,
                 _dump({"reasoning": 50, "evidence": 30, "precision": 20}),
                 assignment_status, today + timedelta(days=due_offset),
                 now - timedelta(days=4), True, True, assignment_kind == "practice"],
            )

    status_scores = {
        "ready": [0.86, 0.82, 0.78, 0.91],
        "watch": [0.75, 0.72, 0.78, 0.76],
        "urgent": [0.44, 0.52, 0.49, 0.61],
    }
    status_inactive = {"ready": 1, "watch": 6, "urgent": 16}

    for class_id, student_rows in students_by_class.items():
        cls = class_by_id[class_id]
        class_order = list(students_by_class.keys()).index(class_id)
        closed_assignment_id = f"asgn_demo_tf_{class_order}_evidence"
        practice_assignment_id = f"asgn_demo_tf_{class_order}_practice"
        for sidx, (student_name, status) in enumerate(student_rows):
            slug = student_name.lower().replace(" ", "_")
            sid = f"{DEMO_STUDENT_PREFIX}{slug}"
            con.execute(
                """
                INSERT INTO scholar_students
                    (student_id, display_name, edu_level, grade_year, goals_json, settings_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    sid,
                    student_name,
                    "high",
                    "10",
                    _dump(["Build confidence", "Use evidence clearly"]),
                    _dump({"demo": True}),
                ],
            )
            con.execute(
                """
                INSERT INTO class_student_map
                    (class_id, student_id, accommodations, iep_notes, parent_contact)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    class_id,
                    sid,
                    "Visual organizer" if status != "ready" else "",
                    "Prefers step-by-step exemplars" if status == "urgent" else "",
                    f"{slug}@family.example",
                ],
            )

            last_session = now - timedelta(days=status_inactive[status] + (sidx % 2))
            con.execute(
                """
                INSERT INTO scholar_study_sessions
                    (student_id, course_id, topic, started_ts, ended_ts,
                     duration_min, session_type, outcome, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    sid,
                    None,
                    cls["topics"][sidx % len(cls["topics"])],
                    last_session,
                    last_session + timedelta(minutes=22 + sidx),
                    22 + sidx,
                    "tutor",
                    "completed",
                    "Demo learning session.",
                ],
            )

            scores = status_scores[status]
            for tidx, topic in enumerate(cls["topics"]):
                for obs in range(2):
                    score = max(0.25, min(0.98, scores[tidx] + (obs * 0.04) - (sidx % 3) * 0.015))
                    con.execute(
                        """
                        INSERT INTO scholar_mastery
                            (student_id, course_id, topic, source, score, correct,
                             question_text, answer_text, feedback_text, ts)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            sid,
                            None,
                            topic,
                            "demo_checkpoint",
                            score,
                            score >= 0.65,
                            f"Explain {topic}.",
                            "Student demo response.",
                            "Seeded feedback for educator dashboard.",
                            now - timedelta(days=8 - obs - (sidx % 4)),
                        ],
                    )

            base_grade = {"ready": 88, "watch": 74, "urgent": 58}[status] + (sidx % 4)
            con.execute(
                """
                INSERT INTO gradebook_entries
                    (entry_id, assessment_id, class_id, student_id, raw_response,
                     score, max_score, pct, feedback_json, overall_comment,
                     ai_graded, teacher_reviewed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"grd_demo_tf_{class_order}_{sidx}",
                    f"asgmt_demo_tf_{class_order}",
                    class_id,
                    sid,
                    "Demo checkpoint response.",
                    base_grade,
                    100,
                    base_grade,
                    _dump({"strength": "Reasoning is visible", "next_step": "Tighten evidence"}),
                    "AI generated feedback pending teacher review." if status != "ready" else "Ready to return.",
                    True,
                    status == "ready",
                ],
            )

            evidence_id = f"evd_demo_tf_{class_order}_{sidx}"
            con.execute(
                """
                INSERT INTO student_evidence_events
                    (evidence_id, student_id, class_id, teacher_id, topic,
                     standard_code, source_type, source_id, score, max_score,
                     evidence_json, observed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [evidence_id, sid, class_id, DEMO_TEACHER_ID, cls["topics"][0],
                 cls["standards"][0], "assessment",
                 f"asgmt_demo_tf_{class_order}", base_grade, 100,
                 _dump({"status": status, "misconception": cls["topics"][1]}),
                 now - timedelta(days=1 + (sidx % 3))],
            )

            closed_sub_id = f"sub_demo_tf_{class_order}_{sidx}_closed"
            con.execute(
                """
                INSERT INTO student_submissions
                    (submission_id, assignment_id, student_id, class_id,
                     content, status, submitted_ts, is_late, attempt, word_count)
                VALUES (?, ?, ?, ?, ?, 'returned', ?, ?, 1, ?)
                """,
                [closed_sub_id, closed_assignment_id, sid, class_id,
                 f"{student_name} explains {cls['topics'][0]} using a claim, evidence, and reasoning chain.",
                 now - timedelta(days=3), sidx % 9 == 0, 18],
            )
            con.execute(
                """
                INSERT INTO submission_feedback
                    (feedback_id, submission_id, assignment_id, student_id,
                     score, max_score, pct, strengths, improvements,
                     overall_comment, rubric_scores, ai_graded,
                     teacher_reviewed, returned_ts)
                VALUES (?, ?, ?, ?, ?, 100, ?, ?, ?, ?, ?, TRUE, TRUE, ?)
                """,
                [f"fb_demo_tf_{class_order}_{sidx}", closed_sub_id,
                 closed_assignment_id, sid, base_grade, base_grade,
                 "The response makes its reasoning visible.",
                 "Connect the evidence to the conclusion more explicitly.",
                 "Keep the strong structure and sharpen the evidence connection.",
                 _dump({"reasoning": base_grade, "evidence": max(45, base_grade - 8)}),
                 now - timedelta(days=2)],
            )

            if sidx % 4 in (0, 1):
                practice_status = "submitted" if sidx % 4 == 0 else "draft"
                con.execute(
                    """
                    INSERT INTO student_submissions
                        (submission_id, assignment_id, student_id, class_id,
                         content, status, submitted_ts, is_late, attempt, word_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, FALSE, 1, ?)
                    """,
                    [f"sub_demo_tf_{class_order}_{sidx}_practice",
                     practice_assignment_id, sid, class_id,
                     f"Working response for {cls['topics'][0]} practice.",
                     practice_status,
                     now - timedelta(hours=3 + sidx) if practice_status == "submitted" else None,
                     7],
                )

            if status == "urgent":
                plan_id = f"ip_demo_tf_{slug}"
                con.execute(
                    """
                    INSERT INTO intervention_plans
                        (plan_id, student_id, class_id, teacher_id, tier,
                         concern_area, goals_json, strategies_json,
                         resources_json, timeline_weeks, progress_target,
                         ai_plan_text, status, created_ts, updated_ts)
                    VALUES (?, ?, ?, ?, 3, ?, ?, ?, ?, 6, ?, ?, 'active', ?, ?)
                    """,
                    [plan_id, sid, class_id, DEMO_TEACHER_ID,
                     f"Persistent misconception in {cls['topics'][0]} and {cls['topics'][1]}",
                     _dump([f"Reach 70% mastery on {cls['topics'][0]} across three checks."]),
                     _dump(["Twice-weekly guided retrieval", "Worked-example comparison",
                            "One-minute confidence reflection"]),
                     _dump([f"res_demo_tf_{class_order}"]),
                     "Three consecutive checks at or above 70% mastery.",
                     "Teacher-reviewed targeted support plan generated from recent evidence.",
                     now - timedelta(days=9), now - timedelta(days=2)],
                )
                con.execute(
                    """
                    INSERT INTO intervention_progress
                        (entry_id, plan_id, student_id, week_num,
                         mastery_snapshot, teacher_notes, student_response,
                         status, logged_ts)
                    VALUES (?, ?, ?, 1, ?, ?, ?, 'progressing', ?)
                    """,
                    [f"pe_demo_tf_{slug}", plan_id, sid,
                     _dump({cls["topics"][0]: round(base_grade / 100, 2)}),
                     "Student is using the scaffold but still needs to explain why the evidence matters.",
                     "The comparison example made the strategy easier to see.",
                     now - timedelta(days=2)],
                )
                con.execute(
                    """
                    INSERT INTO class_communications
                        (comm_id, teacher_id, class_id, student_id, comm_type,
                         subject_line, content, follow_up, ts)
                    VALUES (?, ?, ?, ?, 'email', ?, ?, ?, ?)
                    """,
                    [f"comm_demo_tf_{slug}", DEMO_TEACHER_ID, class_id, sid,
                     f"Support update for {student_name}",
                     f"Shared a strengths-based update and the new support plan for {cls['topics'][0]}.",
                     "Follow up after the next checkpoint.", now - timedelta(days=1)],
                )
                con.execute(
                    """
                    INSERT INTO parent_reports
                        (report_id, student_id, class_id, period, content,
                         tone, language, status, created_ts)
                    VALUES (?, ?, ?, ?, ?, 'Warm', 'English', 'draft', ?)
                    """,
                    [f"rpt_demo_tf_{slug}", sid, class_id, "Current Week",
                     f"{student_name} is showing persistence. We are targeting {cls['topics'][0]} with a short, measurable support cycle.",
                     now - timedelta(hours=6)],
                )
                con.execute(
                    """
                    INSERT INTO teacher_action_items
                        (action_id, teacher_id, class_id, student_id,
                         action_type, title, detail, priority, status,
                         due_date, source_key, source_json, created_ts, updated_ts)
                    VALUES (?, ?, ?, ?, 'intervention_checkin', ?, ?, 'urgent',
                            'open', ?, ?, ?, ?, ?)
                    """,
                    [f"act_demo_tf_{slug}", DEMO_TEACHER_ID, class_id, sid,
                     f"Check in with {student_name}",
                     f"Review progress on {cls['topics'][0]} before the next checkpoint.",
                     today + timedelta(days=1), f"intervention:{plan_id}",
                     _dump({"plan_id": plan_id, "student_name": student_name,
                            "class_name": cls["name"]}),
                     now - timedelta(days=1), now - timedelta(hours=2)],
                )

            if status == "urgent" or (status == "watch" and sidx < 2):
                weak = ", ".join(cls["topics"][:2])
                severity = "high" if status == "urgent" else "medium"
                message = (
                    f"{student_name} needs support with {weak}; "
                    f"last independent practice was {status_inactive[status]} days ago."
                )
                con.execute(
                    """
                    INSERT INTO teacher_alerts
                        (alert_id, class_id, student_id, alert_type, message,
                         severity, data_json, acknowledged, created_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        f"alrt_demo_tf_{slug}",
                        class_id,
                        sid,
                        "mastery_drop" if status == "urgent" else "inactive",
                        message,
                        severity,
                        _dump({"weak_topics": cls["topics"][:2], "recommended_action": "Generate a 10-minute reteach"}),
                        False,
                        now - timedelta(hours=2 + sidx),
                    ],
                )

        con.execute(
            """
            INSERT INTO teacher_action_items
                (action_id, teacher_id, class_id, action_type, title, detail,
                 priority, status, due_date, source_key, source_json)
            VALUES (?, ?, ?, 'submission_review', ?, ?, 'high', 'open', ?, ?, ?)
            """,
            [f"act_demo_tf_review_{class_order}", DEMO_TEACHER_ID, class_id,
             f"Review new {cls['topics'][0]} submissions",
             "Six submitted responses are ready for feedback before tomorrow's lesson.",
             today, f"assignment:{practice_assignment_id}",
             _dump({"assignment_id": practice_assignment_id,
                    "class_name": cls["name"], "submitted": 6})],
        )
        con.execute(
            """
            INSERT INTO ai_artifact_drafts
                (draft_id, teacher_id, class_id, artifact_type, title,
                 payload_json, source_json, model_name, status)
            VALUES (?, ?, ?, 'lesson', ?, ?, ?, 'local-teacher-model', 'draft')
            """,
            [f"draft_demo_tf_{class_order}", DEMO_TEACHER_ID, class_id,
             f"Reteach draft: {cls['topics'][0]}",
             _dump({"topic": cls["topics"][0], "duration_min": 10,
                    "teacher_move": "Compare one correct and one almost-correct response.",
                    "exit_ticket": cls["check_question"]}),
             _dump({"kind": "class_signal", "standard": cls["standards"][0]})],
        )
    con.close()
    return DEMO_TEACHER_ID


def use_demo_teacher_if_available() -> str | None:
    teachers = list_teachers()
    return DEMO_TEACHER_ID if any(t["teacher_id"] == DEMO_TEACHER_ID for t in teachers) else None


def acknowledge_dashboard_alert(alert_id: str) -> None:
    acknowledge_alert(alert_id)


def resolve_dashboard_action(action_id: str) -> None:
    resolve_teacher_action(action_id)


def _class_grade_stats(class_id: str) -> dict[str, Any]:
    con = _con()
    rows = con.execute(
        """
        SELECT pct, ai_graded, teacher_reviewed
        FROM gradebook_entries
        WHERE class_id=?
        """,
        [class_id],
    ).fetchall()
    con.close()
    scores = [float(r[0] or 0) for r in rows]
    return {
        "avg_grade": mean(scores) if scores else 0.0,
        "graded_count": len(scores),
        "unreviewed": sum(1 for r in rows if bool(r[1]) and not bool(r[2])),
    }


def _sessions_today(student_ids: list[str]) -> int:
    if not student_ids:
        return 0
    placeholders = ",".join("?" * len(student_ids))
    con = _con()
    row = con.execute(
        f"""
        SELECT COUNT(*)
        FROM scholar_study_sessions
        WHERE student_id IN ({placeholders})
          AND CAST(started_ts AS DATE)=CURRENT_DATE
        """,
        student_ids,
    ).fetchone()
    con.close()
    return int(row[0] or 0) if row else 0


def list_class_standards_coverage(
    class_id: str, standard_code: str | None = None
) -> list[dict[str, Any]]:
    """List a class's standards coverage in stable standard-code order."""
    query = """
        SELECT standard_code, standard_desc, coverage_level,
               lessons_count, last_taught_ts
        FROM standards_coverage
        WHERE class_id=?
    """
    params: list[Any] = [class_id]
    if standard_code is not None:
        query += " AND standard_code=?"
        params.append(standard_code)
    query += " ORDER BY standard_code"

    con = _con()
    rows = con.execute(query, params).fetchall()
    con.close()
    return [
        {
            "code": row[0],
            "description": row[1] or "",
            "coverage_level": row[2] or "not_started",
            "lesson_count": int(row[3] or 0),
            "last_taught_ts": row[4],
        }
        for row in rows
    ]


def _build_class_card(cls: dict[str, Any]) -> dict[str, Any]:
    students = list_class_students(cls["class_id"])
    heatmap = class_mastery_heatmap(cls["class_id"], top_n_topics=6)
    scores = [float(h["avg_score"] or 0) for h in heatmap]
    avg_mastery = mean(scores) if scores else 0.0
    topic_scores: dict[str, list[float]] = {}
    for row in heatmap:
        topic_scores.setdefault(row["topic"], []).append(float(row["avg_score"] or 0))
    topics = [
        {"topic": topic, "score": mean(vals), "band": _score_band(mean(vals))}
        for topic, vals in topic_scores.items()
    ]
    topics.sort(key=lambda item: item["score"])
    risk = at_risk_students(
        cls["class_id"],
        mastery_threshold=float(cls.get("mastery_threshold") or 0.6),
    )
    grade_stats = _class_grade_stats(cls["class_id"])
    return {
        "class": cls,
        "students": len(students),
        "student_ids": [s["student_id"] for s in students],
        "avg_mastery": avg_mastery,
        "mastery_pct": _pct(avg_mastery),
        "grade_avg": round(grade_stats["avg_grade"]),
        "unreviewed": grade_stats["unreviewed"],
        "at_risk": risk,
        "risk_count": len(risk),
        "urgent_count": sum(1 for r in risk if r.get("severity") == "high"),
        "topics": topics[:4],
        "band": _score_band(avg_mastery),
        "subject_brief": _subject_matter_brief(cls, topics),
    }


def _recommended_actions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = list(snapshot.get("durable_actions", []))
    kinds = {action.get("kind") for action in actions}
    if snapshot["alert_high"] and "intervention" not in kinds:
        top = snapshot["alerts"][0]
        actions.append(
            {
                "priority": "urgent",
                "title": f"Start with {top['student_name']}",
                "detail": top["message"],
                "cta": "Open intervention planner",
                "page": "pages/46_intervention_planner.py",
                "kind": "intervention",
                "payload": top,
            }
        )
    if snapshot["unreviewed_count"] and "assessment_review" not in kinds:
        review_class = max(
            snapshot["class_cards"],
            key=lambda card: card.get("unreviewed", 0),
            default={},
        )
        review_cls = review_class.get("class", {})
        actions.append(
            {
                "priority": "high",
                "title": f"Review {snapshot['unreviewed_count']} AI-graded submissions",
                "detail": f"Start with {review_cls.get('name', 'the busiest class')} before students see feedback.",
                "cta": "Open assessment studio",
                "page": "pages/38_assessment_studio.py",
                "kind": "assessment_review",
                "payload": {
                    "class_id": review_cls.get("class_id", ""),
                    "class_name": review_cls.get("name", ""),
                    "unreviewed": review_class.get("unreviewed", 0),
                },
            }
        )
    if snapshot["missing_lesson_classes"] and "lesson_gap" not in kinds:
        gap_class = snapshot["missing_lesson_classes"][0]
        actions.append(
            {
                "priority": "prep",
                "title": "Fill the next planning gap",
                "detail": "No lesson is scheduled in the next three days for "
                + ", ".join(c["name"] for c in snapshot["missing_lesson_classes"][:2]),
                "cta": "Open lesson planner",
                "page": "pages/37_lesson_planner.py",
                "kind": "lesson_gap",
                "payload": gap_class,
            }
        )
    if snapshot["watch_topics"] and "reteach" not in kinds:
        topic = snapshot["watch_topics"][0]
        actions.append(
            {
                "priority": "coach",
                "title": f"Run a 10-minute reteach on {topic['topic']}",
                "detail": f"{topic['class_name']} is averaging {_pct(topic['score'])}% on this skill.",
                "cta": "Open differentiation generator",
                "page": "pages/48_differentiation_generator.py",
                "kind": "reteach",
                "payload": topic,
            }
        )
    if not actions:
        actions.append(
            {
                "priority": "ready",
                "title": "Everything urgent is covered",
                "detail": "Use the weekly brief to look ahead and choose tomorrow's leverage point.",
                "cta": "Generate weekly brief",
                "page": "pages/53_teacher_weekly_briefing.py",
                "kind": "weekly_brief",
                "payload": {},
            }
        )
    return actions[:4]


def _dashboard_actions_from_queue(teacher_id: str, classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    class_names = {cls["class_id"]: cls["name"] for cls in classes}
    selected: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    seen_type_classes: set[tuple[str, str]] = set()
    for item in list_teacher_actions(teacher_id, status="open", limit=30):
        action_type = item["action_type"]
        if type_counts.get(action_type, 0) >= 2:
            continue
        type_class_key = (action_type, item.get("class_id", ""))
        if type_class_key in seen_type_classes:
            continue
        source = item.get("source") or {}
        class_name = source.get("class_name") or class_names.get(item.get("class_id", ""), "")
        if action_type == "intervention_checkin":
            selected.append(
                {
                    "action_id": item["action_id"],
                    "priority": item["priority"],
                    "title": item["title"],
                    "detail": item["detail"],
                    "cta": "Open intervention plan",
                    "page": "pages/46_intervention_planner.py",
                    "kind": "intervention",
                    "payload": {
                        "student_id": item.get("student_id", ""),
                        "student_name": source.get("student_name", "Student"),
                        "class_name": class_name,
                        "message": item["detail"],
                        "severity": "high",
                    },
                }
            )
        elif action_type == "submission_review":
            selected.append(
                {
                    "action_id": item["action_id"],
                    "priority": item["priority"],
                    "title": item["title"],
                    "detail": item["detail"],
                    "cta": "Review submissions",
                    "page": "pages/44_assignment_manager.py",
                    "kind": "assignment_review",
                    "payload": {
                        "class_name": class_name,
                        "assignment_id": source.get("assignment_id", ""),
                    },
                }
            )
        else:
            continue
        type_counts[action_type] = type_counts.get(action_type, 0) + 1
        seen_type_classes.add(type_class_key)
    return selected


def get_teacher_dashboard_snapshot(teacher_id: str) -> dict[str, Any]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    classes = list_classes(teacher_id)
    class_cards = [_build_class_card(cls) for cls in classes]
    student_ids = [sid for card in class_cards for sid in card["student_ids"]]
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    alerts = sorted(
        list_alerts(teacher_id, acknowledged=False),
        key=lambda item: (severity_rank.get(item.get("severity", "low"), 9), item.get("created_ts", "")),
    )
    today_lessons = list_lessons_for_teacher(teacher_id, start_date=today, end_date=today)
    upcoming_lessons = list_lessons_for_teacher(
        teacher_id, start_date=tomorrow, end_date=today + timedelta(days=6)
    )
    next_3_lessons = list_lessons_for_teacher(
        teacher_id, start_date=today, end_date=today + timedelta(days=3)
    )
    classes_with_near_lessons = {lesson["class_id"] for lesson in next_3_lessons}
    missing_lesson_classes = [c for c in classes if c["class_id"] not in classes_with_near_lessons]

    lesson_class = {c["class_id"]: c for c in classes}
    for lesson in today_lessons + upcoming_lessons:
        cls = lesson_class.get(lesson["class_id"], {})
        lesson["class_name"] = cls.get("name", lesson["class_id"])
        lesson["subject"] = cls.get("subject", "")

    watch_topics: list[dict[str, Any]] = []
    for card in class_cards:
        cls = card["class"]
        for topic in card["topics"]:
            if topic["score"] < 0.72:
                watch_topics.append(
                    {
                        "class_name": cls["name"],
                        "class_id": cls["class_id"],
                        "subject": cls.get("subject", ""),
                        "grade_level": cls.get("grade_level", ""),
                        "topic": topic["topic"],
                        "score": topic["score"],
                    }
                )
    watch_topics.sort(key=lambda item: item["score"])
    subject_briefs = sorted(
        [card["subject_brief"] for card in class_cards],
        key=lambda item: item.get("score", 1),
    )

    snapshot = {
        "classes": classes,
        "class_cards": class_cards,
        "students_total": sum(card["students"] for card in class_cards),
        "sessions_today": _sessions_today(student_ids),
        "alerts": alerts,
        "alert_high": sum(1 for a in alerts if a.get("severity") == "high"),
        "alert_medium": sum(1 for a in alerts if a.get("severity") == "medium"),
        "unreviewed_count": sum(card["unreviewed"] for card in class_cards),
        "today_lessons": today_lessons,
        "upcoming_lessons": upcoming_lessons,
        "missing_lesson_classes": missing_lesson_classes,
        "watch_topics": watch_topics,
        "subject_briefs": subject_briefs,
        "durable_actions": _dashboard_actions_from_queue(teacher_id, classes),
        "draft_count": len(list_ai_artifact_drafts(teacher_id, status="draft")),
        "avg_mastery": mean([card["avg_mastery"] for card in class_cards]) if class_cards else 0.0,
    }
    snapshot["actions"] = _recommended_actions(snapshot)
    snapshot["readiness_score"] = max(
        0,
        min(
            100,
            round(
                100
                - snapshot["alert_high"] * 6
                - snapshot["alert_medium"] * 3
                - len(snapshot["missing_lesson_classes"]) * 5
                - min(snapshot["unreviewed_count"], 6)
            ),
        ),
    )
    return snapshot
