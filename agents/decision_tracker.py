"""
Autonomous Decision & Stage Advancement Tracker for Job Deck.
Scans incoming recruiting communications, detects when Michael Azuka is selected / advanced
to the next stage (Technical Screen, Hiring Manager, Assessment, Final Round, Offer, or Rejection),
updates applications.csv in real-time, and triggers instant high-priority Telegram alerts.
"""

import os
import re
import csv
import json
import email
import email.utils
import datetime
import pathlib
from typing import Dict, Any, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE_FILE = HERE / "decisions_cache.json"

# Stage definitions and precedence ranking (higher rank cannot be downgraded by lower rank)
STAGE_RANK = {
    "Offer Extended": 6,
    "Interview: Final Round": 5,
    "Interview: Technical Screen": 4,
    "Interview: Hiring Manager": 4,
    "Interview: Phone Screen": 4,
    "Assessment / OA": 3,
    "Rejected": 2,
    "Applied": 1,
}

# Advanced regex patterns for detecting decision outcomes and stage advancements
PATTERNS = {
    "Offer Extended": [
        r"\boffer of employment\b",
        r"\bpleased to offer you\b",
        r"\bextend (an|our) offer\b",
        r"\boffer letter\b",
        r"\bcongratulations.*offer\b",
        r"\bwelcome to the team\b"
    ],
    "Interview: Final Round": [
        r"\bfinal round\b",
        r"\bfinal interview\b",
        r"\bon-?site interview\b",
        r"\bpanel interview\b",
        r"\bpresentation interview\b"
    ],
    "Interview: Technical Screen": [
        r"\btechnical (screen|interview|conversation)\b",
        r"\btech screen\b",
        r"\blive coding\b",
        r"\bsystems (interview|assessment)\b",
        r"\barchitecture interview\b",
        r"\bcybersecurity (screen|interview)\b",
        r"\biam interview\b"
    ],
    "Interview: Hiring Manager": [
        r"\bhiring manager (interview|screen|chat|conversation)\b",
        r"\bmanager screen\b",
        r"\bmeet with the hiring manager\b",
        r"\bconversation with.*(director|manager|lead)\b"
    ],
    "Interview: Phone Screen": [
        r"\bselected to (move forward|advance)\b",
        r"\bmoving you forward in our process\b",
        r"\bpleased to invite you\b",
        r"\bschedule (a|your) (interview|call|phone screen|conversation)\b",
        r"\bavailability for a (quick |30-minute |15-minute )?(call|chat|screen)\b",
        r"\bphone screen\b",
        r"\bfirst round interview\b",
        r"\bnext step.*interview\b",
        r"\bnext stage.*interview\b",
        r"\binterview request\b",
        r"\bconnect with (a|our) recruiter\b"
    ],
    "Assessment / OA": [
        r"\bonline assessment\b",
        r"\bhirevue\b",
        r"\bcodesignal\b",
        r"\bhackerrank\b",
        r"\bcodility\b",
        r"\btake-?home (project|exercise|challenge|assignment)\b",
        r"\bskills assessment\b",
        r"\bcomplete (the|an) assessment\b",
        r"\btechnical evaluation\b"
    ],
    "Rejected": [
        r"\bunfortunately\b",
        r"\bnot (be )?moving forward\b",
        r"\bother candidates\b",
        r"\bno longer (being )?considered\b",
        r"\bposition has been filled\b",
        r"\bdecided to pursue\b",
        r"\bwill not be proceeding\b",
        r"\bregret to inform\b",
        r"\bnot selected\b"
    ],
    "Applied": [
        r"\bthank you for (applying|your application|your interest)\b",
        r"\bapplication (was |has been )?received\b",
        r"\bwe('ve| have) received your application\b",
        r"\bsuccessfully submitted\b"
    ]
}


def load_decisions_cache() -> Dict[str, Any]:
    """Loads previously processed email UIDs and decisions."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_decisions_cache(cache: Dict[str, Any]):
    """Persists decisions cache."""
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Decisions Cache Save Error] {e}", flush=True)


def classify_decision_text(subject: str, body: str) -> Dict[str, Any]:
    """
    Evaluates email subject and body, determines if the candidate has been selected / advanced,
    and returns a structured decision outcome.
    """
    full_text = f"{subject}\n{body}".lower()

    detected_stage = "Applied"
    matched_pattern = None

    # Evaluate stages in descending priority order
    for stage in [
        "Offer Extended",
        "Interview: Final Round",
        "Interview: Technical Screen",
        "Interview: Hiring Manager",
        "Interview: Phone Screen",
        "Assessment / OA",
        "Rejected",
        "Applied"
    ]:
        for pattern in PATTERNS[stage]:
            if re.search(pattern, full_text, re.I):
                detected_stage = stage
                matched_pattern = pattern
                break
        if matched_pattern:
            break

    # Determine if this represents a positive advancement
    is_advancement = detected_stage in [
        "Offer Extended",
        "Interview: Final Round",
        "Interview: Technical Screen",
        "Interview: Hiring Manager",
        "Interview: Phone Screen",
        "Assessment / OA"
    ]

    # Extract action needed and deadlines
    action_needed = ""
    deadline = ""
    
    # Check for deadlines like "by Friday", "within 48 hours", "before Nov 15"
    m_dead = re.search(r"\b(?:by|before|within|due)\s+([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?|\d{1,2}/\d{1,2}|\d+\s*(?:days|hours))\b", full_text, re.I)
    if m_dead:
        deadline = m_dead.group(1)

    if detected_stage == "Offer Extended":
        action_needed = "Review offer details & run /negotiate"
    elif "Interview" in detected_stage:
        action_needed = f"Schedule interview via email/link" + (f" (Deadline: {deadline})" if deadline else "")
    elif detected_stage == "Assessment / OA":
        action_needed = f"Complete online assessment" + (f" (Due: {deadline})" if deadline else "")
    elif detected_stage == "Rejected":
        action_needed = "Closed — update pipeline"
    else:
        action_needed = "Watch email for recruiter updates"

    return {
        "stage": detected_stage,
        "is_advancement": is_advancement,
        "matched_pattern": matched_pattern,
        "action_needed": action_needed,
        "deadline": deadline,
        "rank": STAGE_RANK.get(detected_stage, 1)
    }


def find_matching_application(sender: str, subject: str, body: str, applications: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Matches an incoming email to a specific row in applications.csv."""
    combined = f"{sender} {subject} {body[:500]}".lower()

    for app in applications:
        comp = app.get("Company", "").strip().lower()
        if not comp or len(comp) < 3:
            continue
        # Clean company name
        comp_clean = re.sub(r"[^a-zA-Z0-9]", "", comp)
        if comp in combined or comp_clean in re.sub(r"[^a-zA-Z0-9]", "", combined):
            return app

    return None


def update_application_stage(company: str, role: str, new_stage: str, next_action: str, action_date: str = "", decision_timestamp: str = "") -> bool:
    """Updates the stage, next action, deadline, and decision timestamp of an application in applications.csv."""
    app_csv = ROOT / "applications.csv"
    if not app_csv.exists():
        return False

    with open(app_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if "Decision Date" not in fieldnames:
        fieldnames.append("Decision Date")

    updated = False
    new_rank = STAGE_RANK.get(new_stage, 1)

    for r in rows:
        same_co = r.get("Company", "").strip().lower() == company.strip().lower()
        if same_co:
            current_stage = r.get("Stage", "Applied")
            curr_rank = STAGE_RANK.get(current_stage, 1)

            # Never downgrade a higher stage (e.g. do not downgrade an Interview to Rejected or Applied)
            if new_rank >= curr_rank or current_stage == "Applied":
                r["Stage"] = new_stage
                r["Next Action"] = next_action
                if action_date:
                    r["Next Action Date"] = action_date
                if decision_timestamp:
                    r["Decision Date"] = decision_timestamp
                updated = True
                break

    if updated:
        tmp = app_csv.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, app_csv)

    return updated


def scan_and_track_decision_emails(days_back: int = 30) -> List[Dict[str, Any]]:
    """
    Connects to Gmail, scans decision emails against applications.csv,
    updates pipeline stages, and returns new stage advancements.
    """
    from gmail_auth import get_imap_client, decode_str, extract_body

    mail, err = get_imap_client()
    if not mail:
        print(f"[Decision Tracker] Gmail unavailable: {err}", flush=True)
        return []

    app_csv = ROOT / "applications.csv"
    if not app_csv.exists():
        mail.logout()
        return []

    with open(app_csv, "r", encoding="utf-8-sig") as f:
        applications = list(csv.DictReader(f))

    cache = load_decisions_cache()
    new_advancements = []

    try:
        mail.select("INBOX", readonly=True)
        since_date = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%d-%b-%Y")
        _, data = mail.uid("search", None, f'(SINCE {since_date})')
        uids = data[0].split() if data and data[0] else []

        print(f"[Decision Tracker] Scanning {len(uids)} emails since {since_date}...", flush=True)

        for uid_bytes in reversed(uids):
            uid = uid_bytes.decode()
            if uid in cache:
                continue

            # Fetch email headers
            _, h_rows = mail.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not h_rows or not isinstance(h_rows[0], tuple):
                continue

            hdr = email.message_from_bytes(h_rows[0][1])
            sender = decode_str(hdr.get("From", ""))
            subject = decode_str(hdr.get("Subject", ""))
            date_raw = decode_str(hdr.get("Date", ""))
            
            # Match application
            matched_app = find_matching_application(sender, subject, "", applications)
            if not matched_app:
                cache[uid] = {"processed": True, "matched": False}
                continue

            # Fetch body for matched recruiting email
            _, b_rows = mail.uid("fetch", uid, "(BODY.PEEK[])")
            body_text = ""
            if b_rows and isinstance(b_rows[0], tuple):
                full_msg = email.message_from_bytes(b_rows[0][1])
                body_text = re.sub(r"<[^>]+>", " ", extract_body(full_msg))

            # Classify decision
            decision = classify_decision_text(subject, body_text)
            comp = matched_app.get("Company", "Employer")
            role = matched_app.get("Role", "Cybersecurity Specialist")

            # Format decision timestamp
            dec_timestamp = ""
            if date_raw:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(date_raw)
                    dec_timestamp = dt.strftime("%b %d, %Y %I:%M %p")
                except Exception:
                    dec_timestamp = date_raw[:25]
            if not dec_timestamp:
                dec_timestamp = datetime.datetime.now().strftime("%b %d, %Y %I:%M %p")

            # Determine deadline date
            deadline_str = decision["deadline"]
            if not deadline_str:
                if "Interview" in decision["stage"]:
                    deadline_str = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%b %d, %Y")
                elif "Assessment" in decision["stage"]:
                    deadline_str = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%b %d, %Y")
                elif "Offer" in decision["stage"]:
                    deadline_str = (datetime.date.today() + datetime.timedelta(days=5)).strftime("%b %d, %Y")
                else:
                    deadline_str = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%b %d, %Y")

            cache[uid] = {
                "processed": True,
                "matched": True,
                "company": comp,
                "role": role,
                "subject": subject,
                "stage": decision["stage"],
                "is_advancement": decision["is_advancement"],
                "date": dec_timestamp,
                "deadline": deadline_str
            }

            # Update stage in ledger
            if decision["stage"] != "Applied":
                update_application_stage(
                    company=comp,
                    role=role,
                    new_stage=decision["stage"],
                    next_action=decision["action_needed"],
                    action_date=deadline_str,
                    decision_timestamp=dec_timestamp
                )

            # If candidate was selected / advanced to next round, record for Telegram alert
            if decision["is_advancement"]:
                advancement_item = {
                    "company": comp,
                    "role": role,
                    "stage": decision["stage"],
                    "action_needed": decision["action_needed"],
                    "deadline": deadline_str,
                    "decision_timestamp": dec_timestamp,
                    "subject": subject,
                    "sender": sender
                }
                new_advancements.append(advancement_item)

        save_decisions_cache(cache)
    except Exception as e:
        print(f"[Decision Tracker Error] {e}", flush=True)
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return new_advancements


def format_advancement_telegram_alert(adv: Dict[str, Any]) -> str:
    """Formats a celebratory high-priority Stage Advancement notification for Telegram."""
    stage = adv.get("stage", "Interview Screen")
    is_offer = stage == "Offer Extended"
    icon = "🏆" if is_offer else "🎉"
    title = "FORMAL JOB OFFER EXTENDED!" if is_offer else "STAGE ADVANCEMENT DETECTED!"

    ts = adv.get("decision_timestamp") or datetime.datetime.now().strftime("%b %d, %Y %I:%M %p")
    deadline = adv.get("deadline") or "Within 48 hours"

    return (
        f"{icon} <b>{title}</b>\n\n"
        f"🏢 <b>Company:</b> <b>{adv['company']}</b>\n"
        f"💼 <b>Role:</b> {adv['role']}\n"
        f"🚀 <b>Advancement Status:</b> <b>SELECTED TO MOVE FORWARD!</b>\n"
        f"📍 <b>Current Stage:</b> <code>{stage}</code>\n"
        f"📅 <b>Decision Received:</b> <code>{ts}</code>\n"
        f"⏰ <b>Action Deadline:</b> <code>{deadline}</code>\n"
        f"📋 <b>Next Action:</b> {adv['action_needed']}\n\n"
        f"─────────────────────────────\n"
        f"⚔️ <i>Interview Battlecard generated! Tap below to prepare.</i>"
    )


def get_decision_pipeline_summary() -> str:
    """Generates an executive overview of all current application stages."""
    app_csv = ROOT / "applications.csv"
    if not app_csv.exists():
        return "No applications found."

    with open(app_csv, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_stage = {}
    for r in rows:
        st = r.get("Stage", "Applied")
        by_stage.setdefault(st, []).append(r)

    total = len(rows)
    offers = len(by_stage.get("Offer Extended", []))
    interviews = sum(len(by_stage.get(s, [])) for s in by_stage if "interview" in s.lower())
    assessments = sum(len(by_stage.get(s, [])) for s in by_stage if "assessment" in s.lower() or "oa" in s.lower())
    rejected = len(by_stage.get("Rejected", []))
    active_applied = total - (offers + interviews + assessments + rejected)

    summary = [
        "📊 <b>Autonomous Decision & Pipeline Summary</b>\n",
        f"🎯 <b>Total Verified Applications:</b> {total}",
        f"🏆 <b>Offers Extended:</b> <b>{offers}</b>",
        f"🎉 <b>Interviews & Screens:</b> <b>{interviews}</b>",
        f"📝 <b>Active Assessments:</b> <b>{assessments}</b>",
        f"⏳ <b>Under Review (Applied):</b> {active_applied}",
        f"📉 <b>Closed / Rejected:</b> {rejected}\n"
    ]

    # List positive advancements
    positive_apps = []
    for s in by_stage:
        if any(k in s.lower() for k in ["interview", "offer", "assessment"]):
            positive_apps.extend(by_stage[s])

    if positive_apps:
        summary.append("<b>Active Stage Advancements:</b>")
        for a in positive_apps[:10]:
            co = a.get("Company")
            stg = a.get("Stage")
            act = a.get("Next Action", "Action pending")
            dec_date = a.get("Decision Date") or a.get("Date Applied") or "Recent"
            deadline = a.get("Next Action Date") or "Within 48h"
            summary.append(
                f"• <b>{co}</b> — <code>{stg}</code>\n"
                f"  📅 <i>Decision:</i> <code>{dec_date}</code> | ⏰ <i>Deadline:</i> <code>{deadline}</code>\n"
                f"  🎯 <i>Action:</i> {act}"
            )
    else:
        summary.append("<i>Zero stage advancements recorded yet. Automated tracker is actively listening!</i>")

    return "\n".join(summary)

