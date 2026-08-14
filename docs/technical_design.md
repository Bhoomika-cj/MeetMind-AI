# MeetMind AI — Technical Design Document

## 1. Problem

Meeting transcripts are messy: multiple speakers, interruptions, incomplete
sentences, and buried decisions. Manually extracting who owns what, by
when, is slow and error-prone. MeetMind AI automates this by having an LLM
(Gemini) read the raw transcript and emit a structured, editable record of
action items, decisions, risks, and open questions.

## 2. Goals / Non-goals

**Goals**
- Reliable extraction of action items with owner, deadline, priority,
  status, dependency, and AI-estimated confidence.
- A professional, editable dashboard (`st.data_editor`) rather than a
  static report.
- Zero hallucination policy: unknown owner → "Unassigned", unknown deadline
  → "Not specified", never invented decisions.
- Simple, single-service deployment (Streamlit Community Cloud).

**Non-goals**
- No user authentication, no database, no multi-user persistence.
- No real-time/multi-user collaborative editing.
- No calendar integration or task-tracker sync (out of scope for this
  capstone).

## 3. Architecture

See `docs/architecture.md` for the full diagram. In short:
`Streamlit UI → st.form → Gemini API (structured JSON) → validation →
Pandas DataFrame → session_state → dashboard / data_editor / export`.

## 4. Data flow

1. User fills in meeting metadata and pastes/uploads a transcript inside a
   single `st.form`.
2. On submit, `app.py` calls `utils.gemini_client.extract_action_items()`
   exactly once.
3. The client builds a system instruction (persona + hard extraction
   rules) and a per-call user prompt built with f-strings that inject the
   meeting metadata, today's date, and the transcript.
4. Gemini is called with `response_mime_type="application/json"` and a
   `response_schema`, constraining the shape of the output at the API
   level.
5. The raw JSON text is parsed and passed through
   `validate_and_normalize()`, which:
   - Coerces every field to a safe type.
   - Replaces invalid priority/status values with safe defaults.
   - Fills missing owner/deadline with "Unassigned" / "Not specified".
   - Deduplicates action items by (task, owner).
6. The normalized action items become a Pandas DataFrame
   (`utils.analytics.action_items_to_dataframe`).
7. Results are stored in `st.session_state` so later reruns (filtering,
   editing, chart interaction) do not need another API call.

## 5. Gemini integration & prompt engineering strategy

- **Persona system instruction**: Gemini is told explicitly it is
  "MeetMind AI, an enterprise meeting-intelligence and action-item
  extraction engine," not a general chatbot, with 11 numbered rules
  covering extraction scope, owners, deadlines, priority, status,
  dependencies, decisions vs. action items, risks/blockers, confidence,
  and output format.
- **Explicit anti-hallucination rules**: the system instruction repeatedly
  states never to invent an owner, deadline, or decision, and to prefer
  omission over fabrication.
- **Dynamic context via f-strings**: `build_user_prompt()` injects the
  meeting title, date, team/project, participants, transcript, and the
  *current* system date (so Gemini can resolve "next Monday" style
  language against a real reference point) at call time.
- **Structured output**: a JSON schema (`RESPONSE_SCHEMA`) is passed via
  the SDK's `response_schema` parameter so the API itself constrains
  field names, types, and enum values (Priority/Status).
- **Confidence scoring**: each action item includes a 0–1 AI self-estimate
  of extraction confidence, always labeled in the UI as "AI-estimated,"
  never presented as a verified accuracy metric.

## 6. Pandas pipeline

`utils/analytics.py` owns all DataFrame logic:
- Column normalization and dtype coercion (`action_items_to_dataframe`).
- A best-effort, non-inventive deadline parser (`try_parse_deadline`) that
  resolves phrases like "tomorrow", "next Friday", "end of month" against
  a reference date, and returns `None` (not a guess) for anything it can't
  resolve — so overdue/upcoming calculations never fabricate a date.
- KPI calculations (`compute_kpis`) and AI-quality stats
  (`compute_extraction_quality`).
- Filtering (`apply_filters`) that powers both the data editor view and the
  charts.

## 7. Session state design

State is centralized in `app.py::init_session_state()` and includes the
transcript, meeting metadata, extracted summary/decisions/risks/follow-ups,
the working action-items DataFrame, in-session meeting history, and the
current filter selections. The `st.data_editor` widget's edits are merged
back into `st.session_state.action_items_df` by `ID` so edits survive
filtering and reruns.

## 8. API-call optimization

Gemini is called **only** inside the `if submitted:` block that follows
`st.form_submit_button`. All other interactions (typing in filters,
editing table cells, expanding sections, switching chart tabs) are normal
Streamlit reruns that read from `st.session_state` and never touch the
network.

## 9. Error handling

Handled explicitly and surfaced as friendly `st.error` messages instead of
stack traces:
- Empty or very short transcript (rejected before calling the API).
- Missing `GEMINI_API_KEY` (checked before the call is attempted).
- Gemini API/network failure (caught, message shown, app keeps running).
- Malformed / non-JSON response (caught during `json.loads`).
- Missing or invalid fields in an otherwise-valid JSON response
  (`validate_and_normalize` fills safe defaults instead of crashing).
- Duplicate action items (deduplicated by task+owner).
- Uploaded file that isn't valid UTF-8 text (caught, falls back to the
  pasted text box).

## 10. Security

- No API key is ever hard-coded. `get_api_key()` checks the
  `GEMINI_API_KEY` environment variable first, then Streamlit secrets.
- `.env` and `.streamlit/secrets.toml` are both git-ignored.
- Only `.env.example` and `.streamlit/secrets.toml.example` (templates,
  no real values) are committed.

## 11. Deployment

Target: Streamlit Community Cloud. See the root `README.md` for exact,
step-by-step instructions. Deployment has **not** been performed as part
of generating this codebase — the README's live-demo link is a
placeholder until the student deploys and adds the real URL.

## 12. Testing performed

- Static syntax/compile checks on every Python file
  (`python -m py_compile`).
- Manual review of imports against `requirements.txt`.
- Manual review of cross-module references (`app.py` ↔ `utils/*.py`).
- The Gemini API call path itself could **not** be executed in this
  environment (no network access / no API key available here), so the
  live extraction call is untested end-to-end. See the root README's
  "Testing" section for what the student must verify locally.

## 13. Future improvements

- Persist meeting history across sessions (e.g. SQLite) if a future
  rubric requires it.
- Multi-language transcript support.
- Slack/Teams export integration.
- Speaker-level attribution in extracted context.
