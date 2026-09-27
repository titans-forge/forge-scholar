"""Teacher Class Cockpit: one class, one instructional operating view."""
from __future__ import annotations

import html
import sys
from collections import defaultdict
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from forge_assignments import assignment_stats, init_assignments_db, list_assignments
from forge_teacher import (
    at_risk_students,
    class_mastery_heatmap,
    init_teacher_db,
    list_class_students,
    list_classes,
    list_lessons,
    list_teacher_actions,
    list_teachers,
    resolve_teacher_action,
)
from forge_teacher_dashboard import get_teacher_dashboard_snapshot, list_class_standards_coverage

init_teacher_db()
init_assignments_db()


def _h(value: object) -> str:
    return html.escape(str(value or ""))


def _active_teacher() -> dict | None:
    teachers = list_teachers()
    if not teachers:
        return None
    tid = st.session_state.get("teacher_id")
    return next((t for t in teachers if t["teacher_id"] == tid), teachers[0])


def _class_brief(teacher_id: str, class_id: str) -> dict:
    snapshot = get_teacher_dashboard_snapshot(teacher_id)
    return next(
        (card["subject_brief"] for card in snapshot["class_cards"]
         if card["class"]["class_id"] == class_id),
        {},
    )


def _open_page(page: str, class_name: str, **context: str) -> None:
    target_by_page = {
        "pages/38_assessment_studio.py": "quiz_generator",
        "pages/37_lesson_planner.py": "lesson_planner",
        "pages/48_differentiation_generator.py": "differentiation",
        "pages/44_assignment_manager.py": "assignment_review",
        "pages/40_parent_hub.py": "parent_hub",
        "pages/46_intervention_planner.py": "intervention",
    }
    target = target_by_page.get(page, "class_cockpit")
    if class_name:
        st.session_state["as_cls_sel"] = class_name
        st.session_state["am_cls"] = class_name
        st.session_state["lp_class_sel"] = class_name
        st.session_state["ph_cls_sel"] = class_name
        st.session_state["ip_cls"] = class_name
    if page == "pages/38_assessment_studio.py":
        st.session_state["qg_topic"] = context.get("topic", "")
        st.session_state["qg_std"] = context.get("standard", "")
    elif page == "pages/37_lesson_planner.py":
        st.session_state["lp_prefill_topic"] = context.get("topic", "")
    st.session_state["tf_launch_context"] = {
        "target": target,
        "title": context.pop("title", "Class Cockpit action"),
        "detail": context.pop("detail", "Opened from the class instructional cockpit."),
        "class_name": class_name,
        **context,
    }
    st.switch_page(page)


teacher = _active_teacher()
if not teacher:
    st.warning("No teacher profile found.")
    st.page_link("pages/34_teacher_home.py", label="Teacher Home")
    st.stop()

tid = teacher["teacher_id"]
classes = list_classes(tid)
if not classes:
    st.warning("Create a class first in Class Roster.")
    st.page_link("pages/35_class_roster.py", label="Class Roster")
    st.stop()

class_map = {c["name"]: c for c in classes}
with st.sidebar:
    st.markdown("### Class Cockpit")
    st.divider()
    selected_name = st.selectbox("Class", list(class_map.keys()), key="cc_class")
    selected_class = class_map[selected_name]
    st.divider()
    st.page_link("pages/34_teacher_home.py", label="Teacher Home")
    st.page_link("pages/37_lesson_planner.py", label="Lesson Planner")
    st.page_link("pages/38_assessment_studio.py", label="Assessment Studio")
    st.page_link("pages/46_intervention_planner.py", label="Intervention Planner")

cid = selected_class["class_id"]
st.header(selected_class["name"])
st.caption(
    f"{selected_class.get('subject', 'General')} · {selected_class.get('grade_level', '')} · "
    "Class instructional cockpit"
)

students = list_class_students(cid)
heatmap = class_mastery_heatmap(cid, top_n_topics=12)
topic_scores: dict[str, list[float]] = defaultdict(list)
for row in heatmap:
    topic_scores[row["topic"]].append(float(row.get("avg_score") or 0))
topic_summary = sorted(
    [{"topic": topic, "score": sum(scores) / len(scores)}
     for topic, scores in topic_scores.items()],
    key=lambda item: item["score"],
)
at_risk = at_risk_students(cid, mastery_threshold=float(selected_class.get("mastery_threshold") or 0.6))
actions = [a for a in list_teacher_actions(tid) if a.get("class_id") == cid]
lessons = list_lessons(cid)
assignments = list_assignments(cid, include_closed=True)
brief = _class_brief(tid, cid)

avg_mastery = sum(item["score"] for item in topic_summary) / len(topic_summary) if topic_summary else 0
open_assignments = [a for a in assignments if a.get("status") in ("draft", "published")]
submitted_total = sum(assignment_stats(a["assignment_id"])["submitted"] for a in assignments)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Students", len(students))
m2.metric("Avg mastery", f"{avg_mastery:.0%}")
m3.metric("Needs support", len(at_risk))
m4.metric("Open actions", len(actions))

st.divider()
focus, flow = st.columns([1, 1.15])
with focus:
    st.subheader("Instructional Focus")
    if brief:
        st.markdown(f"**{_h(brief.get('topic'))}** · {_h(brief.get('standard'))}")
        st.write(brief.get("learning_target", ""))
        st.info(
            f"**Misconception to watch:** {brief.get('misconception', '')}\n\n"
            f"**Teacher move:** {brief.get('teacher_move', '')}"
        )
    else:
        st.info("Add mastery evidence to generate an instructional focus.")
    q1, q2 = st.columns(2)
    with q1:
        if st.button("Build checkpoint", use_container_width=True):
            _open_page(
                "pages/38_assessment_studio.py", selected_class["name"],
                title=f"Checkpoint: {brief.get('topic', 'core skill')}",
                detail=brief.get("learning_target", ""),
                topic=brief.get("topic", ""), standard=brief.get("standard", ""),
            )
    with q2:
        if st.button("Plan next move", use_container_width=True):
            _open_page(
                "pages/37_lesson_planner.py", selected_class["name"],
                title=f"Next lesson: {brief.get('topic', 'core skill')}",
                detail=brief.get("teacher_move", ""),
                topic=brief.get("topic", ""), standard=brief.get("standard", ""),
            )

with flow:
    st.subheader("Lesson Flow")
    if lessons:
        for lesson in lessons[:5]:
            st.markdown(
                f"**{_h(lesson.get('lesson_date', '')[:10])}** · "
                f"{_h(lesson.get('topic'))} · {lesson.get('duration_min', 0)} min"
            )
    else:
        st.info("No lessons scheduled for this class yet.")
    st.caption(
        f"{len(open_assignments)} active assignments · {submitted_total} submissions recorded"
    )
    if st.button("Open lesson planner", use_container_width=True):
        _open_page("pages/37_lesson_planner.py", selected_class["name"], title="Lesson planner")

st.divider()
evidence, support = st.columns([1.1, 0.9])
with evidence:
    st.subheader("Mastery by Topic")
    if not topic_summary:
        st.info("No mastery evidence yet.")
    for item in topic_summary[:8]:
        score = max(0, min(100, round(item["score"] * 100)))
        color = "#22c55e" if score >= 78 else "#f59e0b" if score >= 62 else "#ef4444"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;color:#cbd5e1;"
            f"font-size:.86rem;margin-top:8px'><span>{_h(item['topic'])}</span>"
            f"<strong>{score}%</strong></div>"
            f"<div style='height:8px;background:#334155;border-radius:999px;overflow:hidden'>"
            f"<div style='width:{score}%;height:100%;background:{color}'></div></div>",
            unsafe_allow_html=True,
        )

    st.subheader("Standards Coverage")
    all_standards = list_class_standards_coverage(cid)
    focus_options = ["All standards"] + [row["code"] for row in all_standards]
    selected_standard = st.selectbox(
        f"Standard focus · {selected_class.get('subject', 'General')}",
        focus_options,
        key=f"cc_standard_focus_{cid}",
    )
    standard_rows = (
        all_standards
        if selected_standard == "All standards"
        else list_class_standards_coverage(cid, standard_code=selected_standard)
    )
    if standard_rows:
        for row in standard_rows:
            level = row["coverage_level"].replace("_", " ").title()
            st.markdown(
                f"**{_h(row['code'])}** · {level} · "
                f"{row['lesson_count']} lesson{'s' if row['lesson_count'] != 1 else ''}"
            )
            st.caption(_h(row["description"]))
    else:
        st.info("No standards mapped yet.")

with support:
    st.subheader("Support Radar")
    if at_risk:
        for student in at_risk[:6]:
            st.markdown(
                f"**{_h(student.get('display_name'))}** · "
                f"{student.get('severity', 'medium').title()} · "
                f"{', '.join(student.get('weak_topics', [])[:2]) or 'engagement'}"
            )
    else:
        st.success("No students currently need immediate support.")

    st.subheader("Action Queue")
    if actions:
        for action in actions[:6]:
            with st.container(border=True):
                st.markdown(f"**{_h(action['title'])}**")
                st.caption(action.get("detail", ""))
                if st.button("Resolve", key=f"cc_resolve_{action['action_id']}"):
                    resolve_teacher_action(action["action_id"])
                    st.rerun()
    else:
        st.info("No open actions for this class.")

st.divider()
st.subheader("Create From This Class")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("Assignment", use_container_width=True):
        _open_page("pages/44_assignment_manager.py", selected_class["name"], title="New assignment")
with c2:
    if st.button("Reteach pack", use_container_width=True):
        _open_page(
            "pages/48_differentiation_generator.py", selected_class["name"],
            title=f"Reteach pack: {brief.get('topic', 'core skill')}",
            detail=brief.get("misconception", ""), topic=brief.get("topic", ""),
        )
with c3:
    if st.button("Intervention", use_container_width=True):
        _open_page("pages/46_intervention_planner.py", selected_class["name"], title="Intervention planner")
with c4:
    if st.button("Family update", use_container_width=True):
        _open_page("pages/40_parent_hub.py", selected_class["name"], title="Family communication")
