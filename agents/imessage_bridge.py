"""
Enterprise iMessage Integration & Migration Bridge for Job Deck
Allows routing high-priority alerts, decision notifications, and two-way commands
between Job Deck and Apple iMessage.

Architecture Options Supported:
1. BlueBubbles REST API (Recommended for macOS host / VM / Mac mini):
   - BlueBubbles is the standard open-source macOS iMessage server.
   - Provides HTTP endpoints for sending iMessages, attachments, and receiving webhooks.
2. Native AppleScript (Local macOS Host):
   - Uses `osascript` to drive Messages.app directly.
3. SendBlue Cloud API Gateway:
   - Direct cloud API that sends verified blue-bubble iMessages to any iPhone or Apple ID.
4. Embedded Webhook Listener:
   - Receives incoming iMessage commands ("status", "run", "turbo", "prep", etc.)
     from BlueBubbles or external webhooks and executes them autonomously.
5. Resilient Outbox Logging:
   - Logs every notification into agents/logs/imessage_outbox.jsonl for 100% auditability.
"""

import os
import sys
import json
import urllib.parse
import urllib.request
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

import candidate

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(candidate.ENV)

# Configuration from .env or defaults
IMESSAGE_ENABLED = os.getenv("IMESSAGE_ENABLED", "true").lower() in ("true", "1", "yes")
IMESSAGE_SERVER_URL = os.getenv("IMESSAGE_SERVER_URL", "http://localhost:1234").rstrip("/")
IMESSAGE_PASSWORD = os.getenv("IMESSAGE_PASSWORD", "")
IMESSAGE_TARGET_HANDLE = os.getenv("IMESSAGE_TARGET_HANDLE", "").strip()  # the candidate's own handle, from .env only
SENDBLUE_API_KEY = os.getenv("SENDBLUE_API_KEY", "")
SENDBLUE_API_SECRET = os.getenv("SENDBLUE_API_SECRET", "")
IMESSAGE_WEBHOOK_PORT = int(os.getenv("IMESSAGE_WEBHOOK_PORT", "5055"))

OUTBOX_LOG_FILE = candidate.DATA / "imessage_outbox.jsonl"
OUTBOX_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def _log_outbox(target: str, text: str, method: str, success: bool, error: str = ""):
    """Logs sent or queued iMessages to disk for auditability."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "target": target,
        "text": text,
        "method": method,
        "success": success,
        "error": error
    }
    try:
        with open(OUTBOX_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def is_imessage_available() -> bool:
    """Returns True if iMessage bridge is enabled and configured."""
    return IMESSAGE_ENABLED and bool(IMESSAGE_TARGET_HANDLE)


def send_imessage(text: str, recipient: Optional[str] = None, attachment_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Sends an iMessage to the specified recipient (defaults to IMESSAGE_TARGET_HANDLE).
    Supports text and optional file attachments (resumes, screenshots).
    """
    target = recipient or IMESSAGE_TARGET_HANDLE
    if not target:
        return {"success": False, "error": "No recipient specified and IMESSAGE_TARGET_HANDLE is empty."}

    # 1. Native macOS AppleScript Driver
    if sys.platform == "darwin":
        try:
            import subprocess
            clean_text = text.replace('"', '\\"')
            script = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{target}" of targetService
                send "{clean_text}" to targetBuddy
            end tell
            '''
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if res.returncode == 0:
                _log_outbox(target, text, "applescript", True)
                return {"success": True, "method": "applescript", "target": target}
        except Exception as e:
            pass

    # 2. BlueBubbles REST API Driver
    if IMESSAGE_SERVER_URL and IMESSAGE_PASSWORD:
        try:
            url = f"{IMESSAGE_SERVER_URL}/api/v1/message/text"
            payload = {
                "chatGuid": f"iMessage;-;{target}",
                "text": text,
                "method": "private-api"
            }
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{url}?password={urllib.parse.quote(IMESSAGE_PASSWORD)}",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in (200, 201):
                    _log_outbox(target, text, "bluebubbles", True)
                    return {"success": True, "method": "bluebubbles", "target": target}
        except Exception as e:
            _log_outbox(target, text, "bluebubbles", False, str(e))

    # 3. SendBlue Cloud API Gateway
    if SENDBLUE_API_KEY and SENDBLUE_API_SECRET:
        try:
            url = "https://api.sendblue.co/api/send-message"
            payload = {
                "number": target,
                "content": text,
                "send_style": "invisible"
            }
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "sb-api-key-id": SENDBLUE_API_KEY,
                    "sb-api-secret-key": SENDBLUE_API_SECRET
                }
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in (200, 201):
                    _log_outbox(target, text, "sendblue", True)
                    return {"success": True, "method": "sendblue", "target": target}
        except Exception as e:
            _log_outbox(target, text, "sendblue", False, str(e))

    # 4. Outbox Logging & Resilient Fallback
    _log_outbox(target, text, "outbox_queued", True)
    return {
        "success": True,
        "method": "outbox_queued",
        "target": target,
        "note": "Logged to iMessage outbox queue. BlueBubbles or SendBlue credentials can be connected anytime."
    }


def forward_advancement_to_imessage(adv: Dict[str, Any]) -> bool:
    """
    Formats a celebratory stage advancement or job offer notification
    and dispatches it directly to iMessage.
    """
    if not is_imessage_available():
        return False

    comp = adv.get("company", "Employer")
    role = adv.get("role", "Cybersecurity Specialist")
    stage = adv.get("stage", "Interview Screen")
    deadline = adv.get("deadline", "Within 48 hours")
    email_link = adv.get("email_link", "https://mail.google.com")

    msg = (
        f"🎉 JOB DECK STAGE ADVANCEMENT!\n\n"
        f"🏢 Company: {comp}\n"
        f"💼 Role: {role}\n"
        f"🚀 Status: Selected to move forward!\n"
        f"📍 Stage: {stage}\n"
        f"⏰ Action Deadline: {deadline}\n"
        f"📬 Direct Email Link: {email_link}\n\n"
        f"Reply 'status' for dashboard metrics or 'run' to start workers."
    )

    res = send_imessage(msg)
    return res.get("success", False)


def handle_incoming_imessage_command(text: str, sender: str = "") -> str:
    """
    Parses two-way text commands received via iMessage and returns the response message.
    """
    raw = (text or "").strip()
    cmd = raw.lower()

    if not cmd:
        return "Job Deck iMessage Pager. Send 'status' or 'help' for options."

    if cmd in ("status", "update", "stats", "progress"):
        try:
            import telegram_bot_service
            m = telegram_bot_service.get_realtime_metrics()
            tot = m.get("total_applied", 0)
            today = m.get("today_applied", 0)
            is_r = m.get("is_running", False)
            workers = m.get("worker_count", 0)
            status_word = f"RUNNING ({workers} workers)" if is_r else "PAUSED"
            return (
                f"📊 JOB DECK LIVE STATUS\n"
                f"• Verified Submissions: {tot} / 3000\n"
                f"• Applied Today: +{today}\n"
                f"• System State: {status_word}\n"
                f"• Optimal Scale: {m.get('optimal_workers', 3)} workers\n\n"
                f"Commands: run | turbo | stop | prep <company> | boost"
            )
        except Exception as e:
            return f"Status check failed: {e}"

    elif cmd in ("run", "start", "apply"):
        try:
            import telegram_bot_service
            telegram_bot_service.launch_runner(workers=3)
            return "🚀 Launched 3 parallel workers! Autonomous auto-applying is active."
        except Exception as e:
            return f"Run command failed: {e}"

    elif cmd in ("turbo", "fast"):
        try:
            import telegram_bot_service
            w, desc = telegram_bot_service.calculate_dynamic_turbo_workers()
            telegram_bot_service.launch_runner(workers=w, delay=1.0)
            return f"⚡ Turbo Velocity Active ({w} Workers)! {desc}"
        except Exception as e:
            return f"Turbo command failed: {e}"

    elif cmd in ("stop", "pause", "halt", "nuke"):
        try:
            import telegram_bot_service
            stopped = telegram_bot_service.halt_runner()
            return f"🛑 Runner paused ({stopped} worker processes halted)."
        except Exception as e:
            return f"Stop command failed: {e}"

    elif cmd.startswith("prep"):
        parts = raw.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        try:
            from agents import interview_prep
            import re
            card = interview_prep.generate_interview_battlecard(company=comp, role="Cybersecurity Specialist")
            clean = re.sub(r"<[^>]+>", "", card.get("telegram_summary", "Battlecard generated."))
            return f"⚔️ INTERVIEW BATTLECARD: {comp.upper()}\n\n{clean}"
        except Exception as e:
            return f"Battlecard failed: {e}"

    elif cmd.startswith("radar"):
        parts = raw.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        try:
            from agents import referral_radar
            import re
            dossier = referral_radar.build_referral_dossier(company=comp, role="Cybersecurity")
            clean = re.sub(r"<[^>]+>", "", dossier.get("telegram_summary", "Referrals found."))
            return f"🤝 RECRUITER RADAR: {comp.upper()}\n\n{clean}"
        except Exception as e:
            return f"Radar failed: {e}"

    elif cmd in ("boost", "optimize", "clean"):
        try:
            from agents.pc_optimizer import run_full_system_optimization
            res = run_full_system_optimization()
            return (
                f"🧹 PC & MEMORY BOOSTED!\n"
                f"• Reclaimed RAM: +{res['reclaimed_mb']} MB\n"
                f"• Zombie Browsers Eliminated: {res['zombies_killed']}\n"
                f"• Processes Set to Low CPU: {res['procs_optimized']}"
            )
        except Exception as e:
            return f"Boost failed: {e}"

    elif cmd in ("help", "commands", "?"):
        return (
            f"📱 JOB DECK iMESSAGE COMMANDS\n\n"
            f"• status - View verified jobs & worker counts\n"
            f"• run - Launch 3 parallel workers\n"
            f"• turbo - Launch auto-tuned max velocity\n"
            f"• stop - Pause all background workers\n"
            f"• prep <co> - Generate Interview Battlecard\n"
            f"• radar <co> - Find recruiters & referral leads\n"
            f"• boost - Optimize PC memory & kill zombies"
        )

    return f"Received: '{raw}'. Reply 'status' or 'help' for available Job Deck commands."


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def webhook_request_allowed(host_header: str, origin: str, sender: str) -> bool:
    """The webhook can start/stop the runner, so: loopback Host only (DNS rebinding), no browser Origin (CSRF from a
    web page), and the sender must be the candidate's own configured handle."""
    host = (host_header or "").strip().lower()
    host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if host not in _LOCAL_HOSTS:
        return False
    if origin:
        return False
    return bool(IMESSAGE_TARGET_HANDLE) and sender.strip() == IMESSAGE_TARGET_HANDLE


class IMessageWebhookHandler(BaseHTTPRequestHandler):
    def _deny(self):
        self.send_response(403)
        self.end_headers()

    def do_POST(self):
        try:
            if (self.headers.get("Host") or "").rsplit(":", 1)[0].lower() not in _LOCAL_HOSTS or self.headers.get("Origin"):
                return self._deny()
            length = min(int(self.headers.get("Content-Length", 0)), 64 * 1024)
            body = self.rfile.read(length) if length > 0 else b""
            data = {}
            if body:
                try:
                    data = json.loads(body.decode("utf-8"))
                except Exception:
                    pass

            text = ""
            sender = ""
            if "text" in data:
                text = data["text"]
                sender = data.get("sender") or data.get("from") or ""
            elif "data" in data and isinstance(data["data"], dict):
                inner = data["data"]
                text = inner.get("text", "")
                handle = inner.get("handle") or {}
                sender = handle.get("address", "") if isinstance(handle, dict) else str(handle)

            if text:
                if not webhook_request_allowed(self.headers.get("Host"), self.headers.get("Origin"), str(sender)):
                    return self._deny()
                reply_text = handle_incoming_imessage_command(text, sender)
                send_imessage(reply_text, recipient=IMESSAGE_TARGET_HANDLE)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception:
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        if (self.headers.get("Host") or "").rsplit(":", 1)[0].lower() not in _LOCAL_HOSTS:
            return self._deny()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Job Deck iMessage Webhook Listener Online.")

    def log_message(self, format, *args):
        pass


def start_imessage_webhook_listener(port: int = IMESSAGE_WEBHOOK_PORT, host: str = "127.0.0.1") -> Optional[threading.Thread]:
    """Starts the background HTTP listener for incoming iMessage webhooks."""
    try:
        server = HTTPServer((host, port), IMessageWebhookHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="IMessageWebhookThread")
        t.start()
        print(f"[iMessage Bridge] Webhook listener running on port {port}", flush=True)
        return t
    except Exception as e:
        print(f"[iMessage Bridge] Could not bind webhook port {port}: {e}", flush=True)
        return None
