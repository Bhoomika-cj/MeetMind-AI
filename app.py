"""
MeetMind AI — Intelligent Meeting Action-Item Extractor
=========================================================
"Turn messy meetings into organized action."

Entry point for the Streamlit application. Handles page config, session
state initialization, the transcript-submission form, the results
dashboard, the interactive data editor, filters, analytics, and exports.

Run locally:
    streamlit run app.py

Requires GEMINI_API_KEY to be set as an environment variable or in
.streamlit/secrets.toml (see README.md).
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd
import streamlit as st

from utils.analytics import (
    action_items_to_dataframe,
    apply_filters,
    chart_deadline_distribution,
    chart_tasks_by_owner,
    chart_tasks_by_priority,
    chart_tasks_by_status,
    compute_extraction_quality,
    compute_kpis,
)
from utils.export import to_csv_bytes, to_json_bytes, to_markdown_report
from utils.gemini_client import extract_action_items

# --------------------------------------------------------------------------
# Page config
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="MeetMind AI | Meeting Action-Item Extractor",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

PRIORITY_OPTIONS = ["High", "Medium", "Low"]
STATUS_OPTIONS = ["Pending", "In Progress", "Completed", "Blocked"]

SAMPLE_TRANSCRIPTS = {
    "College Project Meeting": "data/college_project_meeting.txt",
    "Software Sprint Standup": "data/software_sprint.txt",
    "Marketing Review Meeting": "data/marketing_review.txt",
}


# --------------------------------------------------------------------------
# API key resolution (never hard-coded)
# --------------------------------------------------------------------------

def get_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("GEMINI_API_KEY")  # type: ignore[union-attr]
    except Exception:
        return None


# --------------------------------------------------------------------------
# Session state initialization
# --------------------------------------------------------------------------

def init_session_state() -> None:
    defaults = {
        "transcript_text": "",
        "meeting_title": "",
        "meeting_date": date.today(),
        "team_project": "",
        "participants": "",
        "meeting_summary": "",
        "key_decisions": [],
        "risks_and_blockers": [],
        "follow_up_questions": [],
        "action_items_df": pd.DataFrame(),
        "has_results": False,
        "meeting_history": [],
        "last_error": None,
        "filter_search": "",
        "filter_owner": "All",
        "filter_priority": "All",
        "filter_status": "All",
        "filter_overdue_only": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# --------------------------------------------------------------------------
# Custom styling
# --------------------------------------------------------------------------

st.markdown("""
<style>
    .mm-hero {
        padding: 1.6rem 2rem;
        border-radius: 14px;
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        color: white;
        margin-bottom: 1.4rem;
    }
    .mm-hero h1 { margin: 0; font-size: 2rem; }
    .mm-hero p { margin: 0.3rem 0 0 0; color: #94A3B8; font-size: 1rem; }
    .mm-badge {
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        background: #334155; color: #E2E8F0; font-size: 0.75rem;
        margin-right: 6px;
    }
    div[data-testid="stMetric"] {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 0.8rem 1rem;
}

div[data-testid="stMetric"] label {
    color: #475569 !important;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #0F172A !important;
}

div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    color: #475569 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="mm-hero">
  <h1>🧠 MeetMind AI</h1>
  <p>Intelligent Meeting Action-Item Extractor — Turn messy meetings into organized action.</p>
  <span class="mm-badge">Gemini-powered</span>
  <span class="mm-badge">Streamlit</span>
  <span class="mm-badge">MirAI School of Technology · Capstone</span>
</div>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Sidebar — meeting history + API status
# --------------------------------------------------------------------------

with st.sidebar:
    st.subheader("⚙️ System Status")
    api_key = get_api_key()
    if api_key:
        st.success("Gemini API key detected.")
    else:
        st.error("No Gemini API key found.")
        st.caption("Set GEMINI_API_KEY as an environment variable, or add it to `.streamlit/secrets.toml`.")

    st.divider()
    st.subheader("🕘 Meeting History")
    if st.session_state.meeting_history:
        for entry in reversed(st.session_state.meeting_history[-10:]):
            st.markdown(
                f"**{entry['title']}**  \n"
                f"{entry['date']} · {entry['task_count']} tasks · "
                f"{entry['completion_pct']}% complete"
            )
            st.divider()
    else:
        st.caption("No meetings processed yet this session. "
                    "History is kept in-session only (no database).")


# --------------------------------------------------------------------------
# Section 1 — Transcript submission form
# --------------------------------------------------------------------------

st.header("📋 1. Meeting Details & Transcript")

with st.expander("💡 Try a sample transcript first", expanded=False):
    sample_choice = st.selectbox(
        "Sample meetings",
        options=["None"] + list(SAMPLE_TRANSCRIPTS.keys()),
        key="sample_choice",
    )
    if sample_choice != "None" and st.button("Load sample into the form below"):
        sample_path = SAMPLE_TRANSCRIPTS[sample_choice]
        try:
            with open(sample_path, "r", encoding="utf-8") as f:
                st.session_state["prefill_transcript"] = f.read()
            st.session_state["prefill_title"] = sample_choice
            st.rerun()
        except FileNotFoundError:
            st.warning("Sample file not found on disk.")

with st.form("meeting_form", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        meeting_title = st.text_input(
            "Meeting Title",
            value=st.session_state.pop("prefill_title", st.session_state.meeting_title),
        )
        meeting_date_input = st.date_input("Meeting Date", value=st.session_state.meeting_date)
    with col2:
        team_project = st.text_input("Team / Project", value=st.session_state.team_project)
        participants = st.text_input(
            "Participants (comma-separated)", value=st.session_state.participants
        )

    uploaded_file = st.file_uploader("Upload a .txt transcript (optional)", type=["txt"])

    transcript_default = st.session_state.pop("prefill_transcript", st.session_state.transcript_text)
    transcript_input = st.text_area(
        "Paste raw meeting transcript",
        value=transcript_default,
        height=260,
        placeholder="Paste the raw, messy meeting transcript here...",
    )

    submitted = st.form_submit_button("🤖 Extract Action Items", use_container_width=True)

if submitted:
    final_transcript = transcript_input
    if uploaded_file is not None:
        try:
            final_transcript = uploaded_file.read().decode("utf-8")
        except UnicodeDecodeError:
            st.error("Could not read the uploaded file as UTF-8 text.")
            final_transcript = transcript_input

    st.session_state.meeting_title = meeting_title
    st.session_state.meeting_date = meeting_date_input
    st.session_state.team_project = team_project
    st.session_state.participants = participants
    st.session_state.transcript_text = final_transcript

    if not final_transcript or not final_transcript.strip():
        st.session_state.last_error = "Please paste a transcript or upload a .txt file before extracting."
        st.session_state.has_results = False
    else:
        with st.spinner("MeetMind AI is analyzing the transcript..."):
            result = extract_action_items(
                meeting_title=meeting_title,
                meeting_date=str(meeting_date_input),
                team_project=team_project,
                participants=participants,
                transcript=final_transcript,
                api_key=api_key,
            )

        if not result.success:
            st.session_state.last_error = result.error
            st.session_state.has_results = False
        else:
            st.session_state.last_error = None
            st.session_state.meeting_summary = result.data["meeting_summary"]
            st.session_state.key_decisions = result.data["key_decisions"]
            st.session_state.risks_and_blockers = result.data["risks_and_blockers"]
            st.session_state.follow_up_questions = result.data["follow_up_questions"]
            df = action_items_to_dataframe(result.data["action_items"])
            st.session_state.action_items_df = df
            st.session_state.has_results = True

            kpis = compute_kpis(df)
            st.session_state.meeting_history.append({
                "title": meeting_title or "Untitled Meeting",
                "date": str(meeting_date_input),
                "task_count": kpis["total"],
                "completion_pct": kpis["completion_pct"],
            })

if st.session_state.last_error:
    st.error(st.session_state.last_error)


# --------------------------------------------------------------------------
# Empty state
# --------------------------------------------------------------------------

if not st.session_state.has_results:
    st.info(
        "👆 Fill in the meeting details, paste or upload a transcript, and click "
        "**Extract Action Items** to generate your dashboard. You can also load a "
        "sample transcript above to try it out immediately."
    )
    st.stop()


# --------------------------------------------------------------------------
# Section 2 — Dashboard KPIs
# --------------------------------------------------------------------------

df = st.session_state.action_items_df
kpis = compute_kpis(df)

st.header("📊 2. Dashboard Overview")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Action Items", kpis["total"])
m2.metric("High Priority", kpis["high_priority"])
m3.metric("Unassigned", kpis["unassigned"])
m4.metric("Overdue", kpis["overdue"])
m5.metric("Completion %", f"{kpis['completion_pct']}%")

st.caption(
    "Deltas are intentionally omitted — MeetMind AI only shows a comparison "
    "once at least two meetings with real history exist in this session."
)


# --------------------------------------------------------------------------
# Section 3 — Meeting Brief
# --------------------------------------------------------------------------

st.header("📝 3. Meeting Brief")

with st.expander("Executive Summary", expanded=True):
    st.write(st.session_state.meeting_summary or "No summary available.")

col_a, col_b = st.columns(2)
with col_a:
    with st.expander("✅ Key Decisions", expanded=True):
        if st.session_state.key_decisions:
            for d in st.session_state.key_decisions:
                st.markdown(f"- {d}")
        else:
            st.caption("No decisions were recorded in this transcript.")

    with st.expander("⚠️ Risks / Blockers"):
        if st.session_state.risks_and_blockers:
            for r in st.session_state.risks_and_blockers:
                st.markdown(f"- {r}")
        else:
            st.caption("No risks or blockers were raised.")

with col_b:
    with st.expander("❓ Follow-up Questions"):
        if st.session_state.follow_up_questions:
            for q in st.session_state.follow_up_questions:
                st.markdown(f"- {q}")
        else:
            st.caption("No open follow-up questions.")

    with st.expander("🔎 AI Extraction Quality", expanded=True):
        quality = compute_extraction_quality(df)
        qc1, qc2 = st.columns(2)
        qc1.metric("Tasks extracted", quality["count"])
        qc2.metric("Avg. AI-estimated confidence", quality["avg_confidence"])
        qc3, qc4 = st.columns(2)
        qc3.metric("Unassigned tasks", quality["unassigned"])
        qc4.metric("Tasks without deadlines", quality["no_deadline"])
        st.caption(
            f"⚠️ {quality['ambiguous']} item(s) flagged as potentially ambiguous "
            "(AI confidence below 0.5). Confidence is an AI self-estimate, not a "
            "mathematically verified accuracy score."
        )


# --------------------------------------------------------------------------
# Section 4 — Filters
# --------------------------------------------------------------------------

st.header("🔍 4. Search & Filter")

f1, f2, f3, f4, f5 = st.columns([2, 1, 1, 1, 1])
with f1:
    st.session_state.filter_search = st.text_input(
        "Search tasks", value=st.session_state.filter_search, placeholder="Search by keyword..."
    )
with f2:
    owner_options = ["All"] + sorted(df["Owner"].unique().tolist()) if not df.empty else ["All"]
    st.session_state.filter_owner = st.selectbox(
        "Owner", owner_options,
        index=owner_options.index(st.session_state.filter_owner)
        if st.session_state.filter_owner in owner_options else 0,
    )
with f3:
    priority_opts = ["All"] + PRIORITY_OPTIONS
    st.session_state.filter_priority = st.selectbox(
        "Priority", priority_opts, index=priority_opts.index(st.session_state.filter_priority)
    )
with f4:
    status_opts = ["All"] + STATUS_OPTIONS
    st.session_state.filter_status = st.selectbox(
        "Status", status_opts, index=status_opts.index(st.session_state.filter_status)
    )
with f5:
    st.session_state.filter_overdue_only = st.checkbox(
        "Overdue only", value=st.session_state.filter_overdue_only
    )

filtered_df = apply_filters(
    df,
    search_text=st.session_state.filter_search,
    owner=st.session_state.filter_owner,
    priority=st.session_state.filter_priority,
    status=st.session_state.filter_status,
    overdue_only=st.session_state.filter_overdue_only,
)


# --------------------------------------------------------------------------
# Section 5 — Interactive Data Editor
# --------------------------------------------------------------------------

st.header("🗂️ 5. Action Items (editable)")

if filtered_df.empty:
    st.warning("No action items match the current filters." if not df.empty
               else "No action items were extracted from this transcript.")
else:
    edited_df = st.data_editor(
        filtered_df,
        column_config={
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "Task": st.column_config.TextColumn("Task", width="large"),
            "Owner": st.column_config.TextColumn("Owner"),
            "Deadline": st.column_config.TextColumn("Deadline"),
            "Priority": st.column_config.SelectboxColumn("Priority", options=PRIORITY_OPTIONS),
            "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
            "Dependency": st.column_config.TextColumn("Dependency"),
            "Context": st.column_config.TextColumn("Context", width="large"),
            "Confidence": st.column_config.ProgressColumn(
                "AI Confidence", min_value=0.0, max_value=1.0, format="%.2f"
            ),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="data_editor_widget",
    )

    # Merge edits back into the full (unfiltered) session-state DataFrame
    if not edited_df.equals(filtered_df):
        full_df = st.session_state.action_items_df.set_index("ID")
        edited_indexed = edited_df.set_index("ID") if "ID" in edited_df.columns else edited_df
        for row_id, row in edited_indexed.iterrows():
            if row_id in full_df.index:
                full_df.loc[row_id] = row
        # Handle newly added rows (num_rows="dynamic")
        new_rows = edited_indexed[~edited_indexed.index.isin(full_df.index)]
        if not new_rows.empty:
            full_df = pd.concat([full_df, new_rows])
        st.session_state.action_items_df = full_df.reset_index()
        st.rerun()


# --------------------------------------------------------------------------
# Section 6 — Analytics
# --------------------------------------------------------------------------

st.header("📈 6. Analytics")

c1, c2 = st.columns(2)

with c1:
    st.plotly_chart(
        chart_tasks_by_owner(filtered_df),
        use_container_width=True,
        key="tasks_by_owner_chart"
    )

with c2:
    st.plotly_chart(
        chart_tasks_by_priority(filtered_df),
        use_container_width=True,
        key="tasks_by_priority_chart"
    )


c3, c4 = st.columns(2)

with c3:
    st.plotly_chart(
        chart_tasks_by_status(filtered_df),
        use_container_width=True,
        key="tasks_by_status_chart"
    )

with c4:
    st.plotly_chart(
        chart_deadline_distribution(filtered_df),
        use_container_width=True,
        key="deadline_distribution_chart"
    )


# --------------------------------------------------------------------------
# Section 7 — Export
# --------------------------------------------------------------------------

st.header("⬇️ 7. Export")

e1, e2, e3 = st.columns(3)

current_df = st.session_state.action_items_df

with e1:
    st.download_button(
        "Download CSV",
        data=to_csv_bytes(current_df),
        file_name=f"meetmind_action_items_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with e2:
    st.download_button(
        "Download JSON",
        data=to_json_bytes(
            st.session_state.meeting_title, str(st.session_state.meeting_date),
            st.session_state.team_project, st.session_state.participants,
            st.session_state.meeting_summary, st.session_state.key_decisions,
            current_df, st.session_state.risks_and_blockers,
            st.session_state.follow_up_questions,
        ),
        file_name=f"meetmind_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        use_container_width=True,
    )
with e3:
    st.download_button(
        "Download Markdown Report",
        data=to_markdown_report(
            st.session_state.meeting_title, str(st.session_state.meeting_date),
            st.session_state.team_project, st.session_state.participants,
            st.session_state.meeting_summary, st.session_state.key_decisions,
            current_df, st.session_state.risks_and_blockers,
            st.session_state.follow_up_questions,
        ),
        file_name=f"meetmind_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
        use_container_width=True,
    )

st.divider()
st.caption("MeetMind AI · Built with Streamlit + Gemini · MirAI School of Technology Capstone Project")
