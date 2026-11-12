"""
Enterprise Telegram Command & Control Dashboard for Job Deck
Built on python-telegram-bot (v22+) with two-way question/answer capabilities,
interactive dynamic touch buttons that adapt to live process state, real-time metrics,
and JobQueue 3-hour scheduled updates.
"""

import os
import re
import sys
import csv
import json
import glob
import hashlib
import threading
import subprocess
import asyncio
import time as time_mod
from datetime import datetime, date, time as dt_time, timedelta
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Tuple, Union
import psutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import candidate
import telegram_notify
import telegram_query_engine
from telegram_query_engine import h
from agents.telegram_visuals import (
    find_latest_tailored_resume,
    find_latest_tailored_letter,
    render_pdf_to_image_bytes,
    capture_active_worker_screenshot,
)
from agents.voice_transcriber import transcribe_voice_bytes
from agents.interview_simulator import (
    start_interview_session,
    evaluate_and_advance_interview,
    is_in_interview,
    INTERVIEW_SESSIONS,
)
from agents.offer_negotiator import analyze_offer_and_strategize
from agents.ats_gap_analyzer import analyze_ats_gap
from agents.decision_tracker import (
    scan_and_track_decision_emails,
    format_advancement_telegram_alert,
    get_decision_pipeline_summary,
    update_application_stage,
)

ROOT = Path(__file__).resolve().parent
load_dotenv(candidate.ENV)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_STR = os.getenv("TELEGRAM_CHAT_ID", "").strip()
AUTHORIZED_USER_ID = int(CHAT_ID_STR) if CHAT_ID_STR.isdigit() else 0

PINNED_STATUS_FILE = candidate.DATA / "pinned_status.json"
ACTIVE_HUD_STATE = {"chat_id": None, "message_id": None}
ACTIVE_DECISION_TAB = {"chat_id": None, "message_id": None}


def calculate_dynamic_turbo_workers() -> Tuple[int, str]:
    """Dynamically computes the highest optimal safe worker concurrency for Turbo mode based on system hardware."""
    try:
        mem = psutil.virtual_memory()
        avail_gb = mem.available / (1024 ** 3)
        total_gb = mem.total / (1024 ** 3)
        cpu_cores = psutil.cpu_count(logical=True) or 4

        # Headless Chromium instances use ~350-450MB RSS
        if avail_gb >= 8.0 and cpu_cores >= 8:
            workers = min(6, cpu_cores - 2)
        elif avail_gb >= 4.5 and cpu_cores >= 6:
            workers = 5
        elif avail_gb >= 3.0 and cpu_cores >= 4:
            workers = 4
        elif avail_gb >= 1.8:
            workers = 3
        else:
            workers = 2

        desc = f"{workers} workers auto-tuned ({avail_gb:.1f}GB free of {total_gb:.1f}GB RAM, {cpu_cores} cores)"
        return workers, desc
    except Exception:
        return 4, "4 workers (standard)"


def load_pinned_status_info() -> dict:
    """Loads saved pinned status message ID and chat ID."""
    if PINNED_STATUS_FILE.exists():
        try:
            return json.loads(PINNED_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_pinned_status_info(chat_id: int, message_id: int):
    """Persists pinned status message ID so it can be edited live."""
    try:
        PINNED_STATUS_FILE.write_text(json.dumps({"chat_id": chat_id, "message_id": message_id}), encoding="utf-8")
    except Exception as e:
        print(f"[Pinned Status Save Error] {e}", flush=True)


async def ensure_pinned_live_status(context: ContextTypes.DEFAULT_TYPE, chat_id: int = None, force_repin: bool = False, header: str = None) -> int:
    """Maintains a persistent, pinned live status view at the top of the chat banner."""
    target_chat = chat_id or AUTHORIZED_USER_ID
    if not target_chat:
        return 0

    info = load_pinned_status_info()
    saved_msg_id = info.get("message_id")
    saved_chat_id = info.get("chat_id")

    m = get_realtime_metrics()
    panel_header = header or "📌 <b>Job Deck Live Control Panel (Pinned)</b>"
    text = format_status_message(header=panel_header, metrics=m)
    kb = get_smart_keyboard(m)

    # If already pinned and not force_repin, attempt silent in-place update
    if saved_msg_id and saved_chat_id == target_chat and not force_repin:
        try:
            await context.bot.edit_message_text(
                chat_id=target_chat,
                message_id=saved_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return saved_msg_id
        except Exception as e:
            err_str = str(e).lower()
            if "message is not modified" in err_str:
                return saved_msg_id
            # Message was deleted or unreachable, fall through to post new and pin

    # Otherwise post a fresh pinned control panel
    try:
        sent_msg = await context.bot.send_message(
            chat_id=target_chat,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.pin_chat_message(
                chat_id=target_chat,
                message_id=sent_msg.message_id,
                disable_notification=True
            )
        except Exception as pin_err:
            print(f"[Pin Chat Message Warning] {pin_err}", flush=True)

        save_pinned_status_info(target_chat, sent_msg.message_id)
        return sent_msg.message_id
    except Exception as e:
        print(f"[Ensure Pinned Status Error] {e}", flush=True)
        return 0


def get_realtime_metrics():
    """Calculates comprehensive, ultra-accurate metrics from live ledgers and processes."""
    csv_path = candidate.APPLICATIONS

    total_applied = 0
    today_applied = 0
    today_str = date.today().isoformat()
    recent = []
    companies = {}
    roles_category = {
        "Forward Deployed (FDE)": 0,
        "AI & Automation": 0,
        "Product & Delivery": 0,
        "Data & Analytics": 0,
        "FinTech & Strategy": 0,
        "Security & Infra": 0,
    }

    rows = []
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            rows = list(csv.DictReader(f))
            total_applied = len(rows)
            for r in rows:
                if r.get("Date Applied") == today_str:
                    today_applied += 1
                c = (r.get("Company") or "Unknown").strip()
                if c:
                    companies[c] = companies.get(c, 0) + 1

                role_l = (r.get("Role") or "").lower()
                if any(k in role_l for k in ("forward deploy", "deployed", "fde", "deployment strategist", "solutions engineer", "field engineer", "sales engineer", "implementation")):
                    roles_category["Forward Deployed (FDE)"] += 1
                elif any(k in role_l for k in ("ai", "agent", "llm", "automation", "machine learning", "genai")):
                    roles_category["AI & Automation"] += 1
                elif any(k in role_l for k in ("product", "program manager", "project manager", "tpm", "apm", "delivery")):
                    roles_category["Product & Delivery"] += 1
                elif any(k in role_l for k in ("data", "analytics", "business intelligence", "quant", "research")):
                    roles_category["Data & Analytics"] += 1
                elif any(k in role_l for k in ("finance", "strategy", "operations", "consulting", "trading", "analyst")):
                    roles_category["FinTech & Strategy"] += 1
                else:
                    roles_category["Security & Infra"] += 1
            recent = rows[-5:]

    # Queue Metrics (prefer queue_ranked.txt -> queue.txt -> queue_cyber_iam.txt)
    queue_count = 0
    unapplied_count = 0
    q_path = ROOT / "queue_ranked.txt"
    if not q_path.exists():
        q_path = ROOT / "queue.txt" if (ROOT / "queue.txt").exists() else (ROOT / "queue_cyber_iam.txt")
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            qlines = [l.strip() for l in f if l.strip() and not l.startswith("#") and "http" in l]
            queue_count = len(qlines)
            if rows:
                applied_urls = {r.get("Job URL", "").strip().rstrip("/") for r in rows if r.get("Job URL")}
                unapplied_count = sum(
                    1 for l in qlines if not any(p.rstrip("/") in applied_urls for p in l.split() if p.startswith("http"))
                )
            else:
                unapplied_count = queue_count

    # Runner & Active Process Inspection
    curr_pid = os.getpid()
    active_worker_pids = []
    total_mem_mb = 0
    try:
        for p in psutil.process_iter(["pid", "cmdline"]):  # memory only for matches: all ~600 took 2s on the event loop
            cmd = " ".join(p.info["cmdline"] or [])
            # python running the scripts, not anything that mentions them ("tail -f batch_apply.log" read as a live runner)
            if "python" in cmd.lower() and re.search(r"batch_apply_parallel\.py|fill\.py", cmd) and p.info["pid"] != curr_pid:
                active_worker_pids.append(p.info["pid"])
                try:
                    total_mem_mb += p.memory_info().rss / (1024 * 1024)
                except psutil.Error:
                    pass
    except Exception:
        pass

    is_running = len(active_worker_pids) > 0

    # Current Target
    current_target = None
    today_records_dir = ROOT / "records" / today_str
    if today_records_dir.exists():
        rfiles = glob.glob(str(today_records_dir / "*.json"))
        if rfiles:
            latest_file = max(rfiles, key=os.path.getmtime)
            try:
                with open(latest_file, "r", encoding="utf-8") as rf:
                    d = json.load(rf)
                    current_target = f"{d.get('company', '')} — {d.get('role', '')[:45]}"
            except Exception:
                pass

    # Pending Questions Check
    pending_questions = telegram_query_engine.load_pending_questions()

    # Inbox Actions Check
    inbox_actions = []
    inbox_path = ROOT / "agents" / "inbox_actions.md"
    if inbox_path.exists():
        try:
            with open(inbox_path, "r", encoding="utf-8", errors="ignore") as f:
                inbox_actions = [l.strip() for l in f if l.strip().startswith("-") or l.strip().startswith("*")]
        except Exception:
            pass

    # System RAM & Adaptive Concurrency
    mem = psutil.virtual_memory()
    avail_gb = mem.available / (1024 ** 3)
    mem_pct = mem.percent
    try:
        import batch_apply_parallel
        optimal_workers = batch_apply_parallel.calculate_optimal_workers()
    except Exception:
        optimal_workers = 3

    return {
        "total_applied": total_applied,
        "today_applied": today_applied,
        "recent": recent,
        "companies": companies,
        "roles_category": roles_category,
        "queue_count": queue_count,
        "unapplied_count": unapplied_count,
        "is_running": is_running,
        "worker_count": len(active_worker_pids),
        "total_mem_mb": int(total_mem_mb),
        "current_target": current_target,
        "pending_questions": pending_questions,
        "inbox_actions": inbox_actions,
        "avail_gb": avail_gb,
        "mem_pct": mem_pct,
        "optimal_workers": optimal_workers,
    }


def get_smart_keyboard(metrics=None):
    """Dynamically generates real-time touch buttons tailored to the user's active workflow state."""
    if metrics is None:
        metrics = get_realtime_metrics()

    B = InlineKeyboardButton
    pending_q = metrics.get("pending_questions") or []
    run_btn = B("⏸ Pause", callback_data="btn_stop") if metrics.get("is_running") else B("▶ Run", callback_data="btn_run")
    keyboard = [[run_btn, B("🔄 Refresh", callback_data="btn_status")],
                [B("📋 Recent", callback_data="btn_recent"), B("📈 Stats", callback_data="btn_stats")]]
    if pending_q:
        keyboard.append([B(f"⚠️ Answer questions ({len(pending_q)})", callback_data="btn_questions")])
    keyboard.append([B("⚙️ Settings", callback_data="btn_settings"), B("☰ More", callback_data="btn_more")])
    return InlineKeyboardMarkup(keyboard)


# Owner's bot settings (candidate home, not the repo). workers 0 = auto-size to free RAM.
SETTINGS_FILE = candidate.DATA / "bot_settings.json"
DEFAULT_SETTINGS = {"workers": 3, "delay": 2.0, "autopilot": True, "desired": "running"}
PACE_NAMES = {4.0: "🐢 Careful", 2.0: "Normal", 1.0: "⚡ Fast"}


def load_settings() -> dict:
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULT_SETTINGS)


_SETTINGS_LOCK = threading.Lock()  # taps run concurrently; read-modify-write must not lose a change


def save_settings(**changes) -> dict:
    if "delay" in changes and float(changes["delay"]) not in PACE_NAMES:  # only the offered paces (no 0, negative, nan)
        changes.pop("delay")
    if "workers" in changes and not 0 <= int(changes["workers"]) <= 8:
        changes.pop("workers")
    with _SETTINGS_LOCK:
        s = {**load_settings(), **changes}
        try:
            SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Settings Save Error] {e}", flush=True)
    return s


def settings_summary(s=None) -> str:
    s = s or load_settings()
    w = s["workers"] or "auto"
    return f"{w} workers · {PACE_NAMES.get(float(s['delay']), str(s['delay']) + 's')} pace · autopilot {'on' if s['autopilot'] else 'off'}"


def get_settings_view():
    s = load_settings()
    B = InlineKeyboardButton
    mark = lambda on, label: ("✅ " if on else "") + label
    text = ("⚙️ <b>Settings</b>\n\n"
            f"<b>Workers:</b> {s['workers'] or 'auto (sized to free RAM)'} — browsers applying at once\n"
            f"<b>Pace:</b> {PACE_NAMES.get(float(s['delay']), s['delay'])} — wait between page steps\n"
            f"<b>Autopilot:</b> {'on — restarts the runner if it stops and refills the queue' if s['autopilot'] else 'off — runs only when you tap Run'}\n\n"
            "<i>Changes apply the next time the runner starts.</i>")
    kb = InlineKeyboardMarkup([
        [B(mark(s["workers"] == n, str(n) if n else "Auto"), callback_data=f"set|workers|{n}") for n in (1, 2, 3, 4, 0)],
        [B(mark(float(s["delay"]) == d, name), callback_data=f"set|delay|{d}") for d, name in PACE_NAMES.items()],
        [B(f"🤖 Autopilot: {'ON' if s['autopilot'] else 'OFF'}", callback_data=f"set|autopilot|{'off' if s['autopilot'] else 'on'}")],
        [B("⬅ Back", callback_data="btn_status")],
    ])
    return text, kb


def get_more_view():
    B = InlineKeyboardButton
    text = "☰ <b>More</b>\n<i>Each button sends its result as a new message.</i>"
    kb = InlineKeyboardMarkup([
        [B("🎯 Apply to a company", callback_data="btn_target"), B("➕ Refill queue", callback_data="btn_replenish")],
        [B("📸 Browser screen", callback_data="btn_view"), B("📄 Resume", callback_data="btn_resume")],
        [B("📬 Recruiter decisions", callback_data="btn_decisions"), B("🔍 Scan inbox", callback_data="btn_scan_inbox")],
        [B("🧠 Assessments", callback_data="btn_assessments"), B("🎙️ Mock interview", callback_data="btn_interview")],
        [B("🧹 Clean chat", callback_data="btn_clean_questions"), B("🖥️ Free up PC", callback_data="btn_optimize_pc")],
        [B("⬅ Back", callback_data="btn_status")],
    ])
    return text, kb


def format_status_message(header="📊 <b>Job Deck Live Control Panel</b>", metrics=None):
    if metrics is None:
        metrics = get_realtime_metrics()

    total = metrics["total_applied"]
    today = metrics["today_applied"]
    target_goal = 3000
    pct = (total / target_goal) * 100 if target_goal else 0
    filled = min(10, int(pct // 10))
    bar = "█" * filled + "░" * (10 - filled)

    is_running = metrics["is_running"]
    workers = metrics["worker_count"]
    mem = metrics["total_mem_mb"]
    s = load_settings()
    if is_running:
        runner_str = f"🟢 <b>Running</b> ({workers} processes, {mem}MB)"
    elif RUNNER_SUPERVISOR_STATE.get("desired") == "running" and s["autopilot"]:
        runner_str = "🟡 <b>Restarting…</b> (autopilot)"
    else:
        runner_str = "⏸ <b>Paused</b> — tap ▶ Run"

    now_str = datetime.now().strftime("%I:%M %p")
    lines = [
        f"{header} <i>({now_str})</i>",
        "",
        f"<b>Applied:</b> {total} total · +{today} today  <code>[{bar}]</code> {pct:.0f}% of {target_goal}",
        f"<b>Runner:</b> {runner_str}",
    ]
    if metrics["current_target"] and is_running:
        lines.append(f"<b>Now:</b> <i>{h(metrics['current_target'])}</i>")
    lines.append(f"<b>Queue:</b> {metrics['unapplied_count']} jobs left · <b>Settings:</b> {settings_summary(s)}")
    if metrics["pending_questions"]:
        lines.append(f"⚠️ <b>{len(metrics['pending_questions'])} question(s)</b> need your answer")
    if metrics["inbox_actions"]:
        lines.append(f"📬 <b>{len(metrics['inbox_actions'])} recruiter item(s)</b> in your inbox")
    return "\n".join(lines)


def get_onboarding_step_message(step: int = 1):
    """Generates an interactive, step-by-step onboarding walkthrough for new users."""
    step = max(1, min(8, step))

    if step == 1:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 1 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👋 <b>Welcome to Job Deck Autonomous Headquarters!</b>\n\n"
            "Job Deck is a high-velocity, fully autonomous agentic application pipeline that scouts, "
            "tailors resumes, solves screening questions, and submits job applications 24/7.\n\n"
            "🎯 <b>Strict Candidate Guardrails:</b>\n"
            "• Targets <b>Cybersecurity, IAM, Cloud Security, IT Support, Systems Administration, and Infrastructure</b>.\n"
            "• <b>Zero Software Engineering / Coding roles</b> are ever submitted.\n"
            "• Built with zero human babysitting required.\n\n"
            "<i>Tap below to walk through your system setup and candidate parameters!</i>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next: Automation Engine ➡️", callback_data="onboard:step:2")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 2:
        py_ver = sys.version.split()[0]
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 2 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ <b>Environment & Headless Browser Automation</b>\n\n"
            f"• <b>Python Runtime:</b> <code>v{py_ver}</code> (3.10+ Verified ✅)\n"
            "• <b>Playwright Chromium:</b> Multi-Page Headless Browser Engine Active ✅\n"
            "• <b>Supported Job Portals:</b> Workday, Greenhouse, Lever, Ashby, BambooHR, SmartRecruiters, Jobvite\n"
            "• <b>Form Automation:</b> Solves text fields, complex multi-selects, address autocompletes, and file uploads.\n\n"
            "💡 <b>Full Resilience:</b>\n"
            "If a portal requires human verification or CAPTCHA, Job Deck cleanly isolates that job, captures a diagnostic screenshot, and continues applying to the next queued position seamlessly."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:1"),
             InlineKeyboardButton("Next: Candidate Shield ➡️", callback_data="onboard:step:3")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 3:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 3 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👤 <b>Candidate Identity & Rule-Based Shield</b>\n\n"
            f"• <b>Candidate:</b> {h(candidate.fact('FULL_NAME') or 'not set (CANDIDATE_FULL_NAME)')}\n"
            f"• <b>Education:</b> {h(candidate.fact('DEGREE_EXACT') or candidate.fact('DEGREE') or 'not set')}, "
            f"{h(candidate.fact('UNIVERSITY') or 'not set')} ({h(candidate.fact('EXPECTED_GRAD_DATE') or 'grad date not set')})\n"
            f"• <b>GPA:</b> {h(candidate.fact('GPA') or 'not set')}\n"
            "• <b>Target Specializations:</b> Cybersecurity Analyst, IAM Specialist, SOC Analyst, Cloud Security, IT Support, SysAdmin\n\n"
            "🔒 <b>Anti-Hallucination Policy:</b>\n"
            "All screening responses are locked to factual entries in <code>profile.json</code>. The agent will never "
            "invent credentials, phone numbers, or graduation dates."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:2"),
             InlineKeyboardButton("Next: Resume Tailoring ➡️", callback_data="onboard:step:4")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 4:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 4 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📄 <b>Master Resume & Dynamic Tailoring Engine</b>\n\n"
            "• <b>Master File:</b> <code>resumes/Candidate_Resume.pdf</code>\n"
            "• <b>ATS Keyword Tailoring:</b> Uses ReportLab to dynamically rank and permute bullet points based on the target job description.\n"
            "• <b>No Inventions:</b> Only permutations of genuine verified experiences are permitted.\n"
            "• <b>Instant Mobile Preview:</b> Tap <code>[📄 Quick Resume]</code> on the dashboard anytime to inspect the latest tailored resume as a photo preview without downloading!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:3"),
             InlineKeyboardButton("Next: Recruiter Radar ➡️", callback_data="onboard:step:5")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 5:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 5 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📬 <b>Recruiter Radar & 1-Tap Gmail Direct Links</b>\n\n"
            "• <b>Real-Time Inbox Scanner:</b> Continuously monitors your inbox for confirmation emails, interview invitations, coding/security assessments, and offers.\n"
            "• <b>Decision Stages:</b> Tracks timestamps and interview deadlines.\n"
            "• <b>1-Tap Direct Links:</b> Every advancement alert includes a direct one-tap link to open the email right inside the Gmail web app.\n"
            "• <b>Outreach Drafter:</b> Generates concise LinkedIn connection messages tailored to hiring managers (saved as drafts, never sent automatically)."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:4"),
             InlineKeyboardButton("Next: iMessage Pager ➡️", callback_data="onboard:step:6")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 6:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 6 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📱 <b>Apple iMessage Dual-Channel Emergency Pager</b>\n\n"
            "Job Deck bridges directly to Apple iMessage on the phone set in <code>IMESSAGE_TARGET_HANDLE</code>.\n\n"
            "✨ <b>How it works:</b>\n"
            "• <b>Critical Pager:</b> Interview requests, assessment deadlines, and job offers ping your iPhone instantly via native blue bubbles.\n"
            "• <b>2-Way Text Commands:</b> Text your Job Deck bridge anytime from iMessage:\n"
            "  - <code>status</code> — Live submission counts & worker state\n"
            "  - <code>run</code> / <code>turbo</code> — Launch background workers\n"
            "  - <code>stop</code> — Pause all workers\n"
            "  - <code>prep &lt;Company&gt;</code> — Instant Interview Battlecard\n"
            "  - <code>boost</code> — Optimize PC RAM\n"
            "• <b>Test Command:</b> Type <code>/imessage</code> in Telegram to trigger a live test ping to your iPhone!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:5"),
             InlineKeyboardButton("Next: PC Optimizer ➡️", callback_data="onboard:step:7")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 7:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 7 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧹 <b>Zero-Lag PC Optimizer & RAM Trimmer</b>\n\n"
            "• <b>Below-Normal CPU Priority:</b> All headless browser instances run with below-normal scheduling so Windows prioritizes your foreground applications 100%.\n"
            "• <b>5-Minute Memory Trimmer:</b> Runs silently every 5 minutes to sweep unused working sets back to the OS.\n"
            "• <b>Zombie Cleaner:</b> Automatically cleans up orphaned browser processes.\n"
            "• <b>Zero Stutter:</b> You can game, code, or watch 4K video while Job Deck applies in the background with zero lag!\n\n"
            "Tap <code>[🧹 Boost PC]</code> or type <code>/optimize</code> anytime to manually reclaim RAM."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:6"),
             InlineKeyboardButton("Next: Touch Controls ➡️", callback_data="onboard:step:8")],
            [InlineKeyboardButton("🏠 Exit to Control Panel", callback_data="btn_status")]
        ])

    elif step == 8:
        text = (
            "🧭 <b>Job Deck Setup Wizard (Step 8 of 8)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎮 <b>Cockpit Controls, Dynamic HUD & Ready to Launch!</b>\n\n"
            "You are all set! Here is how to control Job Deck like a pro:\n\n"
            "• <b>Smart Touch Buttons:</b> Run workers, trigger Turbo velocity, view recent submissions, or boost PC performance.\n"
            "• <b>Dynamic Live HUD:</b> Tap <code>[📡 Live Dynamic HUD]</code> to start a single, live-updating 4-second ticker with zero chat bloat.\n"
            "• <b>Voice Memo Engine:</b> Speak commands hands-free directly into Telegram!\n"
            "• <b>Clean Chat:</b> Tap <code>[🧹 Clean Chat]</code> or send <code>/clean</code> anytime to wipe past messages while keeping your pinned dashboard intact.\n\n"
            "Ready to conquer your job hunt?"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Prev", callback_data="onboard:step:7"),
             InlineKeyboardButton("🚀 Launch 3 Workers Now!", callback_data="onboard:launch")],
            [InlineKeyboardButton("🏠 Back to Control Panel", callback_data="btn_status")]
        ])

    return text, kb

RUNNER_SUPERVISOR_STATE = {
    "desired": load_settings()["desired"],  # a Pause survives a bot restart
    "workers": 3,
    "delay": 2.0,
    "queue": "queue_ranked.txt",
    "last_relaunch": 0.0,
    "auto_restarts": 0,
}

# Mid-session isolated worker state (uses worker IDs 91..99 so profiles .browser-profile-w91..w99 never collide with main w1..w6)
ACTIVE_TARGETED_JOBS = []
NEXT_TARGET_WORKER_ID = 91

COMPANY_ALIASES = {
    "visa": ["visa"],
    "goldman": ["goldman", "goldmansachs", "goldman sachs"],
    "goldman sachs": ["goldman", "goldmansachs", "goldman sachs"],
    "palantir": ["palantir"],
    "scale": ["scaleai", "scale ai", "scale"],
    "scale ai": ["scaleai", "scale ai", "scale"],
    "sierra": ["sierra"],
    "coinbase": ["coinbase"],
    "cloudflare": ["cloudflare"],
    "databricks": ["databricks"],
    "stripe": ["stripe"],
    "ramp": ["ramp"],
    "amex": ["americanexpress", "american express", "amex"],
    "american express": ["americanexpress", "american express", "amex"],
    "jpmorgan": ["jpmorgan", "jpmorganchase", "jp morgan", "chase"],
    "blackrock": ["blackrock"],
    "deloitte": ["deloitte"],
    "accenture": ["accenture"],
    "mckinsey": ["mckinsey"],
    "bcg": ["bcg", "boston consulting"],
    "bain": ["bain"],
}


def parse_targeted_apply_intent(text: str):
    """
    Extracts a targeted company / job query from natural-language Telegram bar messages such as:
      - 'Apply to this job with Visa'
      - 'Apply to this job with Goldman'
      - 'Apply to this job at Palantir'
      - 'Apply to Visa' / 'Apply with Goldman Sachs'
      - 'Run job for Visa' / 'Customize job with Goldman'
      - '/apply Visa' / '/target Goldman' / 'target: Visa'
    Returns the cleaned target query string (e.g. 'Visa', 'Goldman Sachs'), or None if the message
    is a general command (like bare '/apply' or 'start applying').
    """
    raw = (text or "").strip()
    if not raw:
        return None
    t_lower = raw.lower()

    # Do not intercept generic runner start phrases
    if t_lower in (
        "apply", "/apply", "run", "/run", "start", "/start",
        "start applying", "start runner", "start workers", "launch workers",
        "keep applying", "run workers", "begin", "launch",
        "start job deck", "start my job deck", "run job deck", "/deck", "deck",
    ):
        return None

    patterns = [
        r"^(?:/apply|/target|target\s*:)\s+(.+)$",
        r"^(?:please\s+|can\s+you\s+|let'?s\s+)?(?:apply|run|launch|submit|customize)\s+(?:to\s+|for\s+)?(?:this\s+|the\s+|a\s+)?(?:job|role|internship|position|application)s?\s+(?:with|at|for|from|to|in)\s+(.+)$",
        r"^(?:please\s+|can\s+you\s+|let'?s\s+)?(?:apply|run|launch)\s+(?:with|to|for|at)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, raw, flags=re.I)
        if m:
            candidate_q = m.group(1).strip().strip(".!?,;\"'")
            candidate_q = re.sub(
                r"\b(?:specifically|mid[\s\-]*session|right\s+now|now|please|immediately|while\s+also\s+running.*|and\s+also\s+run.*)\b",
                "",
                candidate_q,
                flags=re.I,
            ).strip().strip(".!?,;\"'")
            if candidate_q.lower() not in ("", "workers", "runner", "all", "queue", "job deck", "my job deck", "jobs"):
                return candidate_q
    return None


def resolve_targeted_company_jobs(query_str: str, include_applied: bool = False):
    """
    Finds matching job postings across queue_ranked.txt, queue.txt, queue_phase2.txt,
    and # MANUAL (protected company) entries, or builds a direct job entry if a URL is supplied.
    Ranks FDE (10.0), AI & Automation (10.0), Product (9.0), and Data & Analytics (9.0) first.
    """
    import results_engine as RE

    q_clean = (query_str or "").strip()
    if not q_clean:
        return []

    # Case 1: Direct URL included in query
    m_url = re.search(r"(https?://\S+)", q_clean)
    if m_url:
        url = m_url.group(1).strip()
        prefix = (q_clean[:m_url.start()] + " " + q_clean[m_url.end():]).strip()
        m_gh = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/&?]+)(?:/jobs/|.*[&?]token=)(\d+)", url)
        if m_gh:
            board, token = m_gh.groups()
            url = f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={token}"
            comp = prefix.split()[0] if prefix else board.capitalize()
        else:
            comp = prefix.split()[0] if prefix else "TargetEmployer"
        role = " ".join(prefix.split()[1:]) if len(prefix.split()) > 1 else "Targeted Priority Role"
        score, cat, _ = RE.score_job(comp, role, url)
        return [{
            "company": comp,
            "role": role,
            "url": url,
            "score": max(score, 9.5),
            "category": cat if cat != "other" else "targeted",
            "applied": False,
        }]

    # Case 2: Company + optional role filter
    q_low = q_clean.lower()
    matched_alias_key = None
    company_tokens = []
    role_tokens = []

    for alias_key in sorted(COMPANY_ALIASES.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias_key)}\b", q_low):
            matched_alias_key = alias_key
            company_tokens = COMPANY_ALIASES[alias_key]
            leftover = re.sub(rf"\b{re.escape(alias_key)}\b", " ", q_low)
            role_tokens = [w for w in re.findall(r"[a-z0-9]+", leftover) if w not in ("with", "at", "for", "to", "job", "role", "intern", "internship", "the", "this", "sachs")]
            break

    if not company_tokens:
        words = [w for w in re.findall(r"[a-zA-Z0-9]+", q_low) if w not in ("with", "at", "for", "to", "job", "role", "the", "this")]
        if not words:
            return []
        company_tokens = [words[0], "".join(words[:2])]
        role_tokens = [w for w in words[1:] if w not in ("intern", "internship")]

    applied_keys = RE.already_applied_keys()
    seen_urls = set()
    candidates = []

    queue_files = [
        ROOT / "queue_ranked.txt",
        ROOT / "queue.txt",
        ROOT / "queue_phase2.txt",
        ROOT / "queue_cyber_iam.txt",
    ]

    for qf in queue_files:
        if not qf.exists():
            continue
        for raw_line in qf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or "http" not in line:
                continue
            # Also allow # MANUAL (protected company) lines so explicit commands like 'Apply to this job with Goldman' work!
            if line.startswith("#"):
                if "MANUAL" in line and "http" in line:
                    line = re.sub(r"^#\s*MANUAL[^:]*:\s*", "", line).strip()
                else:
                    continue

            m = re.search(r"(https?://\S+)", line)
            if not m:
                continue
            url = m.group(1).strip()
            prefix = line[:m.start()].strip()
            parts = prefix.split(" ", 1)
            comp = parts[0].strip() if parts else ""
            role = parts[1].strip() if len(parts) > 1 else comp
            after = line[m.end():].strip()
            resume_hint = None
            if after:
                m_res = re.search(r"(?:resume=)?(\S+\.pdf)", after)
                if m_res:
                    resume_hint = m_res.group(1)

            comp_norm = re.sub(r"[^a-z0-9]", "", comp.lower())
            line_low = f"{comp} {role}".lower()
            if not any(
                re.sub(r"[^a-z0-9]", "", tok) in comp_norm or re.search(rf"\b{re.escape(tok)}\b", line_low)
                for tok in company_tokens
            ):
                continue

            u_key = url.rstrip("/")
            if u_key in seen_urls:
                continue
            seen_urls.add(u_key)

            score, cat, _ = RE.score_job(comp, role, url)
            is_app = RE.job_key(comp, role, url) in applied_keys
            role_kw_hits = sum(1 for rt in role_tokens if rt in role.lower())
            if matched_alias_key == "sierra" and "sierranevada" in comp_norm and "nevada" not in q_low:
                score -= 3.0

            candidates.append({
                "company": comp,
                "role": role,
                "url": url,
                "score": round(score + (2.5 * role_kw_hits), 1),
                "base_score": score,
                "category": cat,
                "applied": is_app,
                "resume": resume_hint,
                "ats_prio": RE.ats_priority(url),
            })

    # Also check live job_sources feed if no candidates found yet
    if not candidates:
        try:
            import agents.job_sources as js
            for j in js.fetch(max_age_days=60):
                comp = (j.get("company") or "").strip()
                role = (j.get("role") or j.get("title") or "").strip()
                url = (j.get("url") or "").strip()
                if not url:
                    continue
                comp_norm = re.sub(r"[^a-z0-9]", "", comp.lower())
                if any(re.sub(r"[^a-z0-9]", "", tok) in comp_norm for tok in company_tokens):
                    score, cat, _ = RE.score_job(comp, role, url)
                    candidates.append({
                        "company": comp,
                        "role": role,
                        "url": url,
                        "score": score,
                        "base_score": score,
                        "category": cat,
                        "applied": RE.job_key(comp, role, url) in applied_keys,
                        "resume": None,
                        "ats_prio": RE.ats_priority(url),
                    })
        except Exception:
            pass

    if not include_applied:  # never fall back to applied jobs when nothing new matches
        candidates = [c for c in candidates if not c["applied"]]

    # Rank: highest score (including role keyword boost), then FDE/AI/Product/Data track preference, then easiest ATS
    cat_rank = {"fde": 0, "ai_automation": 0, "product": 1, "analyst_data": 1, "business_systems": 2, "consulting_strategy": 2, "finance_tech": 2}
    candidates.sort(key=lambda c: (c["applied"], -c["score"], cat_rank.get(c["category"], 5), c["ats_prio"]))
    return candidates


def _in_flight_keys() -> set:
    import results_engine as RE
    return {RE.job_key(j["company"], j["role"], j["url"]) for j in ACTIVE_TARGETED_JOBS
            if j.get("pid") and psutil.pid_exists(j["pid"])}


def eligible_targets(candidates: list) -> list:
    """The batch runner's own gates (batch_apply_parallel.py): never applied, not protected, fit >= min_fit_score,
    and not already being filled by an earlier tap. A Telegram tap must not reach a job the runner would refuse."""
    import results_engine as RE
    min_fit = RE.strategy().get("min_fit_score", 5.0)
    busy, seen, out = _in_flight_keys(), set(), []
    for m in candidates:
        key = RE.job_key(m["company"], m["role"], m["url"])
        if (m.get("applied") or key in busy or key in seen or RE.is_protected(m["company"])
                or RE.score_job(m["company"], m["role"], m["url"])[0] < min_fit):
            continue
        seen.add(key)
        out.append(m)
    return out


def launch_mid_session_targeted_job(target_query: str, ensure_runner_active: bool = True, max_to_launch: int = 1, role_index: int = 0, dry_run: bool = False) -> dict:
    """
    Launches a targeted application for a specific company or job mid-session using an isolated
    worker profile (.browser-profile-w91..w99) so it NEVER interrupts or conflicts with the active
    batch runner, while also ensuring the main Job Deck runner is active in parallel.
    """
    global NEXT_TARGET_WORKER_ID, ACTIVE_TARGETED_JOBS
    import results_engine as RE

    matches = eligible_targets(resolve_targeted_company_jobs(target_query, include_applied=False))
    if not matches:
        return {
            "ok": False,
            "query": target_query,
            "error": f"No eligible internship postings for '{target_query}' (already applied, in progress, protected, below your fit score, or not an internship).",
            "launched": [],
            "alternates": [],
        }

    # Select slice to launch
    if role_index > 0 and role_index < len(matches):
        to_launch = [matches[role_index]]
        alternates = [m for idx, m in enumerate(matches) if idx != role_index][:5]
    else:
        to_launch = matches[:max(1, max_to_launch)]
        alternates = matches[len(to_launch):len(to_launch) + 5]

    m_before = get_realtime_metrics()
    main_runner_was_active = bool(m_before.get("is_running"))
    main_runner_started_now = False

    launched_items = []
    today_str = date.today().isoformat()
    log_dir = ROOT / "records" / today_str
    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)

    for job in to_launch:
        comp = job["company"]
        role = job["role"]
        url = job["url"]
        from agents.role_filter import reject_reason
        _why = reject_reason(role)
        if _why:
            print(f"[Targeted Apply] Skipping {comp}: {_why}", flush=True)
            continue

        # Canonicalize Greenhouse embed URLs
        m_gh = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/&?]+)(?:/jobs/|.*[&?]token=)(\d+)", url)
        if m_gh:
            board, token = m_gh.groups()
            url = f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={token}"

        # Tailor resume for this specific target company & role
        resume_to_use = job.get("resume") or "resumes/Candidate_Resume.pdf"
        if not (ROOT / resume_to_use).exists() and (ROOT.parent / resume_to_use).exists():
            resume_to_use = str(ROOT.parent / resume_to_use)
        elif not Path(resume_to_use).is_absolute():
            resume_to_use = "resumes/Candidate_Resume.pdf" if (ROOT / "resumes" / "Candidate_Resume.pdf").exists() else "resumes/master_resume.pdf"
        try:
            from agents import resume_tailor
            tailored = resume_tailor.tailor(comp, role, url, resume_to_use)
            if tailored:
                resume_to_use = str(tailored)
        except Exception as e:
            print(f"[Targeted Apply] Resume tailor fallback ({e})", flush=True)

        wid = NEXT_TARGET_WORKER_ID
        NEXT_TARGET_WORKER_ID = 91 if NEXT_TARGET_WORKER_ID >= 99 else (NEXT_TARGET_WORKER_ID + 1)

        cmd = [
            str(ROOT.parent / ".venv" / "Scripts" / "python.exe") if (ROOT.parent / ".venv" / "Scripts" / "python.exe").exists() else sys.executable,
            "-u",
            str(ROOT / "fill.py"),
            url,
            "--worker-id", str(wid),
            "--headless",
            "--block-assets",
            "--company", comp,
            "--role", role,
            "--resume", str(resume_to_use),
        ]

        env = {**os.environ, "AF_DEADLINE": "260"}
        try:
            from agents import cover_letter
            cover = cover_letter.build(comp, role, url)
            if cover:
                env["AF_COVER"] = cover
        except Exception:
            pass

        slug = RE._slug(comp, role)
        log_path = log_dir / f"targeted_{slug}.log"
        pid = None
        if not dry_run:
            log_f = open(log_path, "a", encoding="utf-8", errors="ignore")
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT, creationflags=flags)
            pid = proc.pid

        item_info = {
            "company": comp,
            "role": role,
            "url": url,
            "score": job.get("base_score", job.get("score", 9.0)),
            "category": job.get("category", "targeted"),
            "resume": str(resume_to_use),
            "worker_id": wid,
            "pid": pid,
            "log_path": str(log_path),
            "launched_at": datetime.now().strftime("%I:%M:%S %p"),
        }
        launched_items.append(item_info)
        ACTIVE_TARGETED_JOBS.append(item_info)
        if len(ACTIVE_TARGETED_JOBS) > 15:
            ACTIVE_TARGETED_JOBS[:] = ACTIVE_TARGETED_JOBS[-15:]

    # Ensure the main Job Deck parallel queue runner is ALSO running alongside the targeted job
    if ensure_runner_active and not main_runner_was_active and not dry_run:
        launch_runner(workers=3, queue="queue_ranked.txt", user_action=True)
        main_runner_started_now = True

    return {
        "ok": True,
        "query": target_query,
        "launched": launched_items,
        "alternates": alternates,
        "total_matches": len(matches),
        "main_runner_active": main_runner_was_active or main_runner_started_now,
        "main_runner_started_now": main_runner_started_now,
    }


def format_targeted_launch_message(res: dict):
    """Formats a rich Telegram HTML confirmation card and inline buttons for a mid-session targeted job."""
    if not res.get("ok"):
        msg = (
            f"⚠️ <b>No Queued Match Found for '{h(res.get('query'))}'</b>\n\n"
            f"💡 <b>Tip:</b> Drop the direct job URL in the Telegram bar or try:\n"
            f"• <code>Apply to this job with Visa</code>\n"
            f"• <code>Apply to this job with Goldman</code>\n"
            f"• <code>Apply to this job with Palantir</code>\n"
            f"• <code>Apply to this job with Scale AI</code>"
        )
        return msg, get_target_customizer_panel()[1]

    launched = res.get("launched") or []
    first = launched[0]
    alternates = res.get("alternates") or []

    runner_note = (
        "🟢 <b>Main Job Deck Auto-Started in Parallel!</b> (3 background workers + your targeted job)"
        if res.get("main_runner_started_now")
        else "🟢 <b>Main Job Deck Active in Parallel</b> (Zero interruption to ongoing session)"
    )

    lines = [
        f"🎯 <b>Mid-Session Targeted Job Launched!</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for item in launched:
        lines.extend([
            f"🏢 <b>Company:</b> <b>{h(item['company'])}</b>",
            f"💼 <b>Role:</b> {h(item['role'])}",
            f"⭐ <b>Fit Score:</b> <code>{item['score']}/10</code> (Track: <code>{h(item['category'])}</code>)",
            f"📄 <b>Tailored Resume:</b> <code>{h(Path(item['resume']).name)}</code>",
            f"⚙️ <b>Isolated Worker:</b> <code>W{item['worker_id']}</code> (PID: <code>{item.get('pid') or 'sim'}</code>)",
            f"🔗 <a href=\"{h(item['url'])}\">Open Target Job Portal</a>",
            "",
        ])

    lines.append(f"⚡ <b>Session Status:</b> {runner_note}")

    if alternates:
        lines.append(f"\n📋 <b>Other Matching {h(first['company'])} Roles Ready ({len(alternates)} more):</b>")
        for idx, alt in enumerate(alternates[:3], start=1):
            lines.append(f"  {idx}. {h(alt['role'][:55])} (<code>fit {alt.get('base_score', alt['score'])}</code>)")

    kb_rows = []
    q_comp = first["company"]
    if alternates:
        kb_rows.append([
            InlineKeyboardButton(f"🚀 Apply Next {q_comp} Role", callback_data=f"target_idx|{q_comp[:24]}|1"),
            InlineKeyboardButton(f"⚡ Apply Top 3 {q_comp}", callback_data=f"target_all|{q_comp[:24]}"),
        ])
    kb_rows.append([
        InlineKeyboardButton("📸 Live Screen Cam", callback_data="btn_view"),
        InlineKeyboardButton("📄 Quick Resume", callback_data="btn_resume"),
    ])
    kb_rows.append([
        InlineKeyboardButton("🎯 Target Another Company", callback_data="btn_target"),
        InlineKeyboardButton("📊 Live Control Panel", callback_data="btn_status"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)


def get_target_customizer_panel():
    """Returns the interactive Telegram Bar Company Customizer message & 1-tap keyboard."""
    text = (
        "🎯 <b>Telegram Bar — Mid-Session Job Customizer</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Launch a dedicated, isolated browser worker for any specific company <b>mid-session</b> "
        "while your main Job Deck continues running in the background!\n\n"
        "💬 <b>Type directly in the Telegram Bar:</b>\n"
        "• <code>Apply to this job with Visa</code>\n"
        "• <code>Apply to this job with Goldman</code>\n"
        "• <code>Apply to this job with Palantir Forward Deployed</code>\n"
        "• <code>Apply to this job with Scale AI</code>\n"
        "• <code>/apply [Company Name or Job URL]</code>\n\n"
        "👇 <b>Or tap a priority target employer below to launch immediately:</b>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Apply: Visa", callback_data="quick_apply|Visa"),
            InlineKeyboardButton("🏦 Apply: Goldman Sachs", callback_data="quick_apply|Goldman Sachs"),
        ],
        [
            InlineKeyboardButton("🛡️ Apply: Palantir (FDE)", callback_data="quick_apply|Palantir Forward Deployed"),
            InlineKeyboardButton("🤖 Apply: Scale AI (FDE)", callback_data="quick_apply|Scale AI Forward Deployed"),
        ],
        [
            InlineKeyboardButton("⚡ Apply: Sierra (Agent FDE)", callback_data="quick_apply|Sierra"),
            InlineKeyboardButton("🪙 Apply: Coinbase (FDE)", callback_data="quick_apply|Coinbase Forward Deployed"),
        ],
        [
            InlineKeyboardButton("☁️ Apply: Cloudflare (PM)", callback_data="quick_apply|Cloudflare Product"),
            InlineKeyboardButton("📊 Apply: Databricks", callback_data="quick_apply|Databricks"),
        ],
        [
            InlineKeyboardButton("🚀 Start Full Job Deck", callback_data="btn_start_deck"),
            InlineKeyboardButton("⬅️ Back to Control Panel", callback_data="btn_status"),
        ],
    ])
    return text, kb


def launch_full_job_deck(workers: int = 3, dry_run: bool = False) -> dict:
    """
    Starts the complete Job Deck pipeline from anywhere via the Telegram bar:
    1. Immediately launches parallel workers on queue_ranked.txt (prioritizing FDE, AI, Product, Data).
    2. Runs a non-blocking coordinator refresh (inbox scan + triage ranking) in the background.
    """
    q_name = "queue_ranked.txt" if (ROOT / "queue_ranked.txt").exists() else "queue.txt"
    if not dry_run:
        launch_runner(workers=workers, queue=q_name, delay=1.8, user_action=True)
    m = get_realtime_metrics()
    return {
        "ok": True,
        "workers": workers,
        "queue": q_name,
        "unapplied_count": m.get("unapplied_count", 0),
        "total_applied": m.get("total_applied", 0),
    }


def launch_assessment_solver_from_telegram(dry_run: bool = False) -> dict:
    """Triggers the Autonomous Assessment Solver (linkedin_outreach.assessments) from Telegram."""
    repo_root = ROOT.parent.parent
    py_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    if not py_exe.exists():
        py_exe = Path(sys.executable)

    cmd = [
        str(py_exe),
        "-m",
        "linkedin_outreach.assessments",
        "--solve-pending",
        "--headless",
    ]
    pid = None
    if not dry_run:
        log_file = open(ROOT / "assessments_solver.log", "a", encoding="utf-8", errors="ignore")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(cmd, cwd=str(repo_root), stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags)
        pid = proc.pid
    return {"ok": True, "pid": pid, "cmd": " ".join(cmd)}


def launch_runner(workers=None, queue="queue_ranked.txt", delay=2.0, user_action=True):
    global RUNNER_SUPERVISOR_STATE
    if not (ROOT / queue).exists():
        queue = "queue_ranked.txt" if (ROOT / "queue_ranked.txt").exists() else ("queue.txt" if (ROOT / "queue.txt").exists() else "queue_cyber_iam.txt")
    if user_action:
        RUNNER_SUPERVISOR_STATE["desired"] = "running"
        save_settings(desired="running")
        if workers is not None:
            RUNNER_SUPERVISOR_STATE["workers"] = workers
        RUNNER_SUPERVISOR_STATE["delay"] = delay
        RUNNER_SUPERVISOR_STATE["queue"] = queue
        RUNNER_SUPERVISOR_STATE["last_relaunch"] = time_mod.time()

    # Clear stale lock files before launching
    for lock in ROOT.glob(".batch_apply*.lock"):
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass

    # Terminate any existing batch_apply_parallel processes to prevent duplicate concurrency conflicts
    curr_pid = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd_str = " ".join(p.info.get("cmdline") or [])
            if "python" in cmd_str.lower() and "batch_apply_parallel.py" in cmd_str and p.info.get("pid") != curr_pid:
                p.kill()
        except Exception:
            pass
    time_mod.sleep(0.5)

    # Ensure queue has unapplied jobs available; if low, replenish immediately
    m = get_realtime_metrics()
    if m.get("unapplied_count", 0) < 25:
        print("[Runner Launch] Queue low, automatically replenishing with fresh roles...", flush=True)
        replenish_queue_action()

    try:
        import batch_apply_parallel
        opt_workers = batch_apply_parallel.calculate_optimal_workers()
    except Exception:
        opt_workers = 3

    target_w = workers if workers is not None else opt_workers
    py_exe = ROOT.parent / ".venv" / "Scripts" / "python.exe"
    if not py_exe.exists():
        py_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py_exe.exists():
        py_exe = Path(sys.executable)

    cmd = [
        str(py_exe),
        "-u",  # unbuffered: the log showed nothing for minutes, and a killed runner lost its last lines
        str(ROOT / "batch_apply_parallel.py"),
        "--queue", queue,
        "--workers", str(target_w),
        "--adaptive",
        "--continuous",
        "--use-tailored",
        "--resume", "resumes/Candidate_Resume.pdf",
        "--delay", str(delay)
    ]
    log_file = open(ROOT / "batch_apply.log", "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags).pid


def _log_tail(n=6) -> str:
    try:
        return "\n".join((ROOT / "batch_apply.log").read_text(encoding="utf-8", errors="ignore").splitlines()[-n:])
    except Exception:
        return ""


async def start_runner_and_report(workers=None, delay=None, force=False) -> str:
    """Starts the runner off the event loop (it can refill the queue for ~15s), checks it stayed up, says what happened."""
    s = load_settings()
    if not force and get_realtime_metrics()["is_running"]:  # a restart would kill applications mid-form
        RUNNER_SUPERVISOR_STATE["desired"] = "running"
        save_settings(desired="running")
        return "🟢 <b>Already applying.</b> Nothing was restarted. Tap ⏸ Pause first to change workers or pace."
    w = workers if workers is not None else (s["workers"] or None)
    d = delay if delay is not None else float(s["delay"])
    pid = await asyncio.to_thread(launch_runner, w, "queue_ranked.txt", d, True)
    await asyncio.sleep(4)
    if not (pid and psutil.pid_exists(pid)):
        return f"❌ <b>The runner stopped right after starting.</b>\n<pre>{h(_log_tail())}</pre>"
    m = get_realtime_metrics()
    return ("✅ <b>Applying now</b>\n"
            f"• Workers: {w or 'auto (' + str(m.get('optimal_workers', 3)) + ')'} · pace {d:g}s\n"
            f"• Queue: {m['unapplied_count']} jobs left\n"
            f"• Autopilot: {'on — restarts it if it stops' if s['autopilot'] else 'off'}\n"
            "<i>Submitted applications and questions arrive here as they happen.</i>")


async def stop_runner_and_report() -> str:
    stopped = await asyncio.to_thread(halt_runner)
    return f"⏸ <b>Paused.</b> Stopped {stopped} process(es). Nothing restarts until you tap ▶ Run."


def halt_runner():
    global RUNNER_SUPERVISOR_STATE
    RUNNER_SUPERVISOR_STATE["desired"] = "paused"
    save_settings(desired="paused")
    curr_pid = os.getpid()
    stopped = 0
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "python" in cmd.lower() and re.search(r"batch_apply_parallel\.py|fill\.py", cmd):
                if p.info["pid"] != curr_pid:
                    p.kill()
                    stopped += 1
        except Exception:
            pass
    # Clean locks
    for lock in ROOT.glob(".batch_apply*.lock"):
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass
    return stopped


async def runner_watchdog_supervisor_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Autonomous Supervisor Watchdog:
    Ensures the applicator NEVER prematurely goes idle.
    If desired state is 'running' and no worker is active, replenishes queue if low
    and autonomously relaunches the parallel runner until 3,000 target is reached.
    """
    global RUNNER_SUPERVISOR_STATE
    if RUNNER_SUPERVISOR_STATE.get("desired") != "running" or not load_settings()["autopilot"]:
        return

    m = get_realtime_metrics()
    if m.get("total_applied", 0) >= 3000:
        print("[Supervisor Watchdog] 3,000 milestone reached! Pausing continuous runner.", flush=True)
        RUNNER_SUPERVISOR_STATE["desired"] = "paused"
        return

    if m.get("is_running"):
        return

    now = time_mod.time()
    if now - RUNNER_SUPERVISOR_STATE.get("last_relaunch", 0.0) < 15.0:
        return

    RUNNER_SUPERVISOR_STATE["last_relaunch"] = now
    RUNNER_SUPERVISOR_STATE["auto_restarts"] = RUNNER_SUPERVISOR_STATE.get("auto_restarts", 0) + 1
    restart_num = RUNNER_SUPERVISOR_STATE["auto_restarts"]
    print(f"[Supervisor Watchdog] Detected IDLE runner (desired=running). Auto-restarting #{restart_num}...", flush=True)

    # Refill when low, or every 30 min while the runner keeps stopping: the raw unapplied count includes jobs the
    # gates reject, so it never looked low while the eligible supply was empty
    if m.get("unapplied_count", 0) < 25 or now - RUNNER_SUPERVISOR_STATE.get("last_refill", 0.0) > 1800:
        RUNNER_SUPERVISOR_STATE["last_refill"] = now
        try:
            added = await asyncio.to_thread(replenish_queue_action)
            print(f"[Supervisor Watchdog] Auto-replenished +{added} fresh target roles.", flush=True)
        except Exception as e:
            print(f"[Supervisor Watchdog] Auto-replenish error: {e}", flush=True)

    s = load_settings()
    q = RUNNER_SUPERVISOR_STATE.get("queue", "queue_ranked.txt")
    await asyncio.to_thread(launch_runner, s["workers"] or None, q, float(s["delay"]), False)


def replenish_queue_action() -> int:
    """Harvests and replenishes queue_ranked.txt with fresh, high-fit FDE, AI, Product & Data roles."""
    import agents.job_sources as js
    import re
    import results_engine as RE

    kw = re.compile(
        r"forward[\s\-]*deploy|deployed\s+engineer|\bfde\b|deployment\s+strategist|solutions?\s+engineer|field\s+engineer|sales\s+engineer|customer\s+engineer|ai\s+engineer|agent|automation|product|program\s+manager|project\s+manager|data|analytics|quant|business\s+analyst|strategy|operations|fintech|cloud|systems|analyst",
        re.I
    )
    swe_exclude = re.compile(
        r"\b(mobile\s+dev|ios\s+dev|android\s+dev|compiler|firmware|embedded\s+software|kernel|fpga|verilog)\b",
        re.I
    )
    senior_exclude = re.compile(
        r"\b(director|vp\b|vice\s+president|head\s+of|principal|staff\+)\b",
        re.I
    )

    applied_urls = set()
    applied_pairs = set()

    csv_path = candidate.APPLICATIONS
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                for k in ["Job URL", "job_url", "url"]:
                    u = r.get(k)
                    if u:
                        applied_urls.add(u.strip().rstrip("/"))
                c = (r.get("Company") or "").strip().lower()
                ro = (r.get("Role") or "").strip().lower()
                if c and ro:
                    applied_pairs.add((c, ro))

    for r in RE.ledger_rows():
        if r.get("status") == "submitted":
            u = r.get("url")
            if u:
                applied_urls.add(u.strip().rstrip("/"))
            c = (r.get("company") or "").strip().lower()
            ro = (r.get("role") or "").strip().lower()
            if c and ro:
                applied_pairs.add((c, ro))

    q_path = ROOT / "queue_ranked.txt"
    existing_urls = set()
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    if parts and parts[-1].startswith("http"):
                        existing_urls.add(parts[-1].strip().rstrip("/"))

    collected = []
    seen = set()

    def add_candidate(comp, role, url):
        u_norm = url.strip().rstrip("/")
        if not u_norm or u_norm in seen or u_norm in existing_urls or u_norm in applied_urls:
            return
        c_norm = comp.strip().lower()
        r_norm = role.strip().lower()
        if (c_norm, r_norm) in applied_pairs:
            return
        if not kw.search(role) or swe_exclude.search(role) or senior_exclude.search(role):
            return
        from agents.role_filter import reject_reason
        if reject_reason(role):
            return
        score, cat, _ = RE.score_job(comp, role, u_norm)
        if score < 6.5:
            return
        # Greenhouse canonical embed format
        m_gh = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/&?]+)(?:/jobs/|.*[&?]token=)(\d+)", u_norm)
        if m_gh:
            u_norm = f"https://job-boards.greenhouse.io/embed/job_app?for={m_gh.group(1)}&token={m_gh.group(2)}"
            if u_norm in seen or u_norm in existing_urls or u_norm in applied_urls:
                return

        seen.add(u_norm)
        collected.append((comp.strip(), role.strip(), u_norm, score))

    # 1. Pull from existing large master queues
    for qf in ["queue.txt", "queue_phase2.txt"]:
        qp = ROOT / qf
        if not qp.exists():
            continue
        for line in qp.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "http" not in line:
                continue
            parts = line.split()
            u = parts[-1]
            c = parts[0]
            r = " ".join(parts[1:-1]) if len(parts) > 2 else parts[0]
            add_candidate(c, r, u)

    # 2. Pull fresh postings from ATS feeds and GitHub boards
    try:
        jobs = js.fetch(max_age_days=180)
        for j in jobs:
            c = j.get("company") or "Tech"
            r = j.get("role") or j.get("title") or ""
            u = j.get("url") or ""
            add_candidate(c, r, u)
    except Exception as e:
        print(f"[Replenish Job Sources Error] {e}", flush=True)

    # Sort priority: highest fit score first, then Greenhouse > Ashby > Workday > Lever > Other
    def sort_prio(item):
        u = item[2].lower()
        ats_p = 4
        if "greenhouse.io" in u:
            ats_p = 0
        elif "ashbyhq.com" in u:
            ats_p = 1
        elif "myworkdayjobs.com" in u:
            ats_p = 2
        elif "lever.co" in u:
            ats_p = 3
        return (-item[3], ats_p)

    collected.sort(key=sort_prio)

    if collected:
        with open(q_path, "a", encoding="utf-8") as f:
            for c, r, u, _ in collected:
                f.write(f"{c} {r}   {u}\n")

    return len(collected)



async def safe_reply(target, text: str, reply_markup=None):
    """Safely replies to a message or query, falling back to plain text if HTML parsing fails."""
    try:
        return await target.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"[SafeReply Fallback] HTML entity parse error ({e}), sending plain text...")
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        return await target.reply_text(
            clean,
            reply_markup=reply_markup,
            parse_mode=None,
            disable_web_page_preview=True
        )


async def safe_edit(query, text: str, reply_markup=None):
    """Safely edits callback query message, falling back to plain text if HTML parsing fails."""
    try:
        return await query.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"[SafeEdit Fallback] HTML parse error ({e}), sending plain text...")
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        return await query.message.edit_text(
            clean,
            reply_markup=reply_markup,
            parse_mode=None,
            disable_web_page_preview=True
        )


CLOSE_KB = InlineKeyboardMarkup([[InlineKeyboardButton("✖ Close", callback_data="btn_close")]])
PANEL_HOLD = {"until": 0.0}  # while a menu is open on the pinned panel, the 45s refresh leaves it alone


def is_panel(query) -> bool:
    return bool(query.message) and query.message.message_id == load_pinned_status_info().get("message_id")


def hold_panel_view(query, seconds: float = 120.0):
    if is_panel(query):
        PANEL_HOLD["until"] = time_mod.time() + seconds


async def show(query, text: str, kb=None):
    """A button's result. Tapped on the pinned panel -> new message (the panel stays the panel); elsewhere -> edit in place."""
    if is_panel(query):
        return await safe_reply(query.message, text, reply_markup=kb or CLOSE_KB)
    return await safe_edit(query, text, reply_markup=kb or CLOSE_KB)


async def finish(msg, text: str, kb=None):
    """Replace a '⏳ working…' message with the result."""
    try:
        await msg.edit_text(text, reply_markup=kb or CLOSE_KB, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        if "not modified" not in str(e).lower():
            await msg.reply_text(re.sub(r"<[^>]+>", "", text), reply_markup=kb or CLOSE_KB)


async def refresh_panel(context):
    PANEL_HOLD["until"] = 0.0
    await ensure_pinned_live_status(context, chat_id=AUTHORIZED_USER_ID, force_repin=False)


async def safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    """Silently deletes a message by ID without throwing exceptions."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except Exception:
        return False


async def _delayed_delete_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback to delete a message after a countdown."""
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if chat_id and message_id:
        await safe_delete_message(context.bot, chat_id, message_id)


async def _delete_after(bot, chat_id: int, message_ids: list, delay_sec: float = 3.0):
    """Silently deletes messages after a delay without blocking."""
    try:
        await asyncio.sleep(delay_sec)
        for mid in message_ids:
            if mid:
                await safe_delete_message(bot, chat_id, mid)
    except Exception:
        pass


async def _auto_close_decision_tab_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: automatically removes the decision tab after 3 minutes."""
    data = context.job.data or {}
    cid = data.get("chat_id")
    mid = data.get("message_id")
    if cid and mid:
        await safe_delete_message(context.bot, cid, mid)
        if ACTIVE_DECISION_TAB.get("message_id") == mid:
            ACTIVE_DECISION_TAB["message_id"] = None
        print(f"[Decision Tab] Auto-disappeared after 3-minute active window (chat {cid}, msg {mid}).", flush=True)


async def _async_delete_tab_after(bot, chat_id: int, message_id: int, delay_sec: float = 180.0):
    """Async task fallback: deletes the decision tab after 3 minutes (180s)."""
    try:
        await asyncio.sleep(delay_sec)
        await safe_delete_message(bot, chat_id, message_id)
        if ACTIVE_DECISION_TAB.get("message_id") == message_id:
            ACTIVE_DECISION_TAB["message_id"] = None
        print(f"[Decision Tab] Auto-disappeared after {delay_sec}s (chat {chat_id}, msg {message_id}).", flush=True)
    except Exception:
        pass


async def open_or_refresh_decision_tab(context: ContextTypes.DEFAULT_TYPE, chat_id: int, is_scan: bool = False, query=None):
    """
    Opens or refreshes the dedicated Decision Stages & Recruiter Radar Tab.
    The tab displays live stage advancements, deadlines, decision timestamps, and direct clickable URLs.
    It stays active for 3 minutes (180s) and automatically disappears from chat.
    """
    global ACTIVE_DECISION_TAB

    tab_mid = ACTIVE_DECISION_TAB.get("message_id")
    tab_cid = ACTIVE_DECISION_TAB.get("chat_id") or chat_id

    # If is_scan, perform scanning
    if is_scan:
        if query and query.message and query.message.message_id == tab_mid:
            try:
                await safe_edit(query, "⏳ <i>Scanning Gmail for decision emails, stage advancements & deadlines...</i>")
            except Exception:
                pass
        elif query:
            try:
                await query.answer("⏳ Scanning Gmail for decision emails & stage advancements...", show_alert=False)
            except Exception:
                pass

        new_advs = await asyncio.to_thread(scan_and_track_decision_emails, 30)
        if new_advs:
            for adv in new_advs:
                comp = adv.get("company", "Target")
                kb_rows = []
                if adv.get("email_link"):
                    kb_rows.append([InlineKeyboardButton("📬 Open Email in Gmail", url=adv["email_link"])])
                if adv.get("job_url") and adv["job_url"].startswith("http"):
                    kb_rows.append([InlineKeyboardButton("🔗 View Job Portal", url=adv["job_url"])])
                kb_rows.append([
                    InlineKeyboardButton("⚔️ Prep Battlecard", callback_data=f"prep:{comp}"),
                    InlineKeyboardButton("📄 Quick Resume", callback_data="btn_resume"),
                ])
                alert_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=format_advancement_telegram_alert(adv),
                    reply_markup=InlineKeyboardMarkup(kb_rows),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                telegram_query_engine.save_application_message(alert_msg.message_id, chat_id)

    summary = get_decision_pipeline_summary()
    now_time = datetime.now().strftime("%I:%M:%S %p")
    tab_text = (
        f"🎯 <b>[Decision Stages & Recruiter Radar Tab]</b> <i>({now_time})</i>\n"
        f"<i>⏱️ Active for 3 minutes • Auto-disappears automatically</i>\n\n"
        f"{summary}\n\n"
        f"<i>Tap [📬 Scan Decisions Now] to re-check Gmail, or [🗑️ Close Tab Now] to dismiss early.</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📬 Scan Decisions Now", callback_data="btn_scan_inbox")],
        [InlineKeyboardButton("🗑️ Close Tab Now", callback_data="btn_close_decision_tab")]
    ])

    # If tab is already open and valid, edit in-place
    updated = False
    if tab_mid:
        try:
            await context.bot.edit_message_text(
                chat_id=tab_cid,
                message_id=tab_mid,
                text=tab_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            updated = True
        except Exception:
            updated = False

    if not updated:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=tab_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        tab_mid = sent.message_id
        ACTIVE_DECISION_TAB["message_id"] = tab_mid
        ACTIVE_DECISION_TAB["chat_id"] = chat_id

    # Reset 3-minute auto-disappear timer (180s)
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name("decision_tab_timer"):
            j.schedule_removal()
        context.job_queue.run_once(
            _auto_close_decision_tab_job,
            180.0,
            name="decision_tab_timer",
            data={"chat_id": chat_id, "message_id": tab_mid}
        )
    else:
        asyncio.create_task(_async_delete_tab_after(context.bot, chat_id, tab_mid, 180.0))

    if query:
        try:
            toast = "📬 Decisions scan complete! Tab active for 3 min." if is_scan else "🎯 Decision Stages tab opened! Active for 3 min."
            await query.answer(toast, show_alert=False)
        except Exception:
            pass


async def clean_all_questions_action(context: ContextTypes.DEFAULT_TYPE, chat_id: int, trigger_msg_id: int = None):
    """Deletes all active question messages AND all active application messages to eliminate chat buildup."""
    msg_ids = telegram_query_engine.clear_all_pending_questions()
    app_items = telegram_query_engine.clear_all_application_messages()

    deleted_questions = 0
    for mid in msg_ids:
        if await safe_delete_message(context.bot, chat_id, mid):
            deleted_questions += 1

    deleted_apps = 0
    for mid, cid in app_items:
        target_cid = cid or chat_id
        if await safe_delete_message(context.bot, target_cid, mid):
            deleted_apps += 1

    # In private chat, also scan backwards up to 75 messages to cleanly wipe anything opened except pinned status & dynamic HUD
    deleted_scan = 0
    pinned_info = load_pinned_status_info()
    pinned_mid = pinned_info.get("message_id")
    hud_mid = ACTIVE_HUD_STATE.get("message_id")
    protected_ids = {mid for mid in [pinned_mid, hud_mid] if mid}

    # Also clean active decision tab if open
    dec_mid = ACTIVE_DECISION_TAB.get("message_id")
    if dec_mid:
        await safe_delete_message(context.bot, chat_id, dec_mid)
        ACTIVE_DECISION_TAB["message_id"] = None
        if context.job_queue:
            for j in context.job_queue.get_jobs_by_name("decision_tab_timer"):
                j.schedule_removal()

    if trigger_msg_id:
        tracked_ids = set(msg_ids) | {mid for mid, _ in app_items}
        for past_id in range(trigger_msg_id, max(1, trigger_msg_id - 75), -1):
            if past_id not in protected_ids:
                if await safe_delete_message(context.bot, chat_id, past_id):
                    deleted_scan += 1

    total_deleted = deleted_questions + deleted_apps + deleted_scan
    # Re-anchor chat with fresh Control Hub and ensure it is pinned to the top of the chat banner
    await ensure_pinned_live_status(
        context,
        chat_id=chat_id,
        force_repin=False,
        header=f"📌 <b>Job Deck Live Control Panel (Pinned)</b> <i>(Cleaned {total_deleted} items)</i>"
    )


async def sweep_expired_questions_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task: periodically deletes expired 'Input Needed' questions and trims stale questions."""
    try:
        expired = telegram_query_engine.get_expired_question_messages()
        for item in expired:
            mid = item.get("message_id")
            cid = item.get("chat_id") or AUTHORIZED_USER_ID
            if mid:
                await safe_delete_message(context.bot, int(cid), int(mid))
                telegram_query_engine.mark_question_deleted_or_resolved(message_id=mid)

        # Clear any stale pending questions older than 10 mins from pending_questions.json
        pending = telegram_query_engine.load_pending_questions()
        if pending:
            now_ts = datetime.now().timestamp()
            valid = []
            for p in pending:
                asked_ts = 0
                try:
                    asked_ts = datetime.fromisoformat(p.get("asked_at", "")).timestamp()
                except Exception:
                    pass
                if now_ts - asked_ts < 600:
                    valid.append(p)
            if len(valid) != len(pending):
                telegram_query_engine.save_pending_questions(valid)
    except Exception as e:
        print(f"[Smart Cleaner Sweeper Error] {e}", flush=True)

# ---- Handlers ----

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    await ensure_pinned_live_status(context, chat_id=update.effective_chat.id, force_repin=False)
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    text_out, kb = get_onboarding_step_message(1)
    await update.message.reply_text(text_out, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    target_chat = update.effective_chat.id
    # Always update the single active control panel in-place! Never duplicate!
    await ensure_pinned_live_status(context, chat_id=target_chat, force_repin=False)
    if update.message:
        notice = await update.message.reply_text(
            "📌 <b>Job Deck Live Control Panel updated live above!</b>\n<i>(Single always-active control panel)</i>",
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(_delete_after(context.bot, target_chat, [update.message.message_id, notice.message_id], 3.0))


async def handle_bot_error(update, context: ContextTypes.DEFAULT_TYPE):
    """Any handler crash: log it and tell the owner instead of failing silently."""
    print(f"[Bot Error] {type(context.error).__name__}: {context.error}", flush=True)
    try:
        if isinstance(update, Update) and update.effective_chat and update.effective_chat.id == AUTHORIZED_USER_ID:
            await context.bot.send_message(update.effective_chat.id, f"⚠️ That didn't work: {h(str(context.error)[:200])}. Try again.", parse_mode=ParseMode.HTML)
    except Exception:
        pass


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != AUTHORIZED_USER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return

    data = query.data
    try:
        await query.answer()
    except Exception as e:  # a tap answered late still runs its action
        print(f"[Callback Answer Late] {data}: {e}", flush=True)

    # 0. Confirm / discard a Gemini-proposed change: prop|<proposal id>|y|n (only this button applies it)
    if data.startswith("prop|"):
        parts = data.split("|")
        if len(parts) != 3 or parts[2] not in ("y", "n"):
            await safe_edit(query, "⚠️ Invalid button.")
            return
        result = telegram_query_engine.apply_proposal(parts[1], confirm=parts[2] == "y")
        await safe_edit(query, result)
        return

    # 1. Answer button tapped: ans|<q_id>|<option index>
    if data.startswith("ans|"):
        parts = data.split("|")
        if len(parts) == 3:
            q_id, idx = parts[1], parts[2]
            res = telegram_query_engine.resolve_by_option_index(q_id, idx)
            if not res.get("ok"):
                await safe_edit(query, f"⚠️ {res.get('msg', 'Unknown question')}")
                return
            telegram_query_engine.mark_question_deleted_or_resolved(message_id=query.message.message_id, q_id=q_id)

            confirm_text = (
                f"✅ <b>Answer Recorded:</b> <code>{h(res.get('answer'))}</code>\n"
                f"<b>Field:</b> {h(res.get('question', 'Field'))}\n\n"
                f"<i>🧹 Smart auto-delete: removing message in 4s to keep chat clean...</i>"
            )
            await safe_edit(query, confirm_text)

            # Auto-delete message in 4 seconds
            if context.job_queue:
                context.job_queue.run_once(
                    _delayed_delete_job,
                    when=4.0,
                    data={"chat_id": query.message.chat_id, "message_id": query.message.message_id}
                )
            else:  # no local "import asyncio": it made asyncio local to the whole handler and crashed every button
                async def _del():
                    await asyncio.sleep(4)
                    await safe_delete_message(context.bot, query.message.chat_id, query.message.message_id)
                asyncio.create_task(_del())
            return

    # 2. Panel and menus: these change the panel in place
    if data in ("btn_status", "btn_settings", "btn_more", "btn_target") or data.startswith("set|"):
        if data.startswith("set|"):
            _, key, val = (data.split("|") + ["", ""])[:3]
            s = load_settings()
            if key == "workers" and val.isdigit():
                save_settings(workers=int(val))
            elif key == "delay":
                try:
                    save_settings(delay=float(val))
                except ValueError:
                    pass
            elif key == "autopilot" and val in ("on", "off"):
                save_settings(autopilot=val == "on")
            data = "btn_settings"
        if data == "btn_status":
            if is_panel(query):
                PANEL_HOLD["until"] = 0.0  # back on the panel: live refresh resumes
            m = get_realtime_metrics()
            text_out, kb = format_status_message(metrics=m), get_smart_keyboard(m)
        else:
            text_out, kb = {"btn_settings": get_settings_view, "btn_more": get_more_view,
                            "btn_target": get_target_customizer_panel}[data]()
            hold_panel_view(query)
        await safe_edit(query, text_out, reply_markup=kb)
        return

    if data == "btn_close":
        await safe_delete_message(context.bot, query.message.chat_id, query.message.message_id)
        return

    if data == "btn_setup_wizard" or data.startswith("onboard:step:"):
        try:
            step_num = int(data.split(":")[-1])
        except ValueError:
            step_num = 1
        text_out, kb = get_onboarding_step_message(step_num)
        hold_panel_view(query)
        await safe_edit(query, text_out, reply_markup=kb)
        return

    # 3. Actions: each one answers with its own result message
    if data in ("btn_run", "btn_start_deck", "onboard:launch", "btn_turbo", "btn_sweep"):
        msg = await show(query, "⏳ <i>Starting the runner…</i>")
        if data == "btn_turbo":
            text_out = await start_runner_and_report(calculate_dynamic_turbo_workers()[0], 1.0, force=True)
        elif data == "btn_sweep":
            text_out = await start_runner_and_report(1, 3.0, force=True)
        else:
            text_out = await start_runner_and_report()
        await finish(msg, text_out)
        await refresh_panel(context)

    elif data == "btn_stop":
        await show(query, await stop_runner_and_report())
        await refresh_panel(context)

    elif data == "btn_clean_questions":
        await clean_all_questions_action(context, query.message.chat_id, trigger_msg_id=query.message.message_id)
        await refresh_panel(context)

    elif data == "btn_recent":
        await show(query, recent_text())

    elif data == "btn_stats":
        await show(query, stats_text())

    elif data == "btn_questions":
        ans, _ = telegram_query_engine.answer_natural_language_query("pending questions")
        await show(query, ans)

    elif data == "btn_alerts":
        inbox = get_realtime_metrics()["inbox_actions"]
        await show(query, ("📬 <b>Recruiter inbox items:</b>\n\n" + "\n".join(h(i) for i in inbox[:10])) if inbox else "✅ <b>No recruiter actions pending.</b>")

    elif data == "btn_replenish":
        msg = await show(query, "⏳ <i>Searching job sources for new internships…</i>")
        added = await asyncio.to_thread(replenish_queue_action)
        m = get_realtime_metrics()
        await finish(msg, f"➕ <b>Queue refilled:</b> {added} new eligible job(s) added. {m['unapplied_count']} left to apply.")

    elif data == "btn_assessments":
        await show(query, ASSESSMENTS_MSG)

    elif data.startswith(("quick_apply|", "target_idx|", "target_all|")):
        parts = data.split("|")
        target_q = parts[1].strip() if len(parts) > 1 else ""
        msg = await show(query, f"⏳ <i>Starting {h(target_q)}…</i>")
        if data.startswith("target_idx|"):
            r_idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            res = await asyncio.to_thread(launch_mid_session_targeted_job, target_q, True, 1, r_idx)
        else:
            res = await asyncio.to_thread(launch_mid_session_targeted_job, target_q, True, 3 if data.startswith("target_all|") else 1)
        text_out, kb = format_targeted_launch_message(res)
        await finish(msg, text_out, kb)

    elif data == "btn_resume":
        await send_quickview_doc(query.message, context, is_letter=False)

    elif data == "btn_view":
        await send_screen_cam(query.message, context)

    elif data == "btn_hud":
        await handle_live_hud(query.message, context)

    elif data == "btn_interview":
        sent = await safe_reply(query.message, start_interview_session(query.message.chat_id, "Target Employer", "Cybersecurity Specialist"))
        if sent:
            telegram_query_engine.save_application_message(sent.message_id, query.message.chat_id)

    elif data in ("btn_decisions", "btn_scan_inbox"):
        # the decision tab is its own message (edited in place by its saved id), never the pinned panel
        await open_or_refresh_decision_tab(context, chat_id=query.message.chat_id, is_scan=data == "btn_scan_inbox")

    elif data == "btn_close_decision_tab":
        mid = query.message.message_id
        await safe_delete_message(context.bot, query.message.chat_id, mid)
        if ACTIVE_DECISION_TAB.get("message_id") == mid:
            ACTIVE_DECISION_TAB["message_id"] = None
        if context.job_queue:
            for j in context.job_queue.get_jobs_by_name("decision_tab_timer"):
                j.schedule_removal()

    elif data == "btn_optimize_pc":
        msg = await show(query, "⏳ <i>Freeing memory…</i>")
        from agents.pc_optimizer import run_full_system_optimization
        res = await asyncio.to_thread(run_full_system_optimization)
        await finish(msg, f"🖥️ <b>PC cleaned up:</b> {res['reclaimed_mb']} MB freed, {res['zombies_killed']} stuck browser(s) closed, "
                          f"{res['procs_optimized']} process(es) set to low priority.")

    elif data == "btn_pin_status":
        await ensure_pinned_live_status(context, chat_id=query.message.chat_id, force_repin=True)

    elif data.startswith(("prep:", "radar:")):
        kind, comp = data.split(":", 1)
        msg = await show(query, f"⏳ <i>Building {'interview battlecard' if kind == 'prep' else 'referral dossier'} for {h(comp)}…</i>")
        if kind == "prep":
            from agents import interview_prep
            res = await asyncio.to_thread(interview_prep.generate_interview_battlecard, company=comp, role="Cybersecurity Specialist")
        else:
            from agents import referral_radar
            res = await asyncio.to_thread(referral_radar.build_referral_dossier, company=comp, role="Cybersecurity")
        await finish(msg, res["telegram_summary"])

    elif data.startswith("dl_pdf:"):
        pdf_p = PDF_TOKENS.get(data.split(":", 1)[1])
        if pdf_p and pdf_p.exists():
            with open(pdf_p, "rb") as f:
                await query.message.reply_document(document=f, caption=f"📄 <code>{h(pdf_p.name)}</code>", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("❌ PDF file not found on disk.")

    else:
        await show(query, "⚠️ That button is from an old menu. Use the pinned panel.")


def recent_text() -> str:
    recent = get_realtime_metrics()["recent"]
    if not recent:
        return "📋 <b>Recent applications</b>\n\n<i>None recorded yet.</i>"
    lines = ["📋 <b>Recent applications</b>\n"]
    for r in reversed(recent):
        url = r.get("Job URL", "")
        name = f'<a href="{h(url)}">{h(r.get("Company"))}</a>' if url.startswith("http") else f"<b>{h(r.get('Company'))}</b>"
        lines.append(f"• {name} — {h(r.get('Role'))} (<i>{h(r.get('Date Applied'))}</i>)")
    return "\n".join(lines)


def stats_text() -> str:
    m = get_realtime_metrics()
    top = sorted(m["companies"].items(), key=lambda x: -x[1])[:5]
    top_str = "\n".join(f"  • {h(c)}: {n}" for c, n in top) or "  • No data yet"
    cats = "\n".join(f"  • {k}: {v}" for k, v in m["roles_category"].items() if v)
    return ("📈 <b>Stats</b>\n\n"
            f"<b>Applied:</b> {m['total_applied']} total · +{m['today_applied']} today\n"
            f"<b>Queue:</b> {m['unapplied_count']} left of {m['queue_count']}\n\n"
            f"<b>Top companies:</b>\n{top_str}\n\n"
            f"<b>By type:</b>\n{cats or '  • No data yet'}\n\n"
            f"<b>Runner:</b> {m['worker_count']} process(es), {m['total_mem_mb']}MB")


PDF_TOKENS = {}  # callback_data is capped at 64 bytes and must not carry a file path


def pdf_token(path) -> str:
    tok = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    PDF_TOKENS[tok] = Path(path)
    return tok


async def send_quickview_doc(target_msg, context: ContextTypes.DEFAULT_TYPE, is_letter: bool = False, query_comp: str = ""):
    """Renders the first page of a tailored PDF to PNG image for instant mobile preview without downloading."""
    comp = query_comp.strip() if query_comp else None
    finder = find_latest_tailored_letter if is_letter else find_latest_tailored_resume
    pdf_path = finder(comp)
    if not pdf_path or not pdf_path.exists():
        await safe_reply(target_msg, f"❌ No tailored {'cover letter' if is_letter else 'resume'} found" + (f" for '{comp}'." if comp else "."))
        return

    doc_type = "Cover Letter" if is_letter else "Tailored Resume"
    try:
        img_bytes = await asyncio.to_thread(render_pdf_to_image_bytes, pdf_path)
        co_display = pdf_path.parent.name.replace("_", " ") if pdf_path.parent.name != "resumes" else "Master Candidate"
        caption = (
            f"📄 <b>Quick-View {doc_type}:</b> <code>{h(co_display)}</code>\n"
            f"🎯 <i>Tap photo above to view full-screen without downloading!</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download PDF File", callback_data=f"dl_pdf:{pdf_token(pdf_path)}")]
        ])
        sent = await target_msg.reply_photo(
            photo=img_bytes,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        if sent:
            telegram_query_engine.save_application_message(sent.message_id, target_msg.chat_id)
    except Exception as e:
        with open(pdf_path, "rb") as f:
            sent = await target_msg.reply_document(
                document=f,
                caption=f"📄 <b>{doc_type}</b> ({h(pdf_path.name)})",
                parse_mode=ParseMode.HTML
            )
            if sent:
                telegram_query_engine.save_application_message(sent.message_id, target_msg.chat_id)


async def send_screen_cam(target_msg, context: ContextTypes.DEFAULT_TYPE):
    """Captures and sends an instant screenshot of the active browser viewport."""
    snap = await asyncio.to_thread(capture_active_worker_screenshot)
    m = get_realtime_metrics()
    if not snap:
        status_text = (
            "📸 <b>Live Screen Cam:</b> <i>Browser is currently idle or initializing.</i>\n\n"
            f"⚡ <b>Runner Status:</b> {'🟢 Running' if m['is_running'] else '⚪ Idle'}\n"
            f"📍 <b>Active Target:</b> <i>{h(m.get('current_target') or 'None')}</i>\n\n"
            f"<i>Tap ▶ Run on the pinned panel to start applying.</i>"
        )
        sent = await safe_reply(target_msg, status_text, reply_markup=CLOSE_KB)
        if sent:
            telegram_query_engine.save_application_message(sent.message_id, target_msg.chat_id)
        return
    img_bytes, caption = snap
    sent = await target_msg.reply_photo(
        photo=img_bytes,
        caption=f"{h(caption)}\n<i>⚡ Live view from active Playwright worker</i>",
        reply_markup=CLOSE_KB,
        parse_mode=ParseMode.HTML
    )
    if sent:
        telegram_query_engine.save_application_message(sent.message_id, target_msg.chat_id)


async def handle_live_hud(target_msg, context: ContextTypes.DEFAULT_TYPE):
    """Initializes or toggles the live updating single-message ticker ON and OFF without duplicates."""
    global ACTIVE_HUD_STATE
    chat_id = target_msg.chat_id

    # If HUD is already active -> TOGGLE OFF
    if ACTIVE_HUD_STATE.get("message_id"):
        old_msg_id = ACTIVE_HUD_STATE["message_id"]
        old_chat_id = ACTIVE_HUD_STATE.get("chat_id") or chat_id

        # Cancel ticker repeating job
        if context.job_queue:
            jobs = context.job_queue.get_jobs_by_name("hud_ticker_job")
            for j in jobs:
                j.schedule_removal()

        ACTIVE_HUD_STATE["message_id"] = None
        m = get_realtime_metrics()

        try:
            await context.bot.edit_message_text(
                chat_id=old_chat_id,
                message_id=old_msg_id,
                text="📡 <b>[Job Deck Dynamic HUD — Turned OFF]</b>\n\n<i>Live dynamic ticker paused. Tap [📡 Live Dynamic HUD] below or text /hud to restart anytime.</i>",
                reply_markup=CLOSE_KB,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        await safe_reply(target_msg, "📡 <b>Dynamic HUD Ticker Turned OFF.</b>", reply_markup=CLOSE_KB)
        return

    # If HUD is NOT active -> TOGGLE ON
    m = get_realtime_metrics()
    now_str = datetime.now().strftime("%I:%M:%S %p")
    target_str = f"📍 <b>Target:</b> <i>{h(m['current_target'])}</i>\n" if m.get("current_target") else ""
    hud_text = (
        f"📡 <b>[Job Deck Dynamic HUD — Live Ticker ACTIVE]</b> <i>({now_str})</i>\n\n"
        f"⚡ <b>Runner:</b> {'🟢 ' + str(m['worker_count']) + ' Workers Active' if m['is_running'] else '⚪ Idle'}\n"
        f"{target_str}"
        f"📊 <b>Today:</b> <b>+{m['today_applied']}</b> applied | Total: <b>{m['total_applied']} / 3000</b>\n"
        f"🧠 <b>Memory:</b> {m['total_mem_mb']}MB RSS ({m.get('avail_gb', 0):.1f}GB free)\n"
        f"📋 <b>Priority Queue:</b> {m['unapplied_count']} unapplied roles\n\n"
        f"<i>⚡ Updating live in-place every 4s • Tap button again to Stop</i>"
    )

    sent_msg = await target_msg.reply_text(hud_text, parse_mode=ParseMode.HTML)
    ACTIVE_HUD_STATE["message_id"] = sent_msg.message_id
    ACTIVE_HUD_STATE["chat_id"] = chat_id

    if context.job_queue:
        context.job_queue.run_repeating(
            _update_hud_tick,
            interval=4.0,
            first=3.0,
            name="hud_ticker_job",
            data={"chat_id": chat_id, "message_id": sent_msg.message_id, "ticks": 0}
        )


async def _update_hud_tick(context: ContextTypes.DEFAULT_TYPE):
    """Periodic tick updater for live dynamic HUD message."""
    global ACTIVE_HUD_STATE
    data = context.job.data
    chat_id = data["chat_id"]
    msg_id = data["message_id"]

    # Check if HUD was toggled off externally
    if ACTIVE_HUD_STATE.get("message_id") != msg_id:
        context.job.schedule_removal()
        return

    data["ticks"] += 1

    # Auto-stop ticker after 45 ticks (~3 minutes) if unattended to prevent infinite loop
    if data["ticks"] > 45:
        ACTIVE_HUD_STATE["message_id"] = None
        context.job.schedule_removal()
        try:
            m = get_realtime_metrics()
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text="📡 <b>[Job Deck Dynamic HUD — Auto-Paused]</b>\n\n<i>Live ticker paused after 3 minutes of active telemetry. Tap button below to resume anytime!</i>",
                reply_markup=CLOSE_KB,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    m = get_realtime_metrics()
    now_str = datetime.now().strftime("%I:%M:%S %p")
    target_str = f"📍 <b>Target:</b> <i>{h(m['current_target'])}</i>\n" if m.get("current_target") else ""

    hud_text = (
        f"📡 <b>[Job Deck Dynamic HUD — Live Ticker ACTIVE]</b> <i>({now_str})</i>\n\n"
        f"⚡ <b>Runner:</b> {'🟢 ' + str(m['worker_count']) + ' Workers Active' if m['is_running'] else '⚪ Idle'}\n"
        f"{target_str}"
        f"📊 <b>Today:</b> <b>+{m['today_applied']}</b> applied | Total: <b>{m['total_applied']} / 3000</b>\n"
        f"🧠 <b>System Health:</b> {m['total_mem_mb']}MB RAM | {m.get('avail_gb', 0):.1f}GB headroom\n"
        f"📋 <b>Queue:</b> {m['unapplied_count']} unapplied roles\n\n"
        f"<i>Tick {data['ticks']}/45 • Updating live in-place</i>"
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=hud_text,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        err = str(e).lower()
        if "message to edit not found" in err or "message can't be edited" in err:
            ACTIVE_HUD_STATE["message_id"] = None
            context.job.schedule_removal()


async def handle_url_drop(url: str, target_msg, context: ContextTypes.DEFAULT_TYPE):
    """Handles an instant URL drop, canonicalizes Greenhouse embeds, and launches isolated priority worker."""
    import re
    clean_url = url.strip()
    m_gh = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/&?]+)(?:/jobs/|.*[&?]token=)(\d+)", clean_url)
    if m_gh:
        board, token = m_gh.groups()
        canonical_url = f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={token}"
        comp_name = board.capitalize()
    else:
        canonical_url = clean_url
        comp_name = "Target Employer"

    import results_engine as RE
    if not re.match(r"^https?://", canonical_url):
        await safe_reply(target_msg, "⚠️ Only http(s) job links can be applied to. Nothing was started.")
        return
    if any(r.get("status") == "submitted" and r.get("url", "").strip() == canonical_url for r in RE.ledger_rows()):
        await safe_reply(target_msg, f"✅ You already applied to this posting. Nothing was started.\n<code>{h(canonical_url)}</code>")
        return

    # sys.executable + fill.py's default resume: the old .venv / resumes paths don't exist, so every drop failed silently
    cmd = [sys.executable, "-u", str(ROOT / "fill.py"), canonical_url, "--headless", "--company", comp_name]
    try:
        subprocess.Popen(cmd, cwd=str(ROOT))
    except OSError as e:
        await safe_reply(target_msg, f"⚠️ Could not start the application: {h(e)}")
        return
    await safe_reply(
        target_msg,
        f"🎯 <b>Auto-Apply Triggered!</b>\n"
        f"<b>Employer:</b> {h(comp_name)}\n"
        f"<b>URL:</b> <code>{h(canonical_url)}</code>\n\n"
        f"⚡ <i>Launching isolated priority worker in headless mode...</i>"
    )


async def send_daily_morning_brief(context: ContextTypes.DEFAULT_TYPE):
    """Delivers an executive morning brief at 8:00 AM daily."""
    m = get_realtime_metrics()
    today_applied = m["today_applied"]
    total = m["total_applied"]
    unapplied = m["unapplied_count"]
    now_str = datetime.now().strftime("%A, %B %d, %Y")

    brief = (
        f"🌅 <b>GOOD MORNING {h((candidate.fact('PREFERRED_NAME') or candidate.fact('FIRST_NAME')).upper())} — EXECUTIVE BRIEFING</b>\n"
        f"📅 <i>{now_str}</i>\n"
        f"─────────────────────────────\n"
        f"🎯 <b>Milestone Progress:</b> <b>{total} / 3000</b> ({(total/3000)*100:.1f}%)\n"
        f"⚡ <b>Verified Submissions (Today):</b> +{today_applied}\n"
        f"📋 <b>Queue Inventory:</b> {unapplied} unapplied cybersecurity & IAM roles ready\n\n"
        f"🛡️ <b>Recommended Morning Actions:</b>\n"
        f"• Tap <code>/apply</code> or <b>[🚀 Launch 3 Workers]</b> to kick off submissions.\n"
        f"• Type <code>/inbox</code> to review recruiter responses or assessment requests.\n"
        f"• Type <code>/interview &lt;Company&gt;</code> to run a 5-minute mock interview screen."
    )
    try:
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=brief,
            reply_markup=CLOSE_KB,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"[Morning Briefing Error] {e}", flush=True)


async def check_inbox_radar_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic recruiter radar: scans for decision emails, stage advancements, and urgent interviews."""
    try:
        new_advs = await asyncio.to_thread(scan_and_track_decision_emails, 14)
        for adv in new_advs:
            msg = format_advancement_telegram_alert(adv)
            comp = adv.get("company", "Target")
            kb_rows = []
            if adv.get("email_link"):
                kb_rows.append([InlineKeyboardButton("📬 Open Email in Gmail", url=adv["email_link"])])
            kb_rows.append([
                InlineKeyboardButton("⚔️ Prep Battlecard", callback_data=f"prep:{comp}"),
                InlineKeyboardButton("📄 Quick Resume", callback_data="btn_resume"),
            ])
            kb_rows.append([
                InlineKeyboardButton("🤝 Warm Referrals", callback_data=f"radar:{comp}"),
            ])
            kb = InlineKeyboardMarkup(kb_rows)
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=msg,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            # Forward advancement directly to iMessage pager
            try:
                from agents.imessage_bridge import forward_advancement_to_imessage
                forward_advancement_to_imessage(adv)
            except Exception:
                pass

        m = get_realtime_metrics()
        inbox = m.get("inbox_actions", [])
        if inbox and not new_advs:
            urgent_items = "\n".join(f"• {item}" for item in inbox[:5])
            alert = (
                f"🚨 <b>RECRUITER & INTERVIEW RADAR ALERT</b>\n\n"
                f"{h(urgent_items)}\n\n"
                f"💡 <i>Type /prep &lt;Company&gt; for an instant Interview Battlecard!</i>"
            )
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=alert,
                parse_mode=ParseMode.HTML
            )
            try:
                from agents.imessage_bridge import send_imessage, is_imessage_available
                if is_imessage_available():
                    send_imessage(f"🚨 RECRUITER & INTERVIEW ALERT:\n\n{urgent_items}\n\nReply 'status' or check your email.")
            except Exception:
                pass
    except Exception as e:
        print(f"[Inbox Radar Error] {e}", flush=True)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Voice Memo Control: downloads Telegram voice note, transcribes via Google Web Speech, and executes."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    if not update.message or not update.message.voice:
        return

    status_msg = await update.message.reply_text("🎙️ <i>Transcribing voice memo...</i>", parse_mode=ParseMode.HTML)
    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()
        transcribed_text = transcribe_voice_bytes(bytes(voice_bytes))
        await safe_delete_message(context.bot, update.effective_chat.id, status_msg.message_id)

        if not transcribed_text:
            await update.message.reply_text(
                "⚠️ <i>Could not transcribe audio clearly. Please try speaking closer or send a text command.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        await update.message.reply_text(
            f"🗣️ <b>Voice Command Heard:</b> <i>\"{h(transcribed_text)}\"</i>",
            parse_mode=ParseMode.HTML
        )
        update.message.text = transcribed_text
        await handle_text(update, context)
    except Exception as e:
        await safe_reply(update.message, f"⚠️ Voice memo error: {h(e)}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    text = update.message.text or ""
    t_lower = text.strip().lower()

    # Priority 0: Active Mock Interview Session
    if is_in_interview(update.effective_chat.id):
        if t_lower in ["/exit", "exit", "/quit", "quit", "cancel", "stop", "/stop"]:
            INTERVIEW_SESSIONS.pop(update.effective_chat.id, None)
            await safe_reply(update.message, "🚪 <b>Mock interview session cancelled.</b> Type <code>/interview &lt;Company&gt;</code> anytime to restart!")
            return
        eval_text = evaluate_and_advance_interview(update.effective_chat.id, text)
        await safe_reply(update.message, eval_text)
        return

    # Priority 0.5: answers / rules before keyword routing ("answer qX: I can start in May" must not launch the runner)
    if await handle_answer_text(update, context, text):
        return

    # Priority 0.6: a Telegram reply to one of the bot's messages. Reply to a question -> that is its answer;
    # reply to anything else -> the AI sees what you replied to.
    replied = update.message.reply_to_message
    if replied and text.strip() and not text.startswith(("/", "http://", "https://")):
        q = next((p for p in telegram_query_engine.load_pending_questions()
                  if str(p.get("message_id")) == str(replied.message_id)), None)
        if q:
            res = telegram_query_engine.resolve_pending_question(q["id"], text.strip())
            if res.get("ok"):
                await safe_delete_message(context.bot, update.effective_chat.id, replied.message_id)
                await safe_reply(update.message, f"✅ <b>Saved:</b> <code>{h(res['answer'])}</code>\n<b>Question:</b> {h(res.get('question', ''))}", reply_markup=CLOSE_KB)
            else:
                await safe_reply(update.message, f"⚠️ {h(res.get('msg', 'Could not save that answer.'))}")
            return
        quoted = (replied.text or replied.caption or "").strip()
        if quoted:
            await reply_with_engine(update, f'(Replying to your earlier message: "{quoted[:800]}")\n\n{text}')
            return

    # Priority 1: Instant URL Drop & Auto-Apply
    if text.startswith("http://") or text.startswith("https://") or t_lower.startswith("/add") or t_lower.startswith("add:"):
        url = text.split(":", 1)[1].strip() if (t_lower.startswith("add:") or t_lower.startswith("/add")) else text.strip()
        await handle_url_drop(url, update.message, context)
        return

    # Priority 1.2: start applying / pause / status / settings (exact commands only: "close the tab" must not halt the runner)
    if t_lower in RUN_WORDS:
        msg = await safe_reply(update.message, "⏳ <i>Starting the runner…</i>")
        await finish(msg, await start_runner_and_report())
        await refresh_panel(context)
        return
    if t_lower in STOP_WORDS:
        await safe_reply(update.message, await stop_runner_and_report(), reply_markup=CLOSE_KB)
        await refresh_panel(context)
        return
    if t_lower in VIEW_WORDS:
        text_out, kb = VIEW_WORDS[t_lower]()
        await safe_reply(update.message, text_out, reply_markup=kb)
        return

    # Priority 1.4: Open Mid-Session Target Customizer Menu (/target)
    if t_lower in ["/target", "target", "customize", "/customize", "customize jobs"]:
        target_text, kb = get_target_customizer_panel()
        await safe_reply(update.message, target_text, reply_markup=kb)
        return

    # Priority 1.5: Mid-Session Targeted Company/Job Execution ("Apply to this job with Visa", "Apply to this job with Goldman", "/apply Visa", etc.)
    targeted_query = parse_targeted_apply_intent(text)
    if targeted_query:
        await confirm_targeted_apply(update.message, targeted_query)
        return

    # Priority 1.8: assessments (/assessments, /oa)
    if t_lower in ["/assessments", "assessments", "/oa", "oa", "solve assessments", "run assessments", "complete assessments"]:
        await safe_reply(update.message, ASSESSMENTS_MSG, reply_markup=CLOSE_KB)
        return

    # Priority 1.9: Queue Inspector & Customizer (/queue)
    if t_lower in ["/queue", "queue", "show queue", "view queue", "top queue", "my queue"]:
        top_jobs = []
        for comp_q, n in (("Palantir", 2), ("Visa", 2), ("Goldman", 1), ("Scale AI", 2)):
            top_jobs += eligible_targets(await asyncio.to_thread(resolve_targeted_company_jobs, comp_q, False))[:n]
        lines = [
            "📋 <b>Top Priority FDE / AI / Product / Data Queue</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for idx, j in enumerate(top_jobs[:6], start=1):
            lines.append(f"{idx}. <b>{h(j['company'])}</b> — {h(j['role'][:48])} (<code>fit {j.get('base_score', j['score'])}</code>)")
        lines.append("\n💬 <i>Tap a button below or type <code>Apply to this job with [Company]</code> to run any role mid-session!</i>")
        _, kb = get_target_customizer_panel()
        await safe_reply(update.message, "\n".join(lines), reply_markup=kb)
        return

    # Priority 2: Quick-View Resume & Cover Letter
    if any(k in t_lower for k in ["my resume", "show resume", "quick resume", "view resume", "pull up resume", "bring up resume", "see resume"]) or t_lower.startswith("/resume") or t_lower.startswith("resume:") or t_lower in ["/resume", "resume", "/cv", "cv"]:
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 and not any(p in parts[1].lower() for p in ["resume", "my", "up", "the"]) else ""
        await send_quickview_doc(update.message, context, is_letter=False, query_comp=comp)
        return
    elif any(k in t_lower for k in ["cover letter", "my letter", "show letter", "view letter"]) or t_lower.startswith("/letter") or t_lower.startswith("letter:") or t_lower in ["/letter", "letter", "/cl", "cl"]:
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 and not any(p in parts[1].lower() for p in ["letter", "my", "up", "the"]) else ""
        await send_quickview_doc(update.message, context, is_letter=True, query_comp=comp)
        return

    # Priority 2.5: Pinned Live Status View
    elif any(k in t_lower for k in [
        "pinned live status", "pinned status", "pin live status", "pin status",
        "pin live view", "pinned view", "pin live", "pinned live",
        "dont see the pinned", "don't see the pinned", "where is the pinned",
        "show pinned", "pin the status", "pin hud", "repin"
    ]) or t_lower in ["/pin", "pin", "/pinned"]:
        pinned_id = await ensure_pinned_live_status(context, chat_id=update.effective_chat.id, force_repin=True)
        if update.message:
            notice = await update.message.reply_text(
                "📌 <b>Live Status View has been pinned to the top of your chat banner!</b>\n\n"
                "<i>The banner at the top of your chat updates continuously and keeps your full controls one tap away at all times.</i>",
                parse_mode=ParseMode.HTML
            )
            asyncio.create_task(_delete_after(context.bot, update.effective_chat.id, [update.message.message_id, notice.message_id], 3.0))
        return

    # Priority 3: Live Headless Screen Cam (matches conversational requests like "bring up the live view")
    elif any(k in t_lower for k in [
        "live view", "screen cam", "screencam", "screenshot", "screen shot",
        "show screen", "view screen", "browser view", "bring up the view",
        "bring up the live view", "bring up live view", "see the screen",
        "what is the browser doing", "show browser", "take a screenshot"
    ]) or t_lower in ["/view", "view", "/snap", "snap", "/screenshot", "screenshot", "/cam", "cam"]:
        await send_screen_cam(update.message, context)
        return

    # Priority 4: Dynamic Live HUD Ticker
    elif any(k in t_lower for k in [
        "hud", "ticker", "live ticker", "dynamic hud", "live updates",
        "bring up the hud", "bring up hud", "live dashboard", "ticker card"
    ]) or t_lower in ["/hud", "hud", "/ticker", "ticker", "live", "/live"]:
        await handle_live_hud(update.message, context)
        return

    # Priority 5: AI Mock Interviewer Initiation
    elif t_lower.startswith("/interview") or t_lower.startswith("interview:") or t_lower.startswith("/mock") or t_lower.startswith("mock:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        prompt = start_interview_session(update.effective_chat.id, comp, "Cybersecurity Specialist")
        await safe_reply(update.message, prompt)
        return

    # Priority 6: Autonomous Compensation & Offer Negotiator
    elif t_lower.startswith("/negotiate") or t_lower.startswith("negotiate:") or t_lower.startswith("/offer") or t_lower.startswith("offer:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        rest = parts[1].strip() if len(parts) > 1 else "Axon $85,000 US"
        subparts = rest.split()
        comp = subparts[0] if len(subparts) > 0 else "Employer"
        amount = subparts[1] if len(subparts) > 1 else "$85,000"
        loc = " ".join(subparts[2:]) if len(subparts) > 2 else "US"
        strat = await asyncio.to_thread(analyze_offer_and_strategize, comp, amount, loc)
        await safe_reply(update.message, strat["telegram_summary"])
        return

    # Priority 7: ATS Keyword Gap & Resume Heatmap
    elif t_lower.startswith("/gap") or t_lower.startswith("gap:") or t_lower.startswith("/heatmap") or t_lower.startswith("heatmap:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        gap_res = await asyncio.to_thread(analyze_ats_gap, comp, "Cybersecurity Specialist")
        await safe_reply(update.message, gap_res["telegram_summary"])
        return

    # Priority 8: speed presets
    elif t_lower in ["/turbo", "turbo", "/stealth", "stealth"]:
        turbo = "turbo" in t_lower
        msg = await safe_reply(update.message, "⏳ <i>Starting the runner…</i>")
        await finish(msg, await start_runner_and_report(calculate_dynamic_turbo_workers()[0] if turbo else 1, 1.0 if turbo else 8.0, force=True))
        await refresh_panel(context)
        return

    # Priority 9: Recruiter Inbox Radar
    elif t_lower in ["/inbox", "inbox"]:
        m = get_realtime_metrics()
        inbox = m.get("inbox_actions", [])
        if not inbox:
            await safe_reply(update.message, "✅ <b>No urgent recruiter actions pending in your inbox!</b>")
        else:
            await safe_reply(update.message, "📬 <b>Urgent Recruiter Inbox Items:</b>\n\n" + "\n".join(f"• {h(item)}" for item in inbox[:10]))
        return

    # Priority 10: Decision Tracking & Stage Advancements (Active for 3 min tab)
    elif t_lower in ["/decisions", "decisions", "/advancements", "advancements", "/stages", "stages"]:
        await open_or_refresh_decision_tab(context, chat_id=update.effective_chat.id, is_scan=False)
        if update.message:
            asyncio.create_task(_delete_after(context.bot, update.effective_chat.id, [update.message.message_id], 3.0))
        return
    elif any(k in t_lower for k in ["scan inbox", "check inbox", "/scan_inbox", "scan_inbox", "/check_inbox", "check_inbox", "/scan", "scan decisions", "check decisions", "scan recruiters"]):
        await open_or_refresh_decision_tab(context, chat_id=update.effective_chat.id, is_scan=True)
        if update.message:
            asyncio.create_task(_delete_after(context.bot, update.effective_chat.id, [update.message.message_id], 3.0))
        return
    elif t_lower in ["optimize", "/optimize", "/boost", "boost", "/cleanram", "clean ram", "optimize pc", "free ram", "boost pc", "speed up"]:
        await safe_reply(update.message, "🧹 <i>Running comprehensive PC & Job Deck optimization...</i>")
        from agents.pc_optimizer import run_full_system_optimization
        res = await asyncio.to_thread(run_full_system_optimization)
        msg = (
            f"🚀 <b>PC & Memory Optimized!</b>\n\n"
            f"• <b>RAM Reclaimed:</b> <b>+{res['reclaimed_mb']} MB</b> returned to OS\n"
            f"• <b>Zombie Browsers Eliminated:</b> <b>{res['zombies_killed']}</b>\n"
            f"• <b>Processes Set to Low Priority:</b> <b>{res['procs_optimized']}</b>\n"
            f"• <b>Active Memory Trimmed:</b> <b>{res['procs_trimmed']} processes</b>\n\n"
            f"✨ <i>Zero PC lag: Windows will now prioritize your foreground applications 100%.</i>"
        )
        await safe_reply(update.message, msg)
        return

    if t_lower in ["setup", "/setup", "onboarding", "/onboarding", "welcome", "/welcome", "wizard", "/wizard"]:
        text_out, kb = get_onboarding_step_message(1)
        await safe_reply(update.message, text_out, reply_markup=kb)
        return

    elif t_lower in ["imessage", "/imessage", "/sms", "test imessage", "ping imessage"]:
        from agents.imessage_bridge import send_imessage, is_imessage_available, IMESSAGE_TARGET_HANDLE
        res = await asyncio.to_thread(
            send_imessage,
            "🔔 Test Alert from Job Deck Autonomous Cockpit: Your dual-channel iMessage Pager is live and connected! "
            "You will receive instant blue-bubble notifications here for all interview invitations, assessments, and offers.",
            recipient=IMESSAGE_TARGET_HANDLE
        )
        if res.get("success"):
            await safe_reply(
                update.message,
                f"📱 <b>iMessage Notification Dispatched!</b>\n\n"
                f"• <b>Target:</b> <code>{h(IMESSAGE_TARGET_HANDLE)}</code>\n"
                f"• <b>Transport:</b> <code>{h(res.get('method'))}</code>\n\n"
                f"<i>Your dual-channel pager is active. Critical recruiter alerts will ping your iPhone instantly.</i>"
            )
        else:
            await safe_reply(update.message, f"⚠️ <b>iMessage Notice:</b>\n{h(res.get('error', 'Check configuration in .env'))}")
        return

    if t_lower in ["clean", "clear", "/clean", "/clear", "clean chat", "clear chat", "wipe chat", "reset chat", "clean apps", "clear apps"]:
        await clean_all_questions_action(context, update.effective_chat.id, trigger_msg_id=update.message.message_id)
        return
    elif t_lower.startswith("prep:") or t_lower.startswith("/prep") or t_lower.startswith("battlecard:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        from agents import interview_prep
        card = await asyncio.to_thread(interview_prep.generate_interview_battlecard, company=comp, role="Cybersecurity Specialist")
        await safe_reply(update.message, card["telegram_summary"])
        return
    elif t_lower.startswith("radar:") or t_lower.startswith("/radar") or t_lower.startswith("/referrals") or t_lower.startswith("referral:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        from agents import referral_radar
        dossier = await asyncio.to_thread(referral_radar.build_referral_dossier, company=comp, role="Cybersecurity")
        await safe_reply(update.message, dossier["telegram_summary"])
        return
    elif t_lower.startswith("target:"):
        await confirm_targeted_apply(update.message, text.split(":", 1)[1].strip())
    else:
        await reply_with_engine(update, text)


ASSESSMENTS_MSG = (
    "🧠 <b>Assessments are yours to take.</b>\n\n"
    "Job Deck does not complete online assessments for you: employers and assessment platforms forbid it, "
    "and a flagged assessment can cost the offer. Open the assessment email and take it yourself."
)

RUN_WORDS = {"/run", "run", "/deck", "deck", "/daily", "/startdeck", "start", "start applying", "start runner",
             "run workers", "keep applying", "resume applying", "start job deck", "start my job deck", "run job deck"}
STOP_WORDS = {"/stop", "stop", "/pause", "pause", "/halt", "halt", "/nuke", "nuke", "stop applying", "pause runner",
              "stop workers", "stop the runner", "pause applying"}
HELP_TEXT = ("👋 <b>Job Deck</b>\n\n"
             "The pinned panel at the top runs everything:\n"
             "• <b>▶ Run / ⏸ Pause</b> — start or stop applying\n"
             "• <b>📋 Recent · 📈 Stats</b> — what was submitted\n"
             "• <b>⚙️ Settings</b> — workers, pace, autopilot\n"
             "• <b>☰ More</b> — apply to a company, refill queue, screen, resume, recruiter decisions\n\n"
             "You can also type <code>run</code>, <code>pause</code>, <code>status</code>, <code>apply to Visa</code>, "
             "paste a job link, or ask a question.")


def _status_view():
    m = get_realtime_metrics()
    return format_status_message(metrics=m), get_smart_keyboard(m)


VIEW_WORDS = {
    **dict.fromkeys(["status", "update", "/panel", "panel"], _status_view),
    **dict.fromkeys(["/settings", "settings"], get_settings_view),
    **dict.fromkeys(["/more", "more", "/menu", "menu"], get_more_view),
    **dict.fromkeys(["/recent", "recent"], lambda: (recent_text(), CLOSE_KB)),
    **dict.fromkeys(["/stats", "stats", "progress"], lambda: (stats_text(), CLOSE_KB)),
    **dict.fromkeys(["help"], lambda: (HELP_TEXT, None)),
    **dict.fromkeys(["/apply", "apply"], get_target_customizer_panel),  # bare /apply: pick a company
}


async def confirm_targeted_apply(target_msg, query_str: str):
    """A typed or spoken request only previews the job; the application starts when Apply now is tapped."""
    import results_engine as RE
    q = query_str.strip()[:40]  # Telegram callback_data is limited to 64 bytes
    matches = eligible_targets(await asyncio.to_thread(resolve_targeted_company_jobs, q, False))
    if not matches:
        protected = " Protected companies are yours to apply to yourself." if RE.is_protected(q) else ""
        await safe_reply(target_msg, f"🤷 No eligible internship postings for <b>{h(q)}</b> (already applied, in progress, below your fit score, or not an internship).{protected} Nothing was started.")
        return
    top = matches[0]
    note = ""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Apply now", callback_data=f"quick_apply|{q}"),
                                InlineKeyboardButton("✖️ Cancel", callback_data="btn_close")]])
    await safe_reply(target_msg, f"🎯 <b>Apply to this job?</b>\n\n<b>{h(top['company'])}</b> — {h(top['role'])}\n"
                                 f"<i>{len(matches)} eligible posting(s). Nothing starts until you tap Apply now.</i>{note}",
                     reply_markup=kb)


async def reply_with_engine(update: Update, text: str):
    """Natural-language engine reply. A Gemini proposal gets Apply/Discard buttons and is applied only on tap."""
    answer, proposal_id = await asyncio.to_thread(telegram_query_engine.answer_natural_language_query, text)
    if proposal_id:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Apply change", callback_data=f"prop|{proposal_id}|y"),
            InlineKeyboardButton("🗑️ Discard", callback_data=f"prop|{proposal_id}|n"),
        ]])
    else:
        kb = None
    await safe_reply(update.message, answer, reply_markup=kb)


async def handle_answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """'answer <id>: value' saves an answer for exactly that question. Returns True if the message was an answer."""
    t_lower = text.strip().lower()
    if not (t_lower.startswith("answer") or t_lower.startswith("ans ") or t_lower.startswith("ans:")
            or t_lower.startswith("set rule")):
        return False
    parsed = telegram_query_engine.parse_answer_command(text)
    if not parsed:  # bare "answer: x" or "set rule: ..." -> engine explains / handles it
        await reply_with_engine(update, text)
        return True
    res = telegram_query_engine.resolve_pending_question(*parsed)
    if not res.get("ok"):
        await safe_reply(update.message, res.get("msg", "No pending question found."))
        return True
    q_msg_id = res.get("message_id")
    if q_msg_id:
        await safe_delete_message(context.bot, update.effective_chat.id, q_msg_id)
    reply_msg = await safe_reply(
        update.message,
        f"✅ <b>Rule Saved:</b> <code>{h(res['answer'])}</code>\n<b>Field:</b> {h(res.get('question', 'Field'))}\n\n<i>🧹 Deleting confirmation in 4s to keep chat clean...</i>"
    )
    if context.job_queue:
        context.job_queue.run_once(_delayed_delete_job, when=4.0, data={"chat_id": update.effective_chat.id, "message_id": reply_msg.message_id})
        context.job_queue.run_once(_delayed_delete_job, when=4.0, data={"chat_id": update.effective_chat.id, "message_id": update.message.message_id})
    return True


async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    await clean_all_questions_action(context, update.effective_chat.id, trigger_msg_id=update.message.message_id)


async def send_3hour_update(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue scheduled job: executes every 3 hours. Deletes all application messages to prevent chat buildup."""
    try:
        # Clean all application messages accumulated over the 3-hour period
        app_items = telegram_query_engine.clear_all_application_messages()
        deleted_apps = 0
        for mid, cid in app_items:
            target_chat = cid or AUTHORIZED_USER_ID
            if target_chat and mid:
                if await safe_delete_message(context.bot, target_chat, mid):
                    deleted_apps += 1

        # Also sweep any expired question messages
        await sweep_expired_questions_job(context)

        print(f"[3-Hour Scheduled Update] Cleaned {deleted_apps} application messages from chat.", flush=True)

        m = get_realtime_metrics()
        clean_note = f" (Cleaned {deleted_apps} items)" if deleted_apps > 0 else ""
        header = f"🕒 <b>Job Deck Live Control Panel (3-Hour Update)</b><i>{clean_note}</i>"
        # Update the single always-active control panel in-place without duplicating
        await ensure_pinned_live_status(
            context,
            chat_id=AUTHORIZED_USER_ID,
            force_repin=False,
            header=header
        )
    except Exception as e:
        print(f"[3-Hour Update Error] {e}", flush=True)


async def refresh_pinned_status_job(context: ContextTypes.DEFAULT_TYPE):
    """Silently refreshes the pinned live status message so the pinned banner stays real-time."""
    if not AUTHORIZED_USER_ID or time_mod.time() < PANEL_HOLD["until"]:
        return
    try:
        await ensure_pinned_live_status(context, chat_id=AUTHORIZED_USER_ID, force_repin=False)
    except Exception:
        pass


async def poll_outbox_job(context: ContextTypes.DEFAULT_TYPE):
    """Turns what fill.py wrote (unanswered.json, applications.csv) into question prompts and submitted alerts."""
    try:
        await asyncio.to_thread(telegram_notify.process_outbox)
    except Exception as e:
        print(f"[Outbox Poll Error] {e}", flush=True)


async def periodic_pc_optimizer_job(context: ContextTypes.DEFAULT_TYPE):
    """Silently trims unused memory and clears zombie browsers every 5 minutes."""
    try:
        from agents.pc_optimizer import run_full_system_optimization
        await asyncio.to_thread(run_full_system_optimization)
    except Exception as e:
        print(f"[Periodic PC Optimizer] {e}", flush=True)


async def register_telegram_bar_commands(app):
    """Registers the persistent Telegram Command Bar menu so the user can launch & customize jobs from anywhere."""
    from telegram import BotCommand
    commands = [
        BotCommand("status", "Live panel: progress and runner state"),
        BotCommand("run", "Start applying (uses your settings)"),
        BotCommand("stop", "Pause applying"),
        BotCommand("recent", "Latest submitted applications"),
        BotCommand("stats", "Totals, top companies, queue"),
        BotCommand("settings", "Workers, pace, autopilot"),
        BotCommand("apply", "Apply to one company, e.g. /apply Visa"),
        BotCommand("more", "Screen, resume, refill queue, recruiter decisions"),
        BotCommand("help", "What each button does"),
    ]
    try:
        await app.bot.set_my_commands(commands)
        print(f"[Job Deck Control Bot] Telegram Command Bar menu registered ({len(commands)} commands).", flush=True)
    except Exception as e:
        print(f"[Telegram Command Bar Notice] {e}", flush=True)


def main():
    if not BOT_TOKEN or not AUTHORIZED_USER_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    # One bot per token: on 2026-11-11 three old copies were still polling, so taps landed on old code at random
    others = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.pid != os.getpid() and (p.info["name"] or "").lower().startswith("python") and "telegram_bot_service" in " ".join(p.cmdline()):
                others.append(p.pid)
        except psutil.Error:
            pass
    if others:
        print(f"[!] Another Job Deck bot is already running (pid {others}). Stop it first; not starting a second one.", flush=True)
        sys.exit(1)
    print("[Job Deck Control Bot] Initializing two-way AI engine...", flush=True)
    # concurrent_updates: a slow handler (replenish ~15s, Gmail scan, AI reply) must not queue every later tap past Telegram's ~15s answer window
    app = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).post_init(register_telegram_bar_commands).build()
    app.add_error_handler(handle_bot_error)

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["settings", "more", "menu", "recent", "stats", "panel"], handle_text))
    app.add_handler(CommandHandler(["setup", "onboarding", "welcome", "wizard"], cmd_setup))
    app.add_handler(CommandHandler(["status", "update"], cmd_status))
    app.add_handler(CommandHandler(["deck", "daily", "startdeck"], handle_text))
    app.add_handler(CommandHandler(["apply", "target", "run", "stop", "pause"], handle_text))
    app.add_handler(CommandHandler(["queue"], handle_text))
    app.add_handler(CommandHandler(["assessments", "oa"], handle_text))
    app.add_handler(CommandHandler(["pin", "pinned"], handle_text))
    app.add_handler(CommandHandler(["clean", "clear", "clearchat", "cleanapps"], cmd_clean))
    app.add_handler(CommandHandler(["prep", "battlecard"], handle_text))
    app.add_handler(CommandHandler(["radar", "referrals", "referral"], handle_text))
    app.add_handler(CommandHandler(["resume", "cv"], handle_text))
    app.add_handler(CommandHandler(["letter", "cl", "coverletter"], handle_text))
    app.add_handler(CommandHandler(["hud", "ticker"], handle_text))
    app.add_handler(CommandHandler(["view", "snap", "screenshot"], handle_text))
    app.add_handler(CommandHandler(["interview", "mock"], handle_text))
    app.add_handler(CommandHandler(["negotiate", "offer"], handle_text))
    app.add_handler(CommandHandler(["gap", "heatmap"], handle_text))
    app.add_handler(CommandHandler(["turbo"], handle_text))
    app.add_handler(CommandHandler(["stealth"], handle_text))
    app.add_handler(CommandHandler(["nuke", "halt"], handle_text))
    app.add_handler(CommandHandler(["inbox"], handle_text))
    app.add_handler(CommandHandler(["decisions", "advancements", "stages"], handle_text))
    app.add_handler(CommandHandler(["scan_inbox", "check_inbox", "scan"], handle_text))
    app.add_handler(CommandHandler(["optimize", "boost", "cleanram"], handle_text))
    app.add_handler(CommandHandler(["imessage", "sms"], handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Initialize iMessage background webhook listener for incoming commands
    try:
        from agents.imessage_bridge import start_imessage_webhook_listener, is_imessage_available
        if is_imessage_available():
            start_imessage_webhook_listener()
    except Exception as e:
        print(f"[iMessage Listener Notice] {e}", flush=True)

    if app.job_queue:
        app.job_queue.run_repeating(send_3hour_update, interval=3 * 3600, first=3 * 3600)
        app.job_queue.run_repeating(sweep_expired_questions_job, interval=30, first=10)
        app.job_queue.run_repeating(poll_outbox_job, interval=30, first=15)
        app.job_queue.run_daily(send_daily_morning_brief, time=dt_time(hour=8, minute=0, second=0))
        app.job_queue.run_repeating(check_inbox_radar_job, interval=1800, first=60)
        app.job_queue.run_repeating(refresh_pinned_status_job, interval=45, first=2)
        app.job_queue.run_repeating(runner_watchdog_supervisor_job, interval=20, first=5)
        app.job_queue.run_repeating(periodic_pc_optimizer_job, interval=300, first=60)
        print("[Job Deck Control Bot] Autonomous Watchdog Supervisor (20s), PC Optimizer (5m), 3-hour Sweeper, 8:00 AM Brief, Radar, and Pinned Status scheduled.", flush=True)

    print("[Job Deck Control Bot] Two-way polling active. Ready!", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
