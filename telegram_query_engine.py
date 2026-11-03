"""
Conversational Query & Rule-Answering Engine for Job Deck Telegram Bot
Powered by Google DeepMind Gemini AI + live database search across applications, queue, and inbox.
Features persistent memory of the Antigravity pair-programming session and multi-turn chat context.
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
HISTORY_FILE = ROOT / "telegram_history.json"
MEMORY_FILE = ROOT / "conversation_memory.md"
PROFILE_PATH = ROOT / "profile.json"
NEEDS_YOU_PATH = ROOT / "agents" / "needs_you.md"
APPLICATIONS_PATH = ROOT / "applications.csv"
if not APPLICATIONS_PATH.exists():
    APPLICATIONS_PATH = ROOT.parent / "applications.csv"


def load_chat_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_chat_history(history):
    # Keep last 20 messages for context
    HISTORY_FILE.write_text(json.dumps(history[-20:], indent=2), encoding="utf-8")


def load_session_memory():
    if MEMORY_FILE.exists():
        try:
            return MEMORY_FILE.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


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


def sanitize_for_telegram(text: str) -> str:
    """Sanitizes text for safe Telegram HTML parsing, escaping rogue tags and stripping action blocks."""
    if not text:
        return ""
    # Strip any action blocks (complete or incomplete)
    text = re.sub(r"<<+ACTION.*?>>+", "", text, flags=re.DOTALL)
    text = re.sub(r"<<+ACTION.*$", "", text, flags=re.DOTALL)
    text = text.replace("<<<", "").replace(">>>", "")

    # Normalize common markdown formatting into valid Telegram HTML
    text = re.sub(r"\*\*([^*]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", text)

    # Allowed Telegram HTML tags: b, strong, i, em, u, ins, s, strike, del, a, code, pre, blockquote
    allowed_pattern = re.compile(r"^</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote|a(?:\s+href=\"[^\"]*\")?)>$", re.I)

    def clean_tag(m):
        full = m.group(0)
        if allowed_pattern.match(full):
            return full
        return full.replace("<", "&lt;").replace(">", "&gt;")

    text = re.sub(r"<[^>]+>", clean_tag, text)
    return text.strip()


def execute_gemini_action(action_dict: dict) -> str:
    """Executes real modifications to Job Deck based on Gemini's action block."""
    action = action_dict.get("action")
    if action == "update_rule":
        q = action_dict.get("q", "").strip()
        a = action_dict.get("a", "").strip()
        if q and a:
            try:
                if PROFILE_PATH.exists():
                    p_data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
                else:
                    p_data = {"rules": []}
                new_rule = {
                    "q": q.lower(),
                    "a": a,
                    "src": "telegram_gemini_action",
                    "added": str(date.today())
                }
                if action_dict.get("option"):
                    new_rule["option"] = action_dict["option"]
                p_data["rules"].insert(0, new_rule)
                PROFILE_PATH.write_text(json.dumps(p_data, indent=2), encoding="utf-8")
                return f"\n\n⚙️ <i>Updated profile rule: '<b>{q}</b>' ➔ '<b>{a}</b>'</i>"
            except Exception as e:
                return f"\n\n⚠️ <i>Failed updating rule: {e}</i>"

    elif action == "add_queue":
        url = action_dict.get("url", "").strip()
        co = action_dict.get("company", "Target Company").strip()
        role = action_dict.get("role", "Prioritized Role").strip()
        if url:
            q_path = ROOT / "queue_cyber_iam.txt"
            with open(q_path, "a", encoding="utf-8") as f:
                f.write(f"{co} {role}   {url}\n")
            return f"\n\n⚙️ <i>Added <b>{co} — {role}</b> to the active queue!</i>"

    elif action == "remove_queue":
        kw = action_dict.get("keyword", "").strip().lower()
        if kw:
            q_path = ROOT / "queue_cyber_iam.txt"
            if q_path.exists():
                lines = [l for l in q_path.read_text(encoding="utf-8").splitlines() if kw not in l.lower()]
                q_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return f"\n\n⚙️ <i>Removed postings matching '<b>{kw}</b>' from queue.</i>"

    elif action == "control_runner":
        cmd = action_dict.get("command", "").lower()
        try:
            import telegram_bot_service
            if cmd in ["start", "run"]:
                telegram_bot_service.launch_runner(workers=3)
                return "\n\n⚙️ <i>Launched 3 parallel workers in headless mode!</i>"
            elif cmd == "turbo":
                telegram_bot_service.launch_runner(workers=4)
                return "\n\n⚙️ <i>Turbo mode activated (4 workers)!</i>"
            elif cmd in ["stop", "pause"]:
                stopped = telegram_bot_service.halt_runner()
                return f"\n\n⚙️ <i>Halted {stopped} active worker process(es). System idle.</i>"
        except Exception as e:
            return f"\n\n⚠️ <i>Runner command error: {e}</i>"

    return ""


def ask_gemini_ai(user_prompt: str) -> str:
    """Invokes Google Gemini 3.5 Flash with full session memory, multi-turn context, and active action execution."""
    key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()
    if not key:
        return ""

    session_mem = load_session_memory()

    system_instruction = (
        "You are Antigravity, the elite agentic AI coding assistant developed by Google DeepMind. "
        "You are currently chatting directly with Michael Azuka on Telegram.\n\n"
        "=== COMPREHENSIVE SESSION MEMORY FROM ANTIGRAVITY IDE ===\n"
        f"{session_mem}\n"
        "========================================================\n\n"
        "You remember and have complete context of the entire pairing session: the 350 submitted applications, "
        "the 3-worker parallel runner, the candidate profile (Michael Azuka, KSU Cybersecurity B.S. & IT minor, "
        "Powder Springs GA 30127), and the full Job Deck infrastructure.\n\n"
        "YOU HAVE ACTIVE EXECUTION POWERS: Michael can ask you to make real changes to his Job Deck. "
        "When Michael instructs you to update facts/rules, add or remove jobs from the queue, or control the runner, "
        "answer clearly in Telegram HTML format and ALWAYS append an executable action block in this EXACT syntax at the very end:\n\n"
        "<<<ACTION\n"
        '{"action": "update_rule", "q": "question or field name pattern", "a": "value"}\n'
        ">>>\n"
        "or\n"
        "<<<ACTION\n"
        '{"action": "add_queue", "url": "https://...", "company": "Company Name", "role": "Role Title"}\n'
        ">>>\n"
        "or\n"
        "<<<ACTION\n"
        '{"action": "remove_queue", "keyword": "company or keyword to remove"}\n'
        ">>>\n"
        "or\n"
        "<<<ACTION\n"
        '{"action": "control_runner", "command": "start"|"stop"|"turbo"}\n'
        ">>>\n\n"
        "Only append <<<ACTION >>> when Michael asks for a change or control. Otherwise respond normally."
    )

    history = load_chat_history()
    contents = []
    for turn in history:
        contents.append({"role": turn["role"], "parts": [{"text": turn["text"]}]})
    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600}
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
            answer = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Parse and execute any embedded actions
            m_act = re.search(r"<<+ACTION\s*(\{.*?\})\s*>>+", answer, re.DOTALL)
            if not m_act:
                m_act = re.search(r"<<+ACTION\s*(\{.*?\})", answer, re.DOTALL)
            action_notice = ""
            if m_act:
                try:
                    act_dict = json.loads(m_act.group(1))
                    action_notice = execute_gemini_action(act_dict)
                except Exception as ex:
                    print(f"[Gemini Action Parse Error] {ex}")

            # Clean up all action blocks completely and sanitize HTML
            answer = re.sub(r"<<+ACTION.*?>>+", "", answer, flags=re.DOTALL)
            answer = re.sub(r"<<+ACTION.*$", "", answer, flags=re.DOTALL).strip()
            answer = sanitize_for_telegram(answer)
            if action_notice:
                answer += action_notice

            # Record turn in history
            history.append({"role": "user", "text": user_prompt})
            history.append({"role": "model", "text": answer})
            save_chat_history(history)

            return answer
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

    # Profile / identity facts
    if any(k in t_lower for k in ["birthday", "birth date", "birthdate", "when was i born", "how old", "what is my age", "my age"]):
        return (
            "🎂 <b>Candidate Profile — Age & Birthday:</b>\n\n"
            "• <b>Date of Birth:</b> September 20, 2002 (09/20/2002)\n"
            "• <b>Age:</b> 24 years of age\n"
            "• <b>Legal Status:</b> Over 18 years of age (Adult)\n\n"
            "<i>Registered across profile.json invariants and active on all application workers.</i>"
        )

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

    # 6. User answering a question (direct match or 'answer: ...')
    pending = load_pending_questions()
    if len(pending) == 1:
        opts_lower = [o.lower() for o in pending[0].get("options", [])]
        if t_lower in ["yes", "no", "i agree", "agree", "decline"] or (opts_lower and t_lower in opts_lower):
            res = resolve_pending_question(pending[0]["id"], t)
            return res["msg"]

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

    # 7. Ask Google Gemini AI with session memory & multi-turn history
    ai_resp = ask_gemini_ai(t)
    if ai_resp:
        return f"✨ <b>Antigravity AI:</b>\n\n{ai_resp}"

    # Fallback
    return f"⚡ <b>Received:</b> \"{t}\"\nInstruction noted for Job Deck."
