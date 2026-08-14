# 🧠 MeetMind AI

```
$ whoami
> MeetMind AI — Intelligent Meeting Action-Item Extractor

$ tagline --show
> "Turn messy meetings into organized action."
```

[Live Demo — Add after deployment]

---

## 📖 Overview

MeetMind AI is a Streamlit + Gemini capstone application built for
**MirAI School of Technology**. It solves **Project #20 — Meeting
Action-Item Extractor**:

> Users paste a chaotic raw transcript from a 1-hour meeting. The AI
> parses the text into an interactive `st.data_editor` table assigning
> tasks, deadlines, and owners.

Paste (or upload) a raw, messy transcript, and MeetMind AI turns it into
an executive summary, key decisions, a fully editable action-item table,
live analytics, and downloadable reports — without ever inventing an
owner, deadline, or decision that wasn't actually in the transcript.

---

## ❓ Problem Statement

Meeting notes are usually informal, unstructured, and full of
interruptions. Important commitments get lost. MeetMind AI applies an LLM
(Gemini) with a strict, specialized system instruction to reliably surface
*only* what was actually said — flagging unknowns explicitly instead of
guessing.

---

## ✨ Features

```
$ features --list
> ✔ Meeting metadata form (title, date, team, participants)
> ✔ Paste transcript OR upload a .txt file
> ✔ Gemini-powered structured extraction (JSON schema enforced)
> ✔ Executive summary, key decisions, risks, follow-up questions
> ✔ Editable st.data_editor table (dropdowns for Priority / Status)
> ✔ Live KPI dashboard (st.metric): total, high priority, unassigned,
>   overdue, completion %
> ✔ Search + filter (owner, priority, status, overdue-only)
> ✔ Plotly analytics: by owner, by priority, by status, deadline spread
> ✔ AI Extraction Quality panel (AI-estimated confidence, ambiguous items)
> ✔ In-session meeting history (no database required)
> ✔ CSV / JSON / Markdown export
> ✔ Zero hard-coded API keys — env var or Streamlit secrets only
```

---

## 🧱 Tech Stack

```
$ stack --show
> Frontend/App ......... Streamlit
> AI Engine ............ Google Gemini API (google-genai SDK)
> Data Processing ...... Pandas
> Visualization ........ Plotly
> Deployment ........... Streamlit Community Cloud
> Language ............. Python 3.11+
```

---

## 🏗️ Architecture

```mermaid
flowchart TD
    U[User] --> UI[Streamlit UI]
    UI --> FORM[st.form: meeting details + transcript]
    FORM --> T[Transcript text]
    T --> GC[utils/gemini_client.py]
    GC --> API[Gemini API - structured JSON]
    API --> VAL[Validation and safe defaults]
    VAL --> SS[(st.session_state)]
    SS --> DF[Pandas DataFrame]
    DF --> DASH[Dashboard: metrics, charts]
    DF --> EDIT[st.data_editor]
    EDIT --> SS
    DF --> EXP[CSV / JSON / Markdown export]
```

Full diagram and component breakdown: [`docs/architecture.md`](docs/architecture.md)

---

## 📂 Project Structure

```
MeetMind-AI/
│
├── app.py                          # Main Streamlit application
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example                    # Template only — no real key
│
├── .streamlit/
│   └── secrets.toml.example        # Template only — no real secret
│
├── data/
│   ├── college_project_meeting.txt
│   ├── software_sprint.txt
│   └── marketing_review.txt
│
├── utils/
│   ├── __init__.py
│   ├── gemini_client.py            # System prompt, dynamic context, API call, validation
│   ├── analytics.py                # Pandas pipeline, KPIs, Plotly charts
│   └── export.py                   # CSV / JSON / Markdown export
│
├── docs/
│   ├── architecture.md
│   └── technical_design.md
│
└── assets/
    └── README.md
```

---

## ⚙️ Installation

```
$ git clone <your-repo-url>
$ cd MeetMind-AI
$ python -m venv .venv
$ source .venv/bin/activate      # Windows: .venv\Scripts\activate
$ pip install -r requirements.txt
```

---

## 🔑 Gemini API Setup

1. Get a key from [Google AI Studio](https://aistudio.google.com/).
2. **Local development** — copy the example env file and fill in your key:
   ```
   $ cp .env.example .env
   ```
   Then edit `.env`:
   ```
   GEMINI_API_KEY=your_real_key_here
   ```
   `.env` is already listed in `.gitignore` — it will never be committed.

3. **Streamlit Cloud** — copy `.streamlit/secrets.toml.example` into the
   app's **Settings → Secrets** panel on Streamlit Community Cloud (do not
   commit a real `secrets.toml`).

The app checks, in order: the `GEMINI_API_KEY` environment variable, then
`st.secrets["GEMINI_API_KEY"]`. If neither is set, the sidebar shows a
clear "No Gemini API key found" status instead of crashing.

---

## ▶️ Run Locally

```
$ export GEMINI_API_KEY=your_real_key_here   # or use .env with python-dotenv
$ streamlit run app.py
```

Then open the URL Streamlit prints (typically `http://localhost:8501`).

---

## ☁️ Deployment (Streamlit Community Cloud)

> Deployment has **not** been performed as part of building this codebase.
> Follow these steps yourself:

1. Push this repository to GitHub (see commands below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in.
3. Click **"New app"**, select your repo, branch, and `app.py` as the
   entry point.
4. Under **Advanced settings → Secrets**, paste:
   ```
   GEMINI_API_KEY = "your_real_key_here"
   ```
5. Click **Deploy** and wait for the build to finish.
6. Test the live app end-to-end, then replace the placeholder at the top
   of this README with the real URL.

---

## 🧠 Prompt Engineering Strategy

- Gemini is given a persona-locked system instruction ("MeetMind AI, an
  enterprise meeting-intelligence and action-item extraction engine") with
  11 explicit rules, not a freeform prompt.
- Hallucination safeguards are stated directly and repeatedly: never
  invent an owner, deadline, or decision; use `"Unassigned"` /
  `"Not specified"` when unknown; prefer omission to fabrication.
- Dynamic context (title, date, team, participants, transcript, *and*
  today's date) is injected per-call via Python f-strings so relative
  deadlines like "next Monday" can be resolved sensibly.
- Output is constrained with a JSON `response_schema` at the API level,
  then re-validated in Python (`validate_and_normalize`) so a malformed or
  partial response can never crash the app.

Full detail: [`docs/technical_design.md`](docs/technical_design.md)

---

## 🔄 Data Flow

`Transcript → Gemini (structured JSON) → validation/defaults → Pandas
DataFrame → st.session_state → Dashboard / st.data_editor / Analytics /
Export`. The Gemini API is called exactly once per form submission — never
on a filter change, chart interaction, or table edit.

---

## 🔒 Security

- No API key is ever hard-coded in source.
- `.env` and `.streamlit/secrets.toml` are git-ignored.
- Only `.env.example` and `secrets.toml.example` (placeholder values) are
  committed.

---

## 🛡️ Error Handling

Empty/short transcripts, missing API keys, Gemini API failures, malformed
JSON, missing fields, invalid dates, and duplicate tasks are all handled
gracefully with user-facing messages — the app is designed to never show a
raw stack trace to a normal user. See §9 of
[`docs/technical_design.md`](docs/technical_design.md) for the full list.

---

## 🧪 Testing

What was actually done before delivery:
- `python -m py_compile` on every Python file (syntax check) — passed.
- Manual cross-check of every import against `requirements.txt`.
- Manual review of module boundaries between `app.py` and `utils/*.py`.

What could **not** be verified in the build environment (no network / no
API key available there) and is left for you to confirm locally:
- An actual end-to-end Gemini API call and response.
- A live `streamlit run app.py` session in a browser.
- Streamlit Cloud deployment itself.

---

## 🚀 Future Improvements

- Persistent (database-backed) meeting history across sessions.
- Multi-language transcript support.
- Direct export to Slack / Notion / Jira.
- Speaker-level attribution in the extracted context field.

---

```
$ status --final
> Core app: implemented
> AI integration: implemented
> Dashboard / data editor / analytics: implemented
> Deployment: pending (student action required)
> Live demo: [Live Demo — Add after deployment]
```
