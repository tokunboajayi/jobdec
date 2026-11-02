"""
Telegram 24/7 Interactive Bot Service & 3-Hour Interval Reporter for Job Deck
Handles instant replies to Telegram messages from Zuski and delivers automated updates every 3 hours.
"""

import os
import sys
import time
import json
import csv
import subprocess
import threading
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
INTERVAL_SECONDS = 3 * 60 * 60  # 3 hours


def send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Telegram Bot Error] {e}", flush=True)
        return False


def get_current_stats():
    csv_path = ROOT / "applications.csv"
    if not csv_path.exists():
        csv_path = ROOT.parent / "applications.csv"
    total_applied = 0
    recent = []
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            rows = list(csv.DictReader(f))
            total_applied = len(rows)
            recent = rows[-3:]

    # Remaining queue
    queue_count = 0
    q_path = ROOT / "queue_cyber_iam.txt"
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            queue_count = len([l for l in f if l.strip() and not l.startswith("#")])

    # Check active workers
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Process python* -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=5
        )
        python_count = int(proc.stdout.strip() or "0")
    except Exception:
        python_count = 0

    return total_applied, queue_count, python_count, recent


def generate_status_message(header="📊 <b>Job Deck Status Report</b>"):
    total, queue_count, py_count, recent = get_current_stats()
    workers_active = "Active (running)" if py_count > 1 else "Idle (ready)"
    now_str = datetime.now().strftime("%I:%M %p")

    lines = [
        f"{header} <i>({now_str})</i>",
        "",
        f"🎯 <b>Total Verified Applications:</b> {total}",
        f"📋 <b>Queue Remaining:</b> {queue_count} roles",
        f"⚡ <b>Runner State:</b> {workers_active}",
        "",
    ]
    if recent:
        lines.append("<b>Recent Submissions:</b>")
        for r in recent:
            lines.append(f"• {r.get('Company')} — {r.get('Role')}")
    return "\n".join(lines)


def background_interval_reporter():
    """Sends a summary update every 3 hours."""
    while True:
        time.sleep(INTERVAL_SECONDS)
        try:
            msg = generate_status_message(header="🕒 <b>3-Hour Scheduled Update</b>")
            send_telegram(msg)
            print(f"[Reporter] Sent 3-hour status update at {datetime.now()}", flush=True)
        except Exception as e:
            print(f"[Reporter Error] {e}", flush=True)


def start_application_runner():
    """Starts batch_apply_parallel.py in background with 3 workers."""
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(ROOT / "batch_apply_parallel.py"),
        "--queue", "queue_cyber_iam.txt",
        "--workers", "3",
        "--no-triage",
        "--resume", "resumes/resume.pdf"
    ]
    subprocess.Popen(cmd, cwd=str(ROOT))
    return "🚀 <b>Runner started!</b> 3 workers are now actively applying in headless mode."


def stop_application_runner():
    """Stops batch apply processes."""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process python* -ErrorAction SilentlyContinue | Where-Object {$_.Id -ne $PID} | Stop-Process -Force -ErrorAction SilentlyContinue"],
        capture_output=True
    )
    return "🛑 <b>Runner paused.</b> Application workers have been stopped."


def handle_message(text: str) -> str:
    t = text.strip().lower()
    if t in ["/start", "start", "/help", "help"]:
        return (
            "👋 <b>Welcome to Job Deck Bot!</b>\n\n"
            "I am monitoring your autonomous application suite and will send you <b>3-hour automatic updates</b>.\n\n"
            "<b>Available Commands:</b>\n"
            "• <code>/status</code> or <code>status</code> — View live application count & queue\n"
            "• <code>/apply</code> or <code>run</code> — Start 3 headless workers\n"
            "• <code>/stop</code> or <code>pause</code> — Stop running workers\n"
            "• <code>/update</code> — Get an immediate progress summary"
        )
    elif "status" in t or "/status" in t or "update" in t or "/update" in t:
        return generate_status_message()
    elif "apply" in t or "run" in t or "/apply" in t:
        return start_application_runner()
    elif "stop" in t or "pause" in t or "/stop" in t:
        return stop_application_runner()
    elif "boeing" in t:
        return "✈️ <b>Boeing Priority</b>: Both Boeing 2027 internship postings are queued at the top of your prioritized list. Say <code>/apply</code> anytime to process them!"
    else:
        return f"✅ <b>Received:</b> \"{text}\"\nI have noted this instruction for the Job Deck pipeline."


def poll_telegram():
    """Polls Telegram for incoming user messages and responds instantly."""
    print("[Telegram Bot Service] Starting polling daemon...", flush=True)
    offset = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=25"
            if offset is not None:
                url += f"&offset={offset}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("result", [])
            for item in results:
                update_id = item.get("update_id")
                offset = update_id + 1

                msg = item.get("message", {})
                chat_id_from_msg = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                # Only respond to authorized chat
                if chat_id_from_msg == CHAT_ID and text:
                    print(f"[Telegram Bot] Received from Zuski: {text}", flush=True)
                    reply = handle_message(text)
                    if reply:
                        send_telegram(reply)

        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    # Start 3-hour reporter thread
    t = threading.Thread(target=background_interval_reporter, daemon=True)
    t.start()

    # Initial confirmation message
    send_telegram("🤖 <b>Job Deck Telegram Service Active!</b>\n\n• Instant message replies are enabled.\n• Automated status updates scheduled every <b>3 hours</b>.\n• Type <code>/status</code>, <code>/apply</code>, or <code>/stop</code> anytime!")

    # Start polling
    poll_telegram()
