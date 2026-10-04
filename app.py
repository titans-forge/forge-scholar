"""Local, fictional classroom demonstration. Run: streamlit run app.py."""
from html import escape
import streamlit as st
from scholar_demo import initialize_demo, get_classroom, save_lesson_draft, approve_lesson, get_student_preview
from forge_scholar_config import resolve_demo_database_path

st.set_page_config(page_title="Forge Scholar · Classroom", page_icon="📖", layout="wide")


def html(value):
    st.markdown(value, unsafe_allow_html=True)


def bar(n, d, label, color="#258879"):
    cells = "".join(f'<span style="background:{color if i < n else "#EDF0EA"}"></span>' for i in range(d))
    return f'<div class="fraction-row"><b>{escape(label)}</b><div class="fraction-bar">{cells}</div></div>'


def card(kicker, title, body):
    html(f'<div class="scholar-card"><div class="eyebrow">{escape(kicker)}</div><h3>{escape(title)}</h3><p>{escape(body)}</p></div>')


def lesson_visual():
    html('<div class="visual-lesson"><div class="eyebrow">MAKE THE PIECES VISIBLE</div><h2>Two quarters. One half.</h2>' + bar(1, 4, '1/4') + bar(1, 4, '+ 1/4', '#D6A451') + bar(2, 4, '= 2/4') + bar(1, 2, '= 1/2') + '<p>The pieces stay the same size. Add the number of pieces.</p></div>')


def approve_reviewed_version(db, displayed_version):
    """Callback arguments belong to the prior rendered review, before rerun."""
    try:
        approve_lesson(db, expected_version=displayed_version)
    except ValueError as exc:
        st.session_state['approval_error'] = str(exc)
    else:
        st.session_state['notice'] = 'Lesson approved. It is now available in the student preview.'


def main():
    html('''<style>
    [data-testid="stAppViewContainer"]{background:#F6F5F0}
    [data-testid="stHeader"]{background:transparent}
    .block-container{max-width:1380px;padding-top:2.2rem;padding-bottom:3rem}
    [data-testid="stSidebar"]{display:none}
    h1,h2,h3{color:#183431;letter-spacing:-.035em}
    h1{font-size:2.85rem!important;line-height:1.12!important}
    h2{font-size:1.9rem!important}
    p{line-height:1.6}
    .brand{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;gap:16px}
    .brand-name{font-weight:800;font-size:23px;letter-spacing:-.04em}
    .brand-mark{background:#183431;color:#F2D28B;border-radius:9px;padding:6px 10px;margin-right:10px}
    .pill{font-size:12px;padding:7px 12px;background:#EBEAE1;border:1px solid #DCDDD3;border-radius:20px;color:#50635E}
    .eyebrow{font-weight:700;font-size:11px;color:#648079;letter-spacing:.12em;margin-bottom:9px}
    .hero-description{font-size:18px;color:#61746E;max-width:750px;margin-bottom:22px}
    .scholar-card{background:white;border:1px solid #E1E5DC;border-radius:14px;padding:23px;height:100%;margin-bottom:8px}
    .scholar-card h3{font-size:24px;margin:0 0 9px}.scholar-card p{color:#61746E;margin:0;font-size:15px}
    .stat{font-size:40px;font-weight:750;color:#183431;letter-spacing:-.05em}
    .stat-note{font-size:13px;color:#647871}
    .pattern{border-left:4px solid #D6A451;background:#FFF9E9;padding:18px 22px;border-radius:0 12px 12px 0;margin-bottom:14px}
    .pattern h3{font-size:22px;margin:0 0 7px}.pattern p{margin:0;color:#6C634B}
    .answer{display:flex;justify-content:space-between;gap:15px;padding:14px 2px;border-bottom:1px solid #E6E9E1;font-size:16px}
    .answer em{font-style:normal;color:#99722D;font-weight:700}
    .answer .correct{color:#187E72}
    .visual-lesson{background:#183431;color:white;border-radius:18px;padding:28px;margin:12px 0 20px}
    .visual-lesson h2{color:#FFF9E9;margin:0 0 22px}.visual-lesson .eyebrow{color:#D8C58D}
    .visual-lesson p{color:#D4E0D6;font-size:16px;margin:24px 0 0}
    .fraction-row{display:flex;align-items:center;gap:20px;margin:14px 0}.fraction-row b{width:65px;flex-shrink:0;font-size:22px}
    .fraction-bar{display:flex;width:100%;gap:4px}.fraction-bar span{flex:1;height:34px;border-radius:4px}
    .footer{font-size:12px;color:#7A8C84;margin-top:35px;border-top:1px solid #DCE2D8;padding-top:15px}
    [data-testid="stMetric"]{background:white;border:1px solid #E1E5DC;padding:18px;border-radius:12px}
    @media(max-width:700px){.block-container{padding:1.3rem 1rem!important}h1{font-size:2rem!important}.brand{align-items:flex-start}.pill{max-width:150px}.fraction-row{gap:10px}.visual-lesson{padding:22px}.hero-description{font-size:16px}}
    </style>''')
    db = resolve_demo_database_path()
    initialize_demo(db)
    classroom = get_classroom(db)
    html('<div class="brand"><div class="brand-name"><span class="brand-mark">F</span>Forge Scholar</div><span class="pill">Fictional class · Local demo</span></div>')
    page = st.segmented_control("Workspace", ["Class overview", "Student answers", "Next lesson", "Student preview"], default="Class overview", label_visibility="collapsed")
    page = page or "Class overview"
    summary = classroom['summary']
    lesson = classroom['current_lesson']
    if page == "Class overview":
        html('<div class="eyebrow">GRADE 5 · MATHEMATICS · FRACTIONS</div>')
        st.title("What should we teach next?")
        html('<p class="hero-description">Start with what students actually wrote. Find the shared stumbling block, then choose tomorrow’s lesson.</p>')
        a,b,c = st.columns(3)
        a.metric("Fictional students", summary['student_count'])
        b.metric("Correct answers", f"{summary['correct_count']} / {summary['response_count']}")
        c.metric("Students to check in with", summary['needs_support_count'])
        st.write("")
        left,right=st.columns([1.15,1],gap="large")
        with left:
            st.subheader("The answers tell a story")
            for pattern in classroom['patterns']:
                html(f'<div class="pattern"><div class="eyebrow">{pattern["student_count"]} STUDENTS · {pattern["response_count"]} ANSWERS</div><h3>{escape(pattern["title"])}</h3><p>{escape(pattern["description"])}</p></div>')
            st.caption("Patterns are simple rules applied to these saved answers. The teacher decides what they mean.")
        with right:
            lesson_visual()
            st.caption("Suggested next lesson: use fraction bars to connect the answer with the size of each piece.")
    elif page == "Student answers":
        html('<div class="eyebrow">LOOK BEHIND THE SCORE</div>')
        st.title("See where the thinking changed.")
        st.caption("All names and answers in this example are fictional.")
        question = st.selectbox("Question", classroom['questions'], format_func=lambda q:q['prompt'])
        left,right=st.columns([1.1,1],gap="large")
        with left:
            card("CORRECT ANSWER",question['expected_answer'],f"{question['correct_count']} of {question['response_count']} students answered correctly.")
            if question['id'] == 'compare_parts':
                html('<div class="visual-lesson"><div class="eyebrow">COMPARE THE SAME WHOLE</div><h2>Four eighths is one half.</h2>' + bar(3,8,'3/8','#D6A451') + bar(4,8,'1/2') + '<p>Use equal-sized pieces. Four eighths is greater than three eighths.</p></div>')
            for response in question['answers']:
                css='correct' if response['correct'] else ''
                html(f'<div class="answer"><span>{escape(response["student_name"])}</span><em class="{css}">{escape(response["answer"])} {"✓" if response["correct"] else "· check in"}</em></div>')
        with right:
            st.subheader("Follow an individual answer")
            student=st.selectbox("Student",classroom['students'],format_func=lambda s:s['name'])
            for answer in student['answers']:
                with st.container(border=True):
                    st.markdown(f"**{answer['prompt']}**")
                    st.write(f"Answered: **{answer['answer']}** · Expected: **{answer['expected_answer']}**")
                    st.caption(answer['explanation'])
    elif page == "Next lesson":
        html('<div class="eyebrow">THE TEACHER MAKES THE CALL</div>')
        st.title("Turn the evidence into a lesson.")
        left,right=st.columns([1.1,1],gap="large")
        with left:
            proposal=lesson or classroom['recommended_lesson']
            with st.form("lesson_editor"):
                title=st.text_input("Lesson title",value=proposal['title'],max_chars=180)
                objective=st.text_area("Learning goal",value=proposal['objective'],height=90)
                activities=st.text_area("Activities · one per line",value='\n'.join(proposal['activities']),height=170)
                note=st.text_input("Teacher note",value=proposal.get('teacher_note',''))
                if st.form_submit_button("Save lesson draft",type="primary",use_container_width=True):
                    try:
                        save_lesson_draft(db,title=title,objective=objective,activities=[line.strip() for line in activities.splitlines() if line.strip()],teacher_note=note)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state['notice']='Draft saved. Review the saved lesson before approving it.'
                        st.rerun()
            st.caption("Saving an edit returns the lesson to draft. Students see only the currently approved version.")
        with right:
            lesson_visual()
            if notice:=st.session_state.pop('notice',None):
                st.success(notice)
            if approval_error:=st.session_state.pop('approval_error',None):
                st.error(approval_error)
            if lesson:
                with st.container(border=True):
                    st.markdown(f"**Saved lesson · Version {lesson['version']} · {lesson['status'].title()}**")
                    st.write(lesson['title'])
                    st.caption(lesson['objective'])
                    for activity in lesson['activities']:
                        st.write(f"• {activity}")
                    if lesson.get('teacher_note'):
                        st.caption(f"Teacher note: {lesson['teacher_note']}")
                    st.button("Approve saved lesson for student preview",type="primary",disabled=lesson['status']=='approved',use_container_width=True,on_click=approve_reviewed_version,args=(db,lesson['version']))
            else:
                st.info("Save a draft first. Nothing has been sent to the student preview.")
    else:
        html('<div class="eyebrow">PREVIEW WHAT THE STUDENT SEES</div>')
        st.title("A clearer next step.")
        student=st.selectbox("Preview student",classroom['students'],format_func=lambda s:s['name'])
        preview=get_student_preview(db,student['id'])
        st.caption("A simulated student view for this local demo; this is not a signed-in student account.")
        if not preview['lesson']:
            st.info("Your teacher is preparing the next lesson. A draft is not visible here.")
        else:
            left,right=st.columns([1,1],gap="large")
            with left:
                card(f"READY FOR {student['name'].upper()}",preview['lesson']['title'],preview['lesson']['objective'])
                for number,activity in enumerate(preview['lesson']['activities'],1):
                    st.markdown(f"**{number}.** {activity}")
            with right:
                lesson_visual()
                st.success("Approved by the teacher")
    html('<div class="footer">Titans Forge · An open-source classroom example. Fictional data · Local storage · Teacher-reviewed lessons.</div>')


if __name__ == "__main__":
    # Explicit navigation prevents incomplete legacy preview pages appearing in this demo.
    st.navigation([st.Page(main,title="Classroom")],position="hidden").run()
