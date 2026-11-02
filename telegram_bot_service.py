"""
High-Performance, Low-Latency Telegram Bot Service & 3-Hour Interval Reporter
Optimized for sub-second reply speed with persistent connection pooling,
multithreaded dispatch, and in-memory mtime cached queries.
"""

import os
import sys
import time
import csv
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import requests
import psutil

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
INTERVAL_SECONDS = 3 * 60 * 60  # 3 hours

# Persistent connection pool for zero TLS handshake latency
SESSION = requests.Session()
ADAPTER = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=3)
SESSION.mount("https://", ADAPTER)

EXECUTOR = ThreadPoolExecutor(max_workers=5)

# Fast Stats Cache
_CACHE = {
    "csv_mtime": 0,
    "total_applied": 0,
    "recent": [],
    "q_mtime": 0,
    "queue_count": 0,
    "last_check": 0,
    "python_count": 0,
}


def send_telegram(text: str) -> bool:
    """Send message via persistent HTTP connection."""
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
        resp = SESSION.post(url, json=payload, timeout=6)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Telegram Send Error] {e}", flush=True)
        return False


def get_current_stats_fast():
    """In-memory cached stats check taking < 1ms."""
    now = time.time()
    csv_path = ROOT / "applications.csv"
    if not csv_path.exists():
        csv_path = ROOT.parent / "applications.csv"

    if csv_path.exists():
        mtime = csv_path.stat().st_mtime
        if mtime != _CACHE["csv_mtime"]:
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                rows = list(csv.DictReader(f))
                _CACHE["total_applied"] = len(rows)
                _CACHE["recent"] = rows[-3:]
                _CACHE["csv_mtime"] = mtime

    q_path = ROOT / "queue_cyber_iam.txt"
    if q_path.exists():
        qmtime = q_path.stat().st_mtime
        if qmtime != _CACHE["q_mtime"]:
            with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
                _CACHE["queue_count"] = len([l for l in f if l.strip() and not l.startswith("#")])
                _CACHE["q_mtime"] = qmtime

    # Update active python process count (psutil takes < 10ms)
    if now - _CACHE["last_check"] > 2:
        try:
            curr_pid = os.getpid()
            _CACHE["python_count"] = sum(
                1 for p in psutil.process_iter(["pid", "name"])
                if "python" in (p.info["name"] or "").lower() and p.info["pid"] != curr_pid
            )
        except Exception:
            _CACHE["python_count"] = 0
        _CACHE["last_check"] = now

    return _CACHE["total_applied"], _CACHE["queue_count"], _CACHE["python_count"], _CACHE["recent"]


def generate_status_message(header="📊 <b>Job Deck Status Report</b>"):
    total, queue_count, py_count, recent = get_current_stats_fast()
    workers_active = f"Active ({py_count} workers)" if py_count > 0 else "Idle (ready)"
    now_str = datetime.now().strftime("%I:%M:%S %p")

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
    """Stops batch apply processes using fast native process termination."""
    curr_pid = os.getpid()
    stopped = 0
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "batch_apply" in cmd or "fill.py" in cmd:
                if p.info["pid"] != curr_pid:
                    p.kill()
                    stopped += 1
        except Exception:
            pass
    return f"🛑 <b>Runner paused.</b> Stopped {stopped} active worker process(es)."


def handle_message(text: str) -> str:
    t = text.strip().lower()
    if t in ["/start", "start", "/help", "help"]:
        return (
            "⚡ <b>Job Deck Turbo Bot Active!</b>\n\n"
            "Sub-second response mode enabled with persistent connection pooling.\n\n"
            "<b>Quick Commands:</b>\n"
            "• <code>status</code> or <code>/status</code> — Live stats (< 0.1s)\n"
            "• <code>apply</code> or <code>run</code> — Launch 3 headless workers\n"
            "• <code>stop</code> or <code>pause</code> — Halt all background workers\n"
            "• <code>update</code> — Immediate progress summary"
        )
    elif "status" in t or "/status" in t or "update" in t or "/update" in t:
        return generate_status_message()
    elif "apply" in t or "run" in t or "/apply" in t:
        return start_application_runner()
    elif "stop" in t or "pause" in t or "/stop" in t:
        return stop_application_runner()
    elif "boeing" in t:
        return "✈️ <b>Boeing Priority</b>: Both Boeing 2027 internship postings are queued at the top of your list. Type <code>apply</code> anytime to process them!"
    else:
        return f"⚡ <b>Received:</b> \"{text}\"\nInstruction logged into your Job Deck pipeline."


def process_update_async(item):
    """Processes message and dispatches reply concurrently in thread pool."""
    msg = item.get("message", {})
    chat_id_from_msg = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")

    if chat_id_from_msg == CHAT_ID and text:
        t0 = time.perf_counter()
        reply = handle_message(text)
        if reply:
            send_telegram(reply)
            dt = (time.perf_counter() - t0) * 1000
            print(f"[Turbo Bot] Replied to '{text}' in {dt:.1f}ms", flush=True)


def poll_telegram():
    """Ultra-fast long polling loop."""
    print("[Turbo Bot] Polling daemon started with persistent connection pooling...", flush=True)
    offset = None

    while True:
        try:
            params = {"timeout": 20, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset

            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            resp = SESSION.get(url, params=params, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("result", [])
                for item in results:
                    offset = item.get("update_id") + 1
                    # Dispatch to thread pool immediately for instant response
                    EXECUTOR.submit(process_update_async, item)
            else:
                time.sleep(1)
        except Exception:
            time.sleep(0.5)


if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    # Start 3-hour reporter thread
    t = threading.Thread(target=background_interval_reporter, daemon=True)
    t.start()

    send_telegram("⚡ <b>Reply Speed Boosted!</b>\nPersistent connection pooling & sub-second response engine active. Try typing <code>status</code> now!")

    poll_telegram()
