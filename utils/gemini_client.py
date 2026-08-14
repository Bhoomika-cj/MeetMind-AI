"""
gemini_client.py
-----------------
Handles all communication with the Gemini API for MeetMind AI.

Responsibilities:
* Build a specialized system instruction for meeting-intelligence extraction.
* Build dynamic per-request context (meeting metadata + transcript) using f-strings.
* Call the Gemini API with a structured JSON response schema.
* Validate / sanitize the returned JSON so the rest of the app never crashes
  on a malformed or partial AI response.

No API key is ever hard-coded here. The key is read from the environment
(GEMINI_API_KEY), which app.py populates from either a local .env file or
Streamlit Cloud secrets.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

VALID_PRIORITIES = {"High", "Medium", "Low"}
VALID_STATUSES = {"Pending", "In Progress", "Completed", "Blocked"}
MODEL_NAME = "gemini-2.5-flash"

# JSON schema Gemini is asked to conform to. Passed to the SDK as
# response_schema so the API itself constrains the output shape.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "meeting_summary": {"type": "STRING"},
        "key_decisions": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "action_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "task": {"type": "STRING"},
                    "owner": {"type": "STRING"},
                    "deadline": {"type": "STRING"},
                    "priority": {
                        "type": "STRING",
                        "enum": ["High", "Medium", "Low"],
                    },
                    "status": {
                        "type": "STRING",
                        "enum": ["Pending", "In Progress", "Completed", "Blocked"],
                    },
                    "dependency": {"type": "STRING"},
                    "context": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["task", "owner", "deadline", "priority", "status"],
            },
        },
        "risks_and_blockers": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "follow_up_questions": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
    },
    "required": ["meeting_summary", "key_decisions", "action_items",
                 "risks_and_blockers", "follow_up_questions"],
}


# --------------------------------------------------------------------------
# System instruction
# --------------------------------------------------------------------------

def build_system_instruction() -> str:
    """
    Returns the specialized system instruction that turns Gemini into a
    meeting-intelligence extraction engine rather than a generic chatbot.
    """
    return """You are MeetMind AI, an enterprise meeting-intelligence and action-item
extraction engine. You are NOT a general-purpose conversational assistant.
You exist for one purpose: to read a raw, messy meeting transcript and turn
it into a precise, structured record of what was decided and what needs to
happen next.

Follow these rules strictly:

1. EXTRACTION SCOPE
   - Extract explicit action items exactly as discussed.
   - You may infer an action item ONLY when the transcript strongly implies
     one (e.g. "someone needs to fix the login bug before Friday" implies a
     task even without the word "task"). Do not infer weakly-supported items.
   - Every action item must be traceable to something actually said in the
     transcript. Never invent tasks that were not discussed.

2. OWNERS
   - Identify the owner only if the transcript names or clearly implies a
     specific person.
   - If no owner is identifiable, set owner to the literal string
     "Unassigned". Never guess a name.

3. DEADLINES
   - Identify deadlines only from what was actually said.
   - Preserve relative language when no absolute date is possible, e.g.
     "Relative deadline: next week", "Relative deadline: Friday".
   - If nothing is said about timing, set deadline to the literal string
     "Not specified". Never invent a date.

4. PRIORITY
   - Assign High, Medium, or Low based on urgency language, business impact,
     or explicit statements in the transcript. Default to "Medium" when
     unclear rather than guessing High or Low without support.

5. STATUS
   - Default new action items to "Pending" unless the transcript explicitly
     states work is already underway ("In Progress"), already finished
     ("Completed"), or stuck on something ("Blocked").

6. DEPENDENCIES
   - Note any dependency mentioned (e.g. "after design approval"). If none,
     use "None".

7. DECISIONS vs ACTION ITEMS
   - Key decisions are conclusions the group reached, not tasks assigned to
     a person. Do not duplicate a decision as an action item unless a
     specific follow-up task was also assigned.
   - Never invent a decision that was not actually agreed upon in the text.

8. RISKS, BLOCKERS, FOLLOW-UPS
   - Capture risks or blockers explicitly raised in the discussion.
   - Capture open questions that were raised but not resolved as
     follow-up questions.

9. CONFIDENCE
   - For each action item, include a "confidence" value between 0 and 1
     representing how directly the transcript supports the extraction
     (1.0 = explicitly stated, ~0.5 = reasonably inferred, lower = weak
     inference). This is an AI self-estimate, not a verified metric.

10. HONESTY OVER COMPLETENESS
    - It is always better to omit an item than to fabricate one.
    - Distinguish facts (explicitly stated) from inference (implied) in the
      "context" field when relevant, e.g. "Explicitly assigned by Priya."
      vs "Inferred from discussion about the deploy blocker."

11. OUTPUT FORMAT
    - Respond ONLY with valid JSON matching the provided schema. Do not
      include markdown code fences, commentary, or any text outside the
      JSON object.

Your goal is accuracy and restraint, not volume. A short, correct list of
action items is far more valuable than a long list padded with guesses."""


# --------------------------------------------------------------------------
# Dynamic context builder
# --------------------------------------------------------------------------

def build_user_prompt(
    meeting_title: str,
    meeting_date: str,
    team_project: str,
    participants: str,
    transcript: str,
) -> str:
    """
    Builds the dynamic per-call prompt using f-strings, injecting meeting
    metadata and today's date so Gemini can resolve relative deadlines
    (e.g. "next Monday") against a real reference point.
    """
    today_str = date.today().isoformat()

    return f"""MEETING METADATA
----------------
Title: {meeting_title or "Not provided"}
Date of meeting: {meeting_date or "Not provided"}
Today's date (for resolving relative deadlines): {today_str}
Team / Project: {team_project or "Not provided"}
Participants: {participants or "Not provided"}

RAW TRANSCRIPT
--------------
{transcript}

TASK
----
Analyze the transcript above and return a single JSON object matching the
required schema: meeting_summary, key_decisions, action_items,
risks_and_blockers, follow_up_questions.

Remember: use "Unassigned" for unknown owners, "Not specified" for unknown
deadlines, and never fabricate names, dates, or decisions that are not
supported by the transcript."""


# --------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    raw_text: str | None = None


class GeminiClientError(Exception):
    """Raised for configuration-level problems (e.g. missing API key)."""


# --------------------------------------------------------------------------
# Validation / sanitization
# --------------------------------------------------------------------------

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip() or default
    return str(value)


def _safe_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(max(conf, 0.0), 1.0)


def validate_and_normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Takes a (possibly incomplete/malformed) dict parsed from the model's
    JSON output and returns a fully-populated, safe dict with sensible
    defaults for any missing or invalid fields. Never raises.
    """
    if not isinstance(raw, dict):
        raw = {}

    normalized: dict[str, Any] = {
        "meeting_summary": _safe_str(raw.get("meeting_summary"), "No summary was generated."),
        "key_decisions": [],
        "action_items": [],
        "risks_and_blockers": [],
        "follow_up_questions": [],
    }

    for key in ("key_decisions", "risks_and_blockers", "follow_up_questions"):
        items = raw.get(key)
        if isinstance(items, list):
            normalized[key] = [_safe_str(i) for i in items if _safe_str(i)]

    raw_actions = raw.get("action_items")
    if isinstance(raw_actions, list):
        cleaned_actions = []
        seen = set()
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            task = _safe_str(item.get("task"))
            if not task:
                continue

            owner = _safe_str(item.get("owner"), "Unassigned") or "Unassigned"
            deadline = _safe_str(item.get("deadline"), "Not specified") or "Not specified"

            priority = _safe_str(item.get("priority"), "Medium")
            if priority not in VALID_PRIORITIES:
                priority = "Medium"

            status = _safe_str(item.get("status"), "Pending")
            if status not in VALID_STATUSES:
                status = "Pending"

            dependency = _safe_str(item.get("dependency"), "None") or "None"
            context = _safe_str(item.get("context"), "")
            confidence = _safe_confidence(item.get("confidence"))

            # Duplicate handling: same task + owner treated as a duplicate.
            dedup_key = (task.lower(), owner.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            cleaned_actions.append({
                "Task": task,
                "Owner": owner,
                "Deadline": deadline,
                "Priority": priority,
                "Status": status,
                "Dependency": dependency,
                "Context": context,
                "Confidence": confidence,
            })
        normalized["action_items"] = cleaned_actions

    return normalized


def _extract_json_text(text: str) -> str:
    """Strips markdown code fences if the model added them despite instructions."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def extract_action_items(
    meeting_title: str,
    meeting_date: str,
    team_project: str,
    participants: str,
    transcript: str,
    api_key: str | None = None,
) -> ExtractionResult:
    """
    Calls the Gemini API and returns a validated ExtractionResult.
    Never raises for API-level or parsing-level failures; those are
    captured in ExtractionResult.error so app.py can show a friendly
    message instead of crashing.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ExtractionResult(
            success=False,
            error=(
                "No Gemini API key was found. Set the GEMINI_API_KEY environment "
                "variable locally, or add it to Streamlit Cloud secrets."
            ),
        )

    transcript = (transcript or "").strip()
    if not transcript:
        return ExtractionResult(success=False, error="The transcript is empty.")
    if len(transcript) < 40:
        return ExtractionResult(
            success=False,
            error="The transcript is too short to reliably extract action items from.",
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return ExtractionResult(
            success=False,
            error=(
                "The 'google-genai' package is not installed. "
                "Run: pip install google-genai"
            ),
        )

    try:
        client = genai.Client(api_key=api_key)

        system_instruction = build_system_instruction()
        user_prompt = build_user_prompt(
            meeting_title, meeting_date, team_project, participants, transcript
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.2,
            ),
        )

        raw_text = getattr(response, "text", None)
        if not raw_text:
            return ExtractionResult(
                success=False,
                error="Gemini returned an empty response. Please try again.",
            )

    except Exception as exc:  # noqa: BLE001 - surface any SDK/network error safely
        return ExtractionResult(
            success=False,
            error=f"Gemini API request failed: {exc}",
        )

    try:
        cleaned_text = _extract_json_text(raw_text)
        parsed = json.loads(cleaned_text)
    except (json.JSONDecodeError, TypeError):
        return ExtractionResult(
            success=False,
            error="Gemini's response could not be parsed as valid JSON.",
            raw_text=raw_text,
        )

    normalized = validate_and_normalize(parsed)
    return ExtractionResult(success=True, data=normalized, raw_text=raw_text)
