"""
Agent 5 - Inbox Analyst. Reads recruiting emails (read-only) and extracts the stage, deadlines,
proposed interview times and the action needed. Used by outcomes.py; results cached per email.
Urgent items go to agents/inbox_actions.md for the daily briefing.
"""
import datetime, pathlib
from typing import List, Literal
from pydantic import BaseModel
from . import llm, local

ACTIONS = pathlib.Path(__file__).resolve().parent / "inbox_actions.md"


class EmailRead(BaseModel):
    is_about_application: bool
    company: str
    kind: Literal["confirmation", "rejection", "assessment", "interview", "offer", "recruiter_outreach", "other"]
    deadline: str
    proposed_times: List[str]
    action_needed: str
    urgent: bool
    summary: str


SYSTEM = """You triage recruiting emails for a student applying to internships.
kind: confirmation (application received), rejection, assessment (OA / HireVue / coding test / case),
interview (any request to schedule or attend a conversation), offer, recruiter_outreach (unsolicited), other.
deadline: ISO date (YYYY-MM-DD) if the email sets one, else "". proposed_times: any times offered, verbatim.
action_needed: what the candidate must do next, in one short line, or "" if nothing.
urgent: true for assessments, interviews and offers, or any deadline within 7 days.
summary: one sentence. Marketing, newsletters and job alerts: is_about_application=false, kind=other."""


def read(uid, sender, subject, body, date_iso=""):
    """Returns a dict or None (agent unavailable -> caller uses keyword rules)."""
    key = str(uid)
    eng = llm.engine("inbox_analyst")
    hit = llm.cache_get("inbox", key)
    if hit is not None and not (hit.get("engine") == "local" and eng == "ai"):
        return hit
    if eng == "off":
        return None
    if eng == "local":
        d = local.read_email(sender, subject, body, date_iso)
        d["date"] = date_iso
        llm.cache_put("inbox", key, d)
        if d["urgent"] and d["is_about_application"]:
            _note(d)
        return d
    user = f"Date: {date_iso}\nFrom: {sender}\nSubject: {subject}\n\n{body[:8000]}"
    r = llm.ask("inbox_analyst", "fast", SYSTEM, user, EmailRead)
    if r is None:
        return None
    d = r.model_dump()
    d["date"], d["engine"] = date_iso, "ai"
    d["subject"] = subject[:150]
    llm.cache_put("inbox", key, d)
    if d["urgent"] and d["is_about_application"]:
        _note(d)
    return d


def _note(d):
    line = (f"- [{d['date']}] **{d['kind']}** - {d['company']}: {d['action_needed'] or d['summary']}"
            + (f" (deadline {d['deadline']})" if d["deadline"] else "")
            + (f" times: {', '.join(d['proposed_times'])}" if d["proposed_times"] else ""))
    existing = ACTIONS.read_text(encoding="utf-8") if ACTIONS.exists() else "# Inbox actions (newest last)\n"
    if line not in existing:
        ACTIONS.write_text(existing.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")


def open_actions(days=14):
    if not ACTIONS.exists():
        return []
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return [l for l in ACTIONS.read_text(encoding="utf-8").splitlines()
            if l.startswith("- [") and l[3:13] >= cutoff]
