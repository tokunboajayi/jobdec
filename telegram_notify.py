"""
Telegram notifications and the outbox reader for Job Deck.
fill.py never calls Telegram: it writes unanswered questions to candidate.DATA/unanswered.json and submissions to
candidate.APPLICATIONS. The bot service calls process_outbox() to turn those into question prompts and alerts.
Nothing here saves an answer: only the user's own button tap or "answer <id>: ..." reply does (C-4).
"""

import os
import re
import csv
import json
import time
import urllib.error
import urllib.request
import urllib.parse

import candidate
from telegram_query_engine import FileLock, h, question_id, _read_json, _write_json_atomic

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

OUTBOX_QUESTIONS = candidate.DATA / "unanswered.json"
OUTBOX_STATE = candidate.DATA / "telegram_outbox_state.json"
ASKED_FILE = candidate.DATA / "telegram_asked.json"
ASK_TTL = 24 * 3600   # the same question is asked at most once a day, however many workers hit it (A-6)
MAX_ACTIVE_QUESTIONS = 3  # anti-spam: more wait in the outbox until these are answered or expire
MAX_APP_ALERTS_PER_POLL = 10


def send_message(text: str, reply_markup=None, parse_mode: str = "HTML"):
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
            resp_body = resp.read().decode("utf-8")
            res_data = json.loads(resp_body)
            if res_data.get("ok"):
                msg_id = res_data.get("result", {}).get("message_id")
                return msg_id if msg_id is not None else True
            return False
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
                    resp_body = resp.read().decode("utf-8")
                    res_data = json.loads(resp_body)
                    if res_data.get("ok"):
                        msg_id = res_data.get("result", {}).get("message_id")
                        return msg_id if msg_id is not None else True
                    return False
            except Exception as ex2:
                print(f"[Telegram Notify Plaintext Retry Error] {ex2}")
                return False
        print(f"[Telegram Notify Error] {he}")
        return False
    except Exception as e:
        print(f"[Telegram Notify Error] {e}")
        return False


def delete_message(message_id: int, chat_id: str = None) -> bool:
    """Silently deletes a message by ID from the Telegram chat."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN).strip()
    c_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", CHAT_ID).strip()
    if not token or not c_id or not message_id:
        return False

    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    payload = {"chat_id": c_id, "message_id": int(message_id)}
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            return res_data.get("ok", False)
    except Exception:
        # Silently ignore if message already deleted or older than 48h
        return False


def notify_applied(company: str, role: str, job_url: str = ""):
    url_link = f'\n<a href="{h(job_url)}">View Job Posting</a>' if str(job_url).startswith(("http://", "https://")) else ""
    msg = (
        f"🎯 <b>Application Submitted!</b>\n\n"
        f"🏢 <b>Company:</b> {h(company)}\n"
        f"💼 <b>Role:</b> {h(role)}"
        f"{url_link}"
    )
    msg_id = send_message(msg)
    if msg_id and isinstance(msg_id, int):
        try:
            import telegram_query_engine
            telegram_query_engine.record_application_message(
                message_id=msg_id,
                company=company,
                role=role,
                job_url=job_url,
                chat_id=CHAT_ID
            )
        except Exception as e:
            print(f"[Telegram Notify] could not track message: {e}")
    return msg_id


def notify_urgent_inbox(company: str, subject: str, action: str):
    msg = (
        f"🚨 <b>Urgent Inbox Action!</b>\n\n"
        f"🏢 <b>Company:</b> {h(company)}\n"
        f"✉️ <b>Subject:</b> {h(subject)}\n"
        f"⚡ <b>Action:</b> {h(action)}"
    )
    return send_message(msg)


def ask_question_interactive(question: str, options: list = None, company: str = ""):
    """Sends one form question to Telegram, deduped by question hash across workers/runs (A-6).
    Returns True when the question was sent or was already asked recently, False when it was not sent."""
    import telegram_query_engine
    q_clean = " ".join((question or "").split())
    if len(q_clean) < 4:
        return False
    if not os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN).strip() or not os.getenv("TELEGRAM_CHAT_ID", CHAT_ID).strip():
        return False

    q_id = question_id(q_clean)
    with FileLock(ASKED_FILE):
        asked = _read_json(ASKED_FILE, {})
        now = time.time()
        if now - asked.get(q_id, 0) < ASK_TTL:
            return True
        if len(telegram_query_engine.load_pending_questions()) >= MAX_ACTIVE_QUESTIONS:
            return False

        item = telegram_query_engine.add_pending_question(q_clean, options, company)
        if not item:
            return False

        comp_str = f" for <b>{h(company)}</b>" if company else ""
        msg = f"❓ <b>Input Needed{comp_str}:</b>\n\n<i>\"{h(q_clean)}\"</i>\n"
        # callback carries the question id and the option's index into item["options"], so it round-trips (C-3)
        buttons = [{"text": o.strip(), "callback_data": f"ans|{q_id}|{i}"}
                   for i, o in enumerate(item["options"]) if o and len(o.strip()) < 35][:6]
        reply_markup = None
        if buttons:
            reply_markup = {"inline_keyboard": [buttons[i:i + 2] for i in range(0, len(buttons), 2)]}
            msg += "\nTap an answer below, or type:"
        else:
            msg += "\nReply with:"
        msg += f" <code>answer {q_id}: your answer</code>"
        msg += "\n\n⏱️ <i>Auto-expires and disappears in 5 minutes</i>"

        msg_id = send_message(msg, reply_markup=reply_markup)
        if not msg_id:
            return False
        asked[q_id] = now
        _write_json_atomic(ASKED_FILE, asked)

    if isinstance(msg_id, int):
        telegram_query_engine.record_question_message(
            q_id=q_id,
            question=q_clean,
            message_id=msg_id,
            company=company,
            chat_id=os.getenv("TELEGRAM_CHAT_ID", CHAT_ID),
            ttl_seconds=300
        )
    return True


def process_outbox() -> dict:
    """Reads what fill.py wrote (unanswered.json, applications.csv) and sends prompts / alerts. Called by the bot."""
    sent_q = 0
    data = _read_json(OUTBOX_QUESTIONS, [])
    for entry in data if isinstance(data, list) else []:
        company = urllib.parse.urlparse(str(entry.get("url", ""))).hostname or ""
        for q in entry.get("questions") or []:
            if isinstance(q, dict) and ask_question_interactive(q.get("label", ""), q.get("options"), company):
                sent_q += 1

    # shortcut: new submissions are detected by row count; an upsert of an existing row is not re-announced
    sent_apps = 0
    rows = []
    if candidate.APPLICATIONS.exists():
        with open(candidate.APPLICATIONS, "r", encoding="utf-8", errors="ignore") as f:
            rows = list(csv.DictReader(f))
    state = _read_json(OUTBOX_STATE, {})
    seen = state.get("apps_seen")
    if seen is None or seen > len(rows):
        seen = len(rows)  # first run (or ledger rewritten): don't replay history
    for r in rows[seen:seen + MAX_APP_ALERTS_PER_POLL]:
        if notify_applied(r.get("Company", ""), r.get("Role", ""), r.get("Job URL", "")):
            sent_apps += 1
        seen += 1
    if state.get("apps_seen") != seen:
        _write_json_atomic(OUTBOX_STATE, {**state, "apps_seen": seen})
    return {"questions": sent_q, "applications": sent_apps}


def cleanup_expired_questions(force_all: bool = False) -> int:
    """Deletes expired (or all if force_all=True) question messages from Telegram."""
    import telegram_query_engine
    if force_all:
        msg_ids = telegram_query_engine.clear_all_pending_questions()
        deleted = 0
        for mid in msg_ids:
            if delete_message(mid):
                deleted += 1
        return deleted

    expired = telegram_query_engine.get_expired_question_messages()
    deleted = 0
    for item in expired:
        mid = item.get("message_id")
        if mid and delete_message(mid, item.get("chat_id")):
            deleted += 1
            telegram_query_engine.mark_question_deleted_or_resolved(message_id=mid)
    return deleted


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
