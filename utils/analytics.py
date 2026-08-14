"""
analytics.py
------------
Pandas data pipeline and Plotly analytics for MeetMind AI.

Turns validated action-item dicts into a Pandas DataFrame, computes
dashboard KPIs, and builds the charts shown on the analytics tab.

No information is ever invented here: deadlines that cannot be parsed
into a real date are simply excluded from date-based calculations
(overdue/upcoming), not guessed at.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

COLUMNS = [
    "Task", "Owner", "Deadline", "Priority", "Status",
    "Dependency", "Context", "Confidence",
]

PRIORITY_ORDER = ["High", "Medium", "Low"]
STATUS_ORDER = ["Blocked", "Pending", "In Progress", "Completed"]

# Brand-consistent chart colors
COLOR_MAP_PRIORITY = {"High": "#EF4444", "Medium": "#F59E0B", "Low": "#10B981"}
COLOR_MAP_STATUS = {
    "Pending": "#94A3B8",
    "In Progress": "#3B82F6",
    "Completed": "#10B981",
    "Blocked": "#EF4444",
}


# --------------------------------------------------------------------------
# DataFrame construction
# --------------------------------------------------------------------------

def action_items_to_dataframe(action_items: list[dict[str, Any]]) -> pd.DataFrame:
    """Converts a list of validated action-item dicts into a DataFrame with
    a stable column order and dtypes. Safe to call with an empty list."""
    if not action_items:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(action_items)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "Confidence" else 0.5

    df = df[COLUMNS].copy()
    df["Confidence"] = pd.to_numeric(df["Confidence"], errors="coerce").fillna(0.5)
    df["Confidence"] = df["Confidence"].clip(0.0, 1.0)

    for col in ["Task", "Owner", "Deadline", "Priority", "Status", "Dependency", "Context"]:
        df[col] = df[col].fillna("").astype(str)

    df.loc[df["Owner"].str.strip() == "", "Owner"] = "Unassigned"
    df.loc[df["Deadline"].str.strip() == "", "Deadline"] = "Not specified"
    df.loc[~df["Priority"].isin(PRIORITY_ORDER), "Priority"] = "Medium"
    df.loc[~df["Status"].isin(STATUS_ORDER), "Status"] = "Pending"
    df.loc[df["Dependency"].str.strip() == "", "Dependency"] = "None"

    df = df.reset_index(drop=True)
    df.insert(0, "ID", range(1, len(df) + 1))
    return df


# --------------------------------------------------------------------------
# Deadline parsing (best-effort, never guesses an exact date it isn't told)
# --------------------------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def try_parse_deadline(deadline_text: str, reference_date: date | None = None) -> date | None:
    """
    Best-effort parser for deadline strings so overdue/upcoming analytics
    can work. Returns None (rather than a guess) when the text is not a
    resolvable date, e.g. "Not specified" or a vague relative phrase.
    """
    if not deadline_text:
        return None
    ref = reference_date or date.today()
    text = deadline_text.strip().lower()

    if text in ("not specified", "", "none", "n/a", "unspecified"):
        return None

    if "today" in text:
        return ref
    if "tomorrow" in text:
        return ref + timedelta(days=1)
    if "asap" in text:
        return ref
    if "end of month" in text or "end of the month" in text:
        if ref.month == 12:
            return date(ref.year, 12, 31)
        next_month = date(ref.year, ref.month + 1, 1)
        return next_month - timedelta(days=1)
    if "next week" in text:
        return ref + timedelta(days=7)

    for wd_name, wd_num in _WEEKDAYS.items():
        if wd_name in text:
            days_ahead = (wd_num - ref.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7 if "next" in text else 0
            elif "next" in text:
                days_ahead += 7
            return ref + timedelta(days=days_ahead)

    # Try ISO / common absolute formats, e.g. 2026-08-20, 20/08/2026, Aug 20 2026
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None

    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(deadline_text.strip(), fmt).date()
        except ValueError:
            continue

    return None


# --------------------------------------------------------------------------
# KPI calculations
# --------------------------------------------------------------------------

def compute_kpis(df: pd.DataFrame, reference_date: date | None = None) -> dict[str, Any]:
    """Computes headline KPI numbers. Returns zeros for an empty DataFrame."""
    ref = reference_date or date.today()

    if df.empty:
        return {
            "total": 0, "high_priority": 0, "unassigned": 0,
            "overdue": 0, "completed": 0, "completion_pct": 0.0,
        }

    total = len(df)
    high_priority = int((df["Priority"] == "High").sum())
    unassigned = int((df["Owner"] == "Unassigned").sum())
    completed = int((df["Status"] == "Completed").sum())
    completion_pct = round((completed / total) * 100, 1) if total else 0.0

    overdue = 0
    for _, row in df.iterrows():
        if row["Status"] == "Completed":
            continue
        parsed = try_parse_deadline(row["Deadline"], ref)
        if parsed and parsed < ref:
            overdue += 1

    return {
        "total": total,
        "high_priority": high_priority,
        "unassigned": unassigned,
        "overdue": overdue,
        "completed": completed,
        "completion_pct": completion_pct,
    }


def compute_extraction_quality(df: pd.DataFrame) -> dict[str, Any]:
    """Stats for the '🔎 AI Extraction Quality' section. Confidence is an
    AI self-estimate, never presented as a verified accuracy metric."""
    if df.empty:
        return {
            "count": 0, "avg_confidence": 0.0, "unassigned": 0,
            "no_deadline": 0, "ambiguous": 0,
        }

    avg_conf = round(float(df["Confidence"].mean()), 2)
    unassigned = int((df["Owner"] == "Unassigned").sum())
    no_deadline = int((df["Deadline"] == "Not specified").sum())
    ambiguous = int((df["Confidence"] < 0.5).sum())

    return {
        "count": len(df),
        "avg_confidence": avg_conf,
        "unassigned": unassigned,
        "no_deadline": no_deadline,
        "ambiguous": ambiguous,
    }


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------

def apply_filters(
    df: pd.DataFrame,
    search_text: str = "",
    owner: str = "All",
    priority: str = "All",
    status: str = "All",
    overdue_only: bool = False,
    reference_date: date | None = None,
) -> pd.DataFrame:
    """Applies the dashboard's search/filter controls to the DataFrame."""
    if df.empty:
        return df

    filtered = df.copy()
    ref = reference_date or date.today()

    if search_text:
        mask = filtered["Task"].str.contains(search_text, case=False, na=False) | \
               filtered["Context"].str.contains(search_text, case=False, na=False)
        filtered = filtered[mask]

    if owner and owner != "All":
        filtered = filtered[filtered["Owner"] == owner]

    if priority and priority != "All":
        filtered = filtered[filtered["Priority"] == priority]

    if status and status != "All":
        filtered = filtered[filtered["Status"] == status]

    if overdue_only:
        def _is_overdue(row):
            if row["Status"] == "Completed":
                return False
            parsed = try_parse_deadline(row["Deadline"], ref)
            return bool(parsed and parsed < ref)
        filtered = filtered[filtered.apply(_is_overdue, axis=1)]

    return filtered


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def chart_tasks_by_owner(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_chart("No action items yet")
    counts = df["Owner"].value_counts().reset_index()
    counts.columns = ["Owner", "Tasks"]
    fig = px.bar(counts, x="Owner", y="Tasks", color="Owner", text="Tasks")
    fig.update_layout(showlegend=False, title="Tasks by Owner", margin=dict(t=40, b=10))
    return fig


def chart_tasks_by_priority(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_chart("No action items yet")
    counts = df["Priority"].value_counts().reindex(PRIORITY_ORDER).fillna(0).reset_index()
    counts.columns = ["Priority", "Tasks"]
    fig = px.pie(
        counts, names="Priority", values="Tasks", hole=0.55,
        color="Priority", color_discrete_map=COLOR_MAP_PRIORITY,
    )
    fig.update_layout(title="Tasks by Priority", margin=dict(t=40, b=10))
    return fig


def chart_tasks_by_status(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_chart("No action items yet")
    counts = df["Status"].value_counts().reindex(STATUS_ORDER).fillna(0).reset_index()
    counts.columns = ["Status", "Tasks"]
    fig = px.bar(
        counts, x="Status", y="Tasks", color="Status", text="Tasks",
        color_discrete_map=COLOR_MAP_STATUS,
    )
    fig.update_layout(showlegend=False, title="Tasks by Status", margin=dict(t=40, b=10))
    return fig


def chart_deadline_distribution(df: pd.DataFrame, reference_date: date | None = None) -> go.Figure:
    if df.empty:
        return _empty_chart("No action items yet")
    ref = reference_date or date.today()

    buckets = {"Overdue": 0, "This week": 0, "Next week+": 0, "Not specified / unclear": 0}
    for _, row in df.iterrows():
        parsed = try_parse_deadline(row["Deadline"], ref)
        if parsed is None:
            buckets["Not specified / unclear"] += 1
        elif parsed < ref:
            buckets["Overdue"] += 1
        elif parsed <= ref + timedelta(days=7):
            buckets["This week"] += 1
        else:
            buckets["Next week+"] += 1

    bucket_df = pd.DataFrame({"Bucket": list(buckets.keys()), "Tasks": list(buckets.values())})
    fig = px.bar(bucket_df, x="Bucket", y="Tasks", color="Bucket", text="Tasks")
    fig.update_layout(showlegend=False, title="Deadline Distribution", margin=dict(t=40, b=10))
    return fig


def _empty_chart(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, showarrow=False,
        font=dict(size=14, color="#94A3B8"),
    )
    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(t=20, b=20),
    )
    return fig
