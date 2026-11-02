"""
Telegram Notification Helper for Job Deck
Sends real-time alerts to your Telegram when applications are submitted,
urgent inbox items are detected, or daily briefings are generated.
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured Telegram chat."""
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

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Telegram Notify Error] {e}")
        return False


def notify_applied(company: str, role: str, job_url: str = ""):
    """Notify when an application is successfully submitted."""
    url_link = f'\n<a href="{job_url}">View Job Posting</a>' if job_url else ""
    msg = (
        f"🎯 <b>Application Submitted!</b>\n\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"💼 <b>Role:</b> {role}"
        f"{url_link}"
    )
    return send_message(msg)


def notify_urgent_inbox(company: str, subject: str, action: str):
    """Notify when an interview, assessment, or urgent reply arrives."""
    msg = (
        f"🚨 <b>Urgent Inbox Action!</b>\n\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"✉️ <b>Subject:</b> {subject}\n"
        f"⚡ <b>Action:</b> {action}"
    )
    return send_message(msg)


def test_connection():
    """Verify Telegram bot configuration."""
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
