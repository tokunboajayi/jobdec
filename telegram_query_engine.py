"""
Conversational Query & Rule-Answering Engine for Job Deck Telegram Bot
Powered by Google DeepMind Gemini AI + live database search across applications, queue, and inbox.
"""

import os
import re
import csv
import json
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PENDING_FILE = ROOT / "pending_questions.json"
PROFILE_PATH = ROOT / "profile.json"
NEEDS_YOU_PATH = ROOT / "agents" / "needs_you.md"
APPLICATIONS_PATH = ROOT / "applications.csv"
if not APPLICATIONS_PATH.exists():
    APPLICATIONS_PATH = ROOT.parent / "applications.csv"


def load_pending_questions():
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_pending_questions(q_list):
    PENDING_FILE.write_text(json.dumps(q_list, indent=2), encoding="utf-8")


def add_pending_question(label: str, options: list = None, company: str = ""):
    label_clean = label.strip()
    if not label_clean or len(label_clean) < 3:
        return None

    pending = load_pending_questions()
    for item in pending:
        if item.get("question", "").lower() == label_clean.lower():
            return item

    q_id = f"q_{len(pending) + 1}_{int(datetime.now().timestamp()) % 10000}"
    new_item = {
        "id": q_id,
        "question": label_clean,
        "options": options or [],
        "company": company or "Job Portal",
        "asked_at": datetime.now().isoformat(timespec="seconds")
    }
    pending.append(new_item)
    save_pending_questions(pending)
    return new_item


def resolve_pending_question(q_id_or_latest: str, answer: str) -> dict:
    pending = load_pending_questions()
    if not pending:
        return {"ok": False, "msg": "No pending questions found waiting for an answer."}

    matched_item = None
    if q_id_or_latest and q_id_or_latest != "latest":
        for item in pending:
            if item.get("id") == q_id_or_latest:
                matched_item = item
                break

    if not matched_item:
        matched_item = pending[-1]

    question = matched_item["question"]
    ans_clean = answer.strip()
    clean_q = re.sub(r"[\*#\?]", "", question).strip()

    try:
        if PROFILE_PATH.exists():
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        else:
            data = {"rules": []}

        new_rule = {
            "q": clean_q.lower(),
            "a": ans_clean,
            "src": "telegram_user",
            "added": str(date.today())
        }
        if matched_item.get("options"):
            new_rule["option"] = rf"^{re.escape(ans_clean)}\b"

        data["rules"].insert(0, new_rule)
        PROFILE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

        pending = [p for p in pending if p.get("id") != matched_item.get("id")]
        save_pending_questions(pending)

        if NEEDS_YOU_PATH.exists():
            lines = NEEDS_YOU_PATH.read_text(encoding="utf-8").splitlines()
            new_lines = [l for l in lines if clean_q.lower() not in l.lower()]
            NEEDS_YOU_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "question": clean_q,
            "answer": ans_clean,
            "msg": f"✅ Rule saved to <code>profile.json</code>!\n\n<b>Field:</b> {clean_q}\n<b>Your Answer:</b> {ans_clean}\n\nFuture jobs asking this will be answered automatically."
        }
    except Exception as e:
        return {"ok": False, "msg": f"Failed to save rule: {e}"}


def search_applications(query: str):
    if not APPLICATIONS_PATH.exists():
        return []
    q_norm = query.strip().lower()
    matches = []
    with open(APPLICATIONS_PATH, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            comp = (r.get("Company") or "").lower()
            role = (r.get("Role") or "").lower()
            if q_norm in comp or q_norm in role:
                matches.append(r)
    return matches


def get_applications_by_date(target_date_str: str):
    if not APPLICATIONS_PATH.exists():
        return []
    matches = []
    with open(APPLICATIONS_PATH, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            d = (r.get("Date Applied") or r.get("Date") or "").strip()
            if target_date_str in d:
                matches.append(r)
    return matches


def ask_gemini_ai(user_prompt: str) -> str:
    """Invokes Google Gemini 3.5 Flash for conversational responses."""
    key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()
    if not key:
        return ""

    system_instruction = (
        "You are Antigravity, the elite agentic AI coding assistant developed by Google DeepMind. "
        "You are chatting directly with Michael Azuka on Telegram. "
        "Michael is an undergraduate student at Kennesaw State University majoring in Cybersecurity with a minor in IT "
        "(graduating Dec 2026, accepted MS Cybersecurity Spring 2027). Location: Powder Springs, GA (Atlanta metro). "
        "He is running an automated Job Deck applying to Cybersecurity, IAM, Cloud Engineering, and IT Support roles. "
        "Be concise, highly intelligent, friendly, and authoritative. Answer his question directly in clean Telegram HTML format."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 600}
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[Gemini AI Error] {e}")
        return ""


def answer_natural_language_query(text: str) -> str:
    t = text.strip()
    t_lower = t.lower()

    # 1. Did we apply to X? / Search company
    m_apply = re.search(r"(?:did we apply to|have we applied to|search|check|look for)\s+([a-zA-Z0-9\s\-]+)", t_lower)
    company_candidate = None
    if m_apply:
        company_candidate = m_apply.group(1).strip()
    elif any(term in t_lower for term in ["boeing", "palantir", "cloudflare", "harvey", "perplexity", "sierra", "verkada", "ramp", "figma"]):
        for comp in ["boeing", "palantir", "cloudflare", "harvey", "perplexity", "sierra", "verkada", "ramp", "figma"]:
            if comp in t_lower:
                company_candidate = comp
                break

    if company_candidate:
        matches = search_applications(company_candidate)
        if matches:
            lines = [f"🔍 <b>Found {len(matches)} application(s) for '{company_candidate.title()}':</b>", ""]
            for r in matches[:5]:
                date_str = r.get("Date Applied") or r.get("Date") or "Recent"
                role = r.get("Role") or "Role"
                comp = r.get("Company") or company_candidate.title()
                url = r.get("Job URL") or ""
                link_html = f" - <a href='{url}'>Link</a>" if url else ""
                lines.append(f"• <b>{comp}</b> | {role}\n  <i>Date: {date_str}</i>{link_html}")
            return "\n".join(lines)
        else:
            q_file = ROOT / "queue_cyber_iam.txt"
            in_queue = []
            if q_file.exists():
                with open(q_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if company_candidate in line.lower():
                            in_queue.append(line.strip())
            if in_queue:
                return f"📋 <b>{company_candidate.title()}</b> has not been submitted yet, but is <b>waiting in your priority queue</b> ({len(in_queue)} postings queued).\n\nType <code>apply</code> to run!"
            return f"❌ No submitted applications found for <b>'{company_candidate.title()}'</b>."

    # 2. What jobs were applied today / yesterday?
    today_str = str(date.today())
    yesterday_str = str(date.today() - timedelta(days=1))

    if "today" in t_lower:
        rows = get_applications_by_date(today_str)
        if not rows:
            return f"📅 <b>No applications submitted today yet ({today_str}).</b>\nType <code>apply</code> to start the 3 headless workers!"
        lines = [f"📅 <b>Applications Submitted Today ({len(rows)} total):</b>", ""]
        for r in rows[-8:]:
            lines.append(f"• <b>{r.get('Company')}</b> — {r.get('Role')}")
        return "\n".join(lines)

    if "yesterday" in t_lower:
        rows = get_applications_by_date(yesterday_str)
        if not rows:
            return f"📅 No applications recorded for yesterday ({yesterday_str})."
        lines = [f"📅 <b>Applications Submitted Yesterday ({len(rows)} total):</b>", ""]
        for r in rows[-8:]:
            lines.append(f"• <b>{r.get('Company')}</b> — {r.get('Role')}")
        return "\n".join(lines)

    # 3. Next in queue / top of queue
    if any(k in t_lower for k in ["next", "upcoming", "top of queue", "queue next", "what's next"]):
        q_file = ROOT / "queue_cyber_iam.txt"
        if q_file.exists():
            with open(q_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")][:5]
            if lines:
                out = ["📋 <b>Next 5 Roles in Priority Queue:</b>", ""]
                for i, l in enumerate(lines, 1):
                    parts = l.split("   ")
                    title = parts[0] if parts else l[:60]
                    out.append(f"{i}. {title}")
                return "\n".join(out)
        return "Queue is currently empty or loading."

    # 4. Inbox actions / replies / interviews
    if any(k in t_lower for k in ["inbox", "reply", "replies", "interview", "assessment", "recruiter", "email"]):
        inbox_file = ROOT / "agents" / "inbox_actions.md"
        if inbox_file.exists():
            text_inbox = inbox_file.read_text(encoding="utf-8").strip()
            lines = [l for l in text_inbox.splitlines() if l.startswith("- [")]
            if lines:
                out = ["📬 <b>Urgent Recruiter Inbox Actions:</b>", ""]
                for l in lines[-5:]:
                    out.append(l)
                return "\n".join(out)
        return "📬 <b>No urgent recruiter actions or interview requests pending in your inbox right now.</b>"

    # 5. Pending questions
    if any(k in t_lower for k in ["pending question", "questions", "need answer", "needs you", "unanswered"]):
        pending = load_pending_questions()
        if pending:
            out = [f"❓ <b>There are {len(pending)} question(s) awaiting your input:</b>", ""]
            for item in pending[-3:]:
                out.append(f"• <b>{item.get('company')}:</b> <i>{item.get('question')}</i>")
                if item.get("options"):
                    out.append(f"  Options: {', '.join(item.get('options')[:4])}")
            out.append("\nTo answer, reply: <code>answer: [your answer]</code>")
            return "\n".join(out)
        return "✅ <b>All caught up!</b> There are no pending questions waiting for your answer."

    # 6. User answering a question via "answer: ..." or "set rule: ..."
    m_answer = re.search(r"^(?:answer|ans)\s*:\s*(.+)$", t, re.I)
    if m_answer:
        ans_val = m_answer.group(1).strip()
        res = resolve_pending_question("latest", ans_val)
        return res["msg"]

    m_rule = re.search(r"^set rule\s*:\s*(.+?)\s*=\s*(.+)$", t, re.I)
    if m_rule:
        q_val = m_rule.group(1).strip()
        a_val = m_rule.group(2).strip()
        fake_item = add_pending_question(q_val)
        res = resolve_pending_question(fake_item["id"], a_val)
        return res["msg"]

    # 7. Ask Google Gemini AI (Antigravity Brain)
    ai_resp = ask_gemini_ai(t)
    if ai_resp:
        return f"✨ <b>Antigravity AI:</b>\n\n{ai_resp}"

    # Fallback
    return f"⚡ <b>Received:</b> \"{t}\"\nInstruction noted for Job Deck."
