"""
Telegram Notification & Smart Question Resolver for Job Deck
Intercepts known candidate facts and AI-resolvable questions so the user is never asked
questions the system already knows. Dispatches only novel, personal-choice questions.
"""

import os
import re
import json
import urllib.request
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Strict Known Facts Knowledge Base
KNOWN_FACTS_MAP = [
    # Location
    (r"\b(location|city)\b", "Atlanta, GA", r"Atlanta|Powder Springs|Georgia|GA"),
    (r"\bstate\b", "Georgia", r"Georgia|^GA\b"),
    (r"\bcountry|territory\b", "United States", r"United States|USA|^US\b"),
    (r"\bzip|postal\b", "30127", r"30127"),
    (r"\baddress\b", "4020 Saint George Walk SW, Powder Springs, GA 30127", None),

    # Education
    (r"\b(school|university|college|alma mater)\b(?!.*cap.exempt)", "Kennesaw State University", r"Kennesaw|KSU"),
    (r"\bdegree\b", "Bachelor of Science", r"Bachelor|B\.S|Undergraduate"),
    (r"\bdiscipline|major|field of study\b", "Cybersecurity", r"Cybersecurity|Cyber|Information Security|Computer"),
    (r"\bgpa\b|grade point", "3.35", r"3\.35|3\.0\s*-\s*3\.5|3\.0\+"),
    (r"\bgraduat.*year|\byear of graduation\b|\bgraduation\b", "2026", r"2026|2027|2028|Dec 2026"),
    (r"\bstudent.*status|class standing|academic status\b|sophomore.*junior.*senior", "Senior", r"Senior|Junior|Undergraduate"),

    # Work Auth & Clearance
    (r"h-?1b", "No", r"^No\b"),
    (r"authori[sz]ed to work|legally eligible|authorized in the (united states|us)|work authorization", "Yes", r"^Yes\b"),
    (r"sponsorship|require.*visa|visa sponsorship|now or in the future require", "No", r"^No\b"),
    (r"active.*security clearance|hold.*clearance", "No", r"^No\b"),
    (r"eligible to obtain.*clearance", "Yes", r"^Yes\b"),
    (r"18 years|at least 18|age of 18|over 18|legal age", "Yes", r"^Yes\b|^18\b|Under 30"),
    (r"what is your.*age|current age", "Under 30", r"Under 30|< 30|18-29"),

    # Demographics & EEO
    (r"\bgender\b|\bsex\b", "Male", r"^Male\b|Decline|Prefer not"),
    (r"\brace\b|\bethnic", "Black or African American", r"Black|African American|Decline|Prefer not"),
    (r"\bveteran\b", "I am not a protected veteran", r"not a protected veteran|not a veteran|^No\b"),
    (r"\bdisabilit", "No, I do not have a disability", r"No, I do not have a disability|do not have a disability|^No\b"),
    (r"\bhispanic|latino\b", "No", r"^No\b"),
    (r"\btransgender\b", "No", r"^No\b"),
    (r"\bpronouns?\b", "He/Him", r"He/Him|he/him|^He\b"),
    (r"sexual orientation", "Heterosexual", r"Heterosexual|Straight|Decline|Prefer not"),
    (r"\bprefix\b|\btitle\b", "Mr.", r"Mr\.|Mr"),
    (r"privacy policy|consent to.*process|candidate privacy", "I agree", r"agree|consent|accept"),

    # Experience, Skills & Agreements
    (r"production.*level code|production.*code", "Yes", r"^Yes\b"),
    (r"applied cryptography|cryptographic|security capabilities|security boundaries", "Yes", r"^Yes\b"),
    (r"active on the platform|years.*active", "3", r"3|1-3|2-4"),
    (r"how did you (first )?(hear|learn) about", "Job Board - LinkedIn", r"LinkedIn|Job Board"),
    (r"military experience|veteran status mapping", "No", r"^No\b|Decline"),
    (r"start date month", "May", r"May|June"),
    (r"end date month", "August", r"August|July"),
    (r"\bregion\b", "Georgia", r"Georgia|^GA\b"),

    # Personal Identifiers & Agreements
    (r"first name", "Michael", None),
    (r"last name", "Azuka", None),
    (r"full name|legal name", "Michael Azuka", None),
    (r"email", "mazuka146@gmail.com", None),
    (r"phone", "404-645-0373", None),
    (r"linkedin", "https://www.linkedin.com/in/michael-azuka", None),
    (r"github", "https://github.com/1Zuski", None),
    (r"certify|electronic signature|type your name|signature", "Michael Azuka", None),
    (r"sms|text message|consent to receive", "Yes", r"^Yes\b|Consent"),
    (r"previously applied|worked (for|with) us before|employed by.*before", "No", r"^No\b"),
    (r"relative.*work|family.*work|conflict of interest", "No", r"^No\b"),
    (r"non-?compet|non-?solicit", "No", r"^No\b"),
    (r"intellectual property", "No", r"^No\b"),
    (r"military officer in grades o-?7|covered dod official", "No", r"^No\b"),
]

# Track recently asked questions to eliminate spam
_RECENTLY_ASKED = set()


def send_message(text: str, reply_markup=None, parse_mode: str = "HTML") -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN).strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", CHAT_ID).strip()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as he:
        # If HTML entity parsing failed (HTTP 400), fall back to clean plain text
        if he.code == 400 and parse_mode:
            try:
                clean_text = re.sub(r"<[^>]+>", "", text)
                clean_text = clean_text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                payload["text"] = clean_text
                payload.pop("parse_mode", None)
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status == 200
            except Exception as ex2:
                print(f"[Telegram Notify Plaintext Retry Error] {ex2}")
                return False
        print(f"[Telegram Notify Error] {he}")
        return False
    except Exception as e:
        print(f"[Telegram Notify Error] {e}")
        return False


def notify_applied(company: str, role: str, job_url: str = ""):
    url_link = f'\n<a href="{job_url}">View Job Posting</a>' if job_url else ""
    msg = (
        f"🎯 <b>Application Submitted!</b>\n\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"💼 <b>Role:</b> {role}"
        f"{url_link}"
    )
    return send_message(msg)


def notify_urgent_inbox(company: str, subject: str, action: str):
    msg = (
        f"🚨 <b>Urgent Inbox Action!</b>\n\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"✉️ <b>Subject:</b> {subject}\n"
        f"⚡ <b>Action:</b> {action}"
    )
    return send_message(msg)


def check_and_auto_resolve_fact(question: str, options: list = None) -> bool:
    """Checks if the question matches known candidate facts and silently saves rule."""
    import telegram_query_engine
    q_norm = question.strip()

    for pattern, ans, opt_pat in KNOWN_FACTS_MAP:
        if re.search(pattern, q_norm, re.I):
            # Known fact! Save rule silently to profile.json
            fake_item = telegram_query_engine.add_pending_question(q_norm, options)
            if fake_item:
                telegram_query_engine.resolve_pending_question(fake_item["id"], ans)
                print(f"[Auto-Resolved Known Fact] '{q_norm[:50]}' -> '{ans}' saved to profile.json silently.")
            return True
    return False


def ask_question_interactive(question: str, options: list = None, company: str = ""):
    """Dispatches a form question to Telegram ONLY if it cannot be auto-resolved by AI Brain."""
    q_clean = question.strip()
    if not q_clean or len(q_clean) < 3:
        return False

    # 1. Multi-Tier Intelligent AI Resolver (Resolves silently without pinging user)
    try:
        from agents import intelligent_resolver
        res = intelligent_resolver.resolve_field(q_clean, options=options, company=company)
        if res and res.get("answer"):
            print(f"[Intelligent Auto-Resolution] '{q_clean[:50]}' -> '{res['answer']}' (Silently resolved, not sent to Telegram)")
            return True
    except Exception as ex:
        pass

    # 2. Check known fact map
    if check_and_auto_resolve_fact(q_clean, options):
        return True

    # 3. Permanent suppression for standard screening & EEO questions (never bother user)
    suppress_patterns = re.compile(
        r"gender|race|ethnic|veteran|disabilit|hispanic|latino|pronoun|sexual\s*orientation|"
        r"address|city|county|state|zip|postal|phone|email|name|signature|certify|"
        r"work\s*authorization|citizen|sponsorship|visa|non-?compete|non-?solicit|felon|"
        r"school|university|degree|major|gpa|graduation|date\s*of\s*birth|birth|age|"
        r"how\s*did\s*you\s*hear|referral|source|sms|text\s*message|privacy\s*policy|"
        r"language|driver|relocate|commute|clearance|export|itar",
        re.I
    )
    if suppress_patterns.search(q_clean):
        return True

    # 4. Strict session deduplication & anti-spam rate limit
    if q_clean.lower() in _RECENTLY_ASKED:
        return True
    _RECENTLY_ASKED.add(q_clean.lower())

    if len(_RECENTLY_ASKED) > 3:
        print(f"[Anti-Spam Filter] Suppressed Telegram alert for '{q_clean[:40]}' (Session rate limit reached).")
        return True

    import telegram_query_engine
    item = telegram_query_engine.add_pending_question(q_clean, options, company)
    if not item:
        return False

    comp_str = f" for <b>{company}</b>" if company else ""
    msg = (
        f"❓ <b>Input Needed{comp_str}:</b>\n\n"
        f"<i>\"{q_clean}\"</i>\n"
    )

    clean_opts = [o.strip() for o in (options or []) if o and len(o.strip()) < 35][:6]
    reply_markup = None
    if clean_opts:
        keyboard = []
        row = []
        for opt in clean_opts:
            cb_data = f"ans_{item['id']}_{opt}"[:60]
            row.append({"text": opt, "callback_data": cb_data})
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        reply_markup = {"inline_keyboard": keyboard}
        msg += "\nTap an answer below, or type: <code>answer: [your answer]</code>"
    else:
        msg += "\nReply with: <code>answer: [your answer]</code>"

    return send_message(msg, reply_markup=reply_markup)


def test_connection():
    token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN).strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", CHAT_ID).strip()
    if not token or not chat_id:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing in .env")
        return False

    ok = send_message("🚀 <b>Job Deck Connected!</b>\nTelegram notifications are active.")
    if ok:
        print("[OK] Telegram notification sent successfully!")
    else:
        print("[X] Failed to send Telegram notification. Check token and chat ID.")
    return ok


if __name__ == "__main__":
    test_connection()
