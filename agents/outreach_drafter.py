"""
Agent 4 - Outreach Drafter. For strong applications (fit >= 8), drafts a LinkedIn connection note
and says who to look for. DRAFTS ONLY - it never sends anything (LinkedIn restricts accounts that
send automated messages, and the playbook requires AJ's yes per send).
Output: outreach_drafts.csv (one row per company), picked up by the daily briefing.
"""
import csv, datetime, os, pathlib, re, urllib.parse
from typing import List
from pydantic import BaseModel
from . import llm, context, local

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
DRAFTS = AUTOFILL / "outreach_drafts.csv"
COLS = ["date", "company", "role_applied", "fit", "look_for", "linkedin_search", "note", "hook", "status", "followup"]

_FIRST_NAME = os.getenv("CANDIDATE_FIRST_NAME", "Tokunbo")


class Outreach(BaseModel):
    look_for: List[str]
    search_keywords: str
    note: str
    hook: str


SYSTEM = f"""You draft one LinkedIn connection note for the candidate after they apply to a role.

{context.FACT_TEXT}

# PLAYBOOK
- The note is under 280 characters, ends with "- {_FIRST_NAME}", uses contractions, sounds like a student, not a
  template. One specific hook tied to the company or role. No stacked credentials (pick at most one).
- Mention he just applied to the role. Never invent facts about him or the person.
- Never use: leverage, passionate, delve, synergy, spearhead.
- look_for: 2-3 people types most likely to help (e.g. campus recruiter, GSU Robinson / MLT alum on the team,
  team member in that function). search_keywords: a short LinkedIn people-search query for them."""


def _ok(o):
    n = o.note.strip()
    ends_ok = n.endswith(f"- {_FIRST_NAME}") or n.endswith("- Tokunbo")
    return (len(n) <= 300 and ends_ok and not context.BANNED.search(n)
            and not context.unsupported_numbers(n))


def draft(company, role, fit, url="", pre_apply=False):
    eng = llm.engine("outreach_drafter")
    if eng == "off":
        return None
    rows = _rows()
    if any(r["company"].lower() == company.lower() for r in rows):
        return None  # one draft per company is enough
    if eng == "local":
        import results_engine as RE
        o = Outreach(**local.outreach(company, role, RE.score_job(company, role, url)[1]))
        if pre_apply:
            o.note = o.note.replace("I just applied to", "I'm applying to")
    else:
        o = llm.ask("outreach_drafter", "writer", SYSTEM, f"Company: {company}\nRole he applied to: {role}", Outreach)
    if o is None or not _ok(o):
        return None

    # Knowledge Graph Enhancement: Inject warm referral connections & alumni ties
    try:
        from brain.knowledge_graph import get_kg
        kg = get_kg()
        paths = kg.find_referral_paths(company)
        if paths:
            warm_contacts = [f"WARM: {p['name']} ({p['role']}, Warmth: {p['warmth_score']})" for p in paths[:2]]
            o.look_for = warm_contacts + [x for x in o.look_for if not any(w in x for w in ("WARM:", "warmth"))]
            if paths[0].get("hook"):
                o.hook = f"Referral: {paths[0]['name']} - {paths[0]['hook']}"
    except Exception:
        pass

    q = urllib.parse.quote(f"{company} {o.search_keywords}")
    row = {"date": datetime.date.today().isoformat(), "company": company, "role_applied": role, "fit": fit,
           "look_for": "; ".join(o.look_for), "linkedin_search": f"https://www.linkedin.com/search/results/people/?keywords={q}",
           "note": o.note.strip(), "hook": o.hook, "status": "draft - not sent"}
    rows.append(row)
    with open(DRAFTS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)
    return row


def _rows():
    if not DRAFTS.exists():
        return []
    with open(DRAFTS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def followups(days=7):
    """Follow-up drafts for notes AJ marked 'sent' in outreach_drafts.csv >= `days` ago with no reply.
    (Set status to 'sent YYYY-MM-DD' after sending, 'replied' when they answer.)"""
    import re as _re
    rows, made = _rows(), []
    for r in rows:
        m = _re.match(r"sent (\d{4}-\d{2}-\d{2})", r.get("status", ""))
        if m and (datetime.date.today() - datetime.date.fromisoformat(m.group(1))).days >= days and not r.get("followup"):
            r["followup"] = (f"Hi! Following up on my note - I applied to the {r['role_applied'][:50]} role at {r['company']} "
                             f"and would still really value a quick chat if you have 15 minutes. - Tokunbo")
            made.append(r)
    if made:
        cols = COLS + (["followup"] if "followup" not in COLS else [])
        with open(DRAFTS, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    return made


def run_for_today(min_fit=8):
    """Draft notes for today's submitted applications with fit >= min_fit."""
    import results_engine as RE
    today = datetime.date.today().isoformat()
    made = []
    for r in RE.ledger_rows():
        if r["date"] == today and r["status"] == "submitted" and float(r["fit_score"] or 0) >= min_fit:
            d = draft(r["company"], r["role"], r["fit_score"], r["url"])
            if d:
                made.append(d)
    return made
