"""
Enterprise Telegram Command & Control Dashboard for Job Deck
Built on python-telegram-bot (v22+) with two-way question/answer capabilities,
interactive dynamic touch buttons that adapt to live process state, real-time metrics,
and JobQueue 3-hour scheduled updates.
"""

import os
import sys
import csv
import json
import glob
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

import telegram_query_engine
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
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_STR = os.getenv("TELEGRAM_CHAT_ID", "").strip()
AUTHORIZED_USER_ID = int(CHAT_ID_STR) if CHAT_ID_STR.isdigit() else 0

PINNED_STATUS_FILE = ROOT / "pinned_status.json"
ACTIVE_HUD_STATE = {"chat_id": None, "message_id": None}


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
    csv_path = ROOT / "applications.csv"
    if not csv_path.exists():
        csv_path = ROOT.parent / "applications.csv"

    total_applied = 0
    today_applied = 0
    today_str = date.today().isoformat()
    recent = []
    companies = {}
    roles_category = {"Cybersecurity": 0, "IAM & Identity": 0, "Cloud & Infra": 0, "Systems Eng": 0, "General Tech": 0}

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
                if "security" in role_l or "cyber" in role_l or "appsec" in role_l:
                    roles_category["Cybersecurity"] += 1
                elif "iam" in role_l or "identity" in role_l or "access" in role_l:
                    roles_category["IAM & Identity"] += 1
                elif "cloud" in role_l or "devops" in role_l or "infra" in role_l:
                    roles_category["Cloud & Infra"] += 1
                elif "systems" in role_l:
                    roles_category["Systems Eng"] += 1
                else:
                    roles_category["General Tech"] += 1
            recent = rows[-5:]

    # Queue Metrics
    queue_count = 0
    unapplied_count = 0
    q_path = ROOT / "queue_cyber_iam.txt"
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            qlines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
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
        for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if ("batch_apply" in cmd or "fill.py" in cmd) and p.info["pid"] != curr_pid:
                active_worker_pids.append(p.info["pid"])
                if p.info.get("memory_info"):
                    total_mem_mb += p.info["memory_info"].rss / (1024 * 1024)
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

    is_running = metrics.get("is_running", False)
    pending_q = metrics.get("pending_questions") or []
    inbox = metrics.get("inbox_actions") or []

    keyboard = []

    # Row 1: Core Lifecycle Controls (Adapts dynamically to runner state)
    if is_running:
        row1 = [
            InlineKeyboardButton("📊 Live Status", callback_data="btn_status"),
            InlineKeyboardButton("🛑 Pause Runner", callback_data="btn_stop"),
        ]
    else:
        row1 = [
            InlineKeyboardButton("📊 Live Status", callback_data="btn_status"),
            InlineKeyboardButton("▶ Run 3 Workers", callback_data="btn_run"),
        ]
    keyboard.append(row1)

    # Row 2: Tactical Application Operations
    turbo_w, _ = calculate_dynamic_turbo_workers()
    if is_running:
        row2 = [
            InlineKeyboardButton(f"⚡ Turbo ({turbo_w} Workers)", callback_data="btn_turbo"),
            InlineKeyboardButton("📋 Recent Apps", callback_data="btn_recent"),
        ]
    else:
        row2 = [
            InlineKeyboardButton(f"⚡ Turbo ({turbo_w} Workers)", callback_data="btn_turbo"),
            InlineKeyboardButton("🚀 1-Worker Sweep", callback_data="btn_sweep"),
        ]
    keyboard.append(row2)

    # Row 3: High Priority User-Interaction (Urgent alerts pushed to front!)
    if len(pending_q) > 0:
        row3 = [
            InlineKeyboardButton(f"⚠️ Answer Questions ({len(pending_q)})", callback_data="btn_questions"),
            InlineKeyboardButton("🧹 Clean Questions", callback_data="btn_clean_questions"),
        ]
    elif len(inbox) > 0:
        row3 = [
            InlineKeyboardButton(f"📬 Recruiter Action ({len(inbox)})", callback_data="btn_alerts"),
            InlineKeyboardButton("🧹 Clean Chat", callback_data="btn_clean_questions"),
        ]
    else:
        row3 = [
            InlineKeyboardButton("🎯 Replenish Queue", callback_data="btn_replenish"),
            InlineKeyboardButton("🧹 Clean Chat", callback_data="btn_clean_questions"),
        ]
    keyboard.append(row3)

    # Row 4: Targeted Operations & Analytics
    row4 = [
        InlineKeyboardButton("✈️ Targeted Priority Run", callback_data="btn_target"),
        InlineKeyboardButton("📈 Stats Breakdown", callback_data="btn_stats"),
    ]
    keyboard.append(row4)

    # Row 5: Quick-View Resume & Live Screen Cam
    row5 = [
        InlineKeyboardButton("📄 Quick Resume", callback_data="btn_resume"),
        InlineKeyboardButton("📸 Screen Cam", callback_data="btn_view"),
    ]
    keyboard.append(row5)

    # Row 6: Live Dynamic HUD & AI Mock Interview
    hud_active = bool(ACTIVE_HUD_STATE.get("message_id"))
    hud_label = "📡 Stop Dynamic HUD" if hud_active else "📡 Live Dynamic HUD"
    row6 = [
        InlineKeyboardButton(hud_label, callback_data="btn_hud"),
        InlineKeyboardButton("🎙️ Mock Interview", callback_data="btn_interview"),
    ]
    keyboard.append(row6)

    # Row 7: Decision Stages & Recruiter Scan
    row7 = [
        InlineKeyboardButton("🎯 Decision Stages", callback_data="btn_decisions"),
        InlineKeyboardButton("📬 Scan Decisions Now", callback_data="btn_scan_inbox"),
    ]
    keyboard.append(row7)

    # Row 8: Pin Live Status & Quick Refresh
    row8 = [
        InlineKeyboardButton("📌 Pin Live Status", callback_data="btn_pin_status"),
        InlineKeyboardButton("🔄 Refresh View", callback_data="btn_status"),
    ]
    keyboard.append(row8)

    # Row 9: PC Optimizer & Resource Boost + Setup Wizard
    row9 = [
        InlineKeyboardButton("🧹 Boost PC", callback_data="btn_optimize_pc"),
        InlineKeyboardButton("🧭 Setup Wizard", callback_data="btn_setup_wizard"),
    ]
    keyboard.append(row9)

    return InlineKeyboardMarkup(keyboard)


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
    if is_running:
        runner_str = f"🟢 <b>RUNNING</b> ({workers} workers active, {mem}MB RAM)"
    elif RUNNER_SUPERVISOR_STATE.get("desired") == "running":
        runner_str = "🟡 <b>RE-IGNITING...</b> (Autonomous Supervisor Active)"
    else:
        runner_str = "⚪ <b>PAUSED</b> (User Paused)"

    now_str = datetime.now().strftime("%I:%M:%S %p")
    lines = [
        f"{header} <i>({now_str})</i>",
        "",
        f"🎯 <b>Milestone Progress:</b> <code>[{bar}]</code> {pct:.1f}%",
        f"• <b>Total Verified:</b> <b>{total}</b> / {target_goal}",
        f"• <b>Submitted Today:</b> <b>+{today}</b> applications",
        "",
        f"⚡ <b>Runner Status:</b> {runner_str}",
    ]

    if metrics["current_target"] and is_running:
        lines.append(f"📍 <b>Active Target:</b> <i>{metrics['current_target']}</i>")

    lines.extend([
        "",
        f"🧠 <b>Memory & Auto-Scale:</b> {metrics.get('avail_gb', 0):.1f}GB free ({metrics.get('mem_pct', 0)}% RAM) ➔ Optimal: <b>{metrics.get('optimal_workers', 3)} workers</b>",
        f"📋 <b>Queue Inventory:</b> {metrics['unapplied_count']} unapplied ({metrics['queue_count']} total in queue)",
    ])

    if len(metrics["pending_questions"]) > 0:
        lines.append(f"⚠️ <b>Action Needed:</b> <b>{len(metrics['pending_questions'])} pending question(s)</b> awaiting input!")
    else:
        lines.append("✅ <b>Form Screening:</b> 100% auto-resolved (0 pending)")

    if len(metrics["inbox_actions"]) > 0:
        lines.append(f"📬 <b>Recruiter Inbox:</b> {len(metrics['inbox_actions'])} urgent recruiter item(s)!")

    try:
        from agents.imessage_bridge import is_imessage_available, IMESSAGE_TARGET_HANDLE
        im_active = is_imessage_available()
        lines.append(f"📱 <b>iMessage Dual-Channel Pager:</b> {'🟢 Connected' if im_active else '⚪ Inactive'} <code>({IMESSAGE_TARGET_HANDLE})</code>")
    except Exception:
        pass

    if metrics["recent"]:
        lines.append("\n<b>Recent Submissions:</b>")
        for r in metrics["recent"][-3:]:
            lines.append(f"• <b>{r.get('Company')}</b> — {r.get('Role')}")

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
            "• <b>Candidate:</b> Michael Azuka\n"
            "• <b>Education:</b> B.S. Cybersecurity, Kennesaw State University (Dec 2026)\n"
            "• <b>GPA:</b> 3.35 | Accepted to M.S. Cybersecurity\n"
            "• <b>Certifications:</b> CompTIA Security+, NSF BPC AI & ML Certificate\n"
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
            "Job Deck bridges directly to Apple iMessage on your phone (<code>+14046450373</code>)!\n\n"
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

    return text, kb


RUNNER_SUPERVISOR_STATE = {
    "desired": "running",
    "workers": 3,
    "delay": 2.0,
    "queue": "queue_cyber_iam.txt",
    "last_relaunch": 0.0,
    "auto_restarts": 0,
}


def launch_runner(workers=None, queue="queue_cyber_iam.txt", delay=2.0, user_action=True):
    global RUNNER_SUPERVISOR_STATE
    if user_action:
        RUNNER_SUPERVISOR_STATE["desired"] = "running"
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

    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(ROOT / "batch_apply_parallel.py"),
        "--queue", queue,
        "--workers", str(target_w),
        "--adaptive",
        "--continuous",
        "--no-triage",
        "--use-tailored",
        "--resume", "resumes/Candidate_Resume.pdf",
        "--delay", str(delay)
    ]
    log_file = open(ROOT / "batch_apply.log", "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags)


def halt_runner():
    global RUNNER_SUPERVISOR_STATE
    RUNNER_SUPERVISOR_STATE["desired"] = "paused"
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
    if RUNNER_SUPERVISOR_STATE.get("desired") != "running":
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

    # Replenish if queue inventory is low
    if m.get("unapplied_count", 0) < 25:
        try:
            added = await asyncio.to_thread(replenish_queue_action)
            print(f"[Supervisor Watchdog] Auto-replenished +{added} fresh target roles.", flush=True)
        except Exception as e:
            print(f"[Supervisor Watchdog] Auto-replenish error: {e}", flush=True)

    w = RUNNER_SUPERVISOR_STATE.get("workers", 3)
    d = RUNNER_SUPERVISOR_STATE.get("delay", 2.0)
    q = RUNNER_SUPERVISOR_STATE.get("queue", "queue_cyber_iam.txt")
    launch_runner(workers=w, queue=q, delay=d, user_action=False)


def replenish_queue_action() -> int:
    """Harvests and replenishes queue_cyber_iam.txt with fresh, highly-targeted unapplied roles."""
    import agents.job_sources as js
    import re
    import results_engine as RE

    kw = re.compile(
        r"security|cyber|iam|identity|cloud|soc|infosec|network|systems|support|infrastructure|devops|threat|vulnerability|incident|compliance|it\s+support|desktop|sysadmin|analyst",
        re.I
    )
    swe_exclude = re.compile(
        r"\b(software\s+(engineer|developer|dev)|full\s*stack|backend|frontend|mobile\s+dev|ios\s+dev|android\s+dev|ml\s+engineer|machine\s+learning|algorithm|compiler|firmware|embedded\s+software|c\+\+\s+dev|java\s+dev|python\s+dev|react\s+dev|programmer|sde\b|swe\b)\b",
        re.I
    )
    senior_exclude = re.compile(
        r"\b(director|vp\b|vice\s+president|head\s+of|manager|principal|staff\+)\b",
        re.I
    )

    applied_urls = set()
    applied_pairs = set()

    csv_path = ROOT / "applications.csv"
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

    q_path = ROOT / "queue_cyber_iam.txt"
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
        # Greenhouse canonical embed format
        m_gh = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/&?]+)(?:/jobs/|.*[&?]token=)(\d+)", u_norm)
        if m_gh:
            u_norm = f"https://job-boards.greenhouse.io/embed/job_app?for={m_gh.group(1)}&token={m_gh.group(2)}"
            if u_norm in seen or u_norm in existing_urls or u_norm in applied_urls:
                return

        seen.add(u_norm)
        collected.append((comp.strip(), role.strip(), u_norm))

    # 1. Pull from existing large master queues
    for qf in ["queue.txt", "queue_ranked.txt", "queue_phase2.txt"]:
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

    # Sort priority: Greenhouse > Ashby > Workday > Lever > Other
    def sort_prio(item):
        u = item[2].lower()
        if "greenhouse.io" in u:
            return 0
        if "ashbyhq.com" in u:
            return 1
        if "myworkdayjobs.com" in u:
            return 2
        if "lever.co" in u:
            return 3
        return 4

    collected.sort(key=sort_prio)

    if collected:
        with open(q_path, "a", encoding="utf-8") as f:
            for c, r, u in collected:
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
    text = (
        "👋 <b>Welcome to Job Deck Autonomous Headquarters!</b>\n\n"
        "🧭 <b>New User Setup:</b>\n"
        "• <code>/setup</code> or tap <b>[🧭 Setup Wizard]</b> below for an interactive 6-step walkthrough!\n\n"
        "⚡ <b>Autonomous Speed & Workers:</b>\n"
        "• <code>/apply</code> or <code>run</code> — Launch 3 workers with auto-scaling\n"
        "• <code>/turbo</code> — Max velocity (4 workers, fast 1.0s delay)\n"
        "• <code>/stealth</code> — Ultra-stealth human emulation (8s jitter)\n"
        "• <code>/stop</code> or <code>/nuke</code> — Immediate pause / emergency kill\n\n"
        "📄 <b>Tailored Documents & Screen Cam:</b>\n"
        "• <code>/resume [Company]</code> — Quick-view tailored resume (photo preview, no download!)\n"
        "• <code>/letter [Company]</code> — Quick-view tailored cover letter\n"
        "• <code>/view</code> or <code>/snap</code> — Live screenshot of active browser window\n"
        "• <code>/hud</code> or <code>/ticker</code> — Single-message live dynamic ticker\n"
        "• <code>/pin</code> — Pin the live status control panel to top banner\n\n"
        "🎯 <b>Auto-Apply & Radar:</b>\n"
        "• Paste any job URL directly — Auto-applies on the spot\n"
        "• <code>/inbox</code> — Urgent recruiter replies & interview alerts\n"
        "• <code>/gap [Company]</code> — ATS keyword heatmap & missing skills\n"
        "• <code>/prep [Company]</code> — Complete Interview Battlecard\n"
        "• <code>/radar [Company]</code> — Recruiter & warm referral dossiers\n\n"
        "🎙️ <b>AI Mock Interview & Negotiation:</b>\n"
        "• <code>/interview [Company]</code> — Interactive technical mock interview (Voice or Text!)\n"
        "• <code>/negotiate [Details]</code> — Market salary counter-offer packages\n"
        "• 🗣️ <i>Send any voice memo to execute commands hands-free!</i>"
    )
    m = get_realtime_metrics()
    await update.message.reply_text(text, reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    text_out, kb = get_onboarding_step_message(1)
    await update.message.reply_text(text_out, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    m = get_realtime_metrics()
    await update.message.reply_text(format_status_message(metrics=m), reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != AUTHORIZED_USER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return

    data = query.data
    await query.answer()

    # 1. Answer button tapped: ans_{q_id}_{option}
    if data.startswith("ans_"):
        parts = data.split("_", 2)
        if len(parts) >= 3:
            q_id = f"{parts[0]}_{parts[1]}"
            selected_answer = parts[2]
            res = telegram_query_engine.resolve_pending_question(q_id, selected_answer)
            telegram_query_engine.mark_question_deleted_or_resolved(message_id=query.message.message_id, q_id=q_id)

            clean_q = res.get("question", "Field")
            confirm_text = (
                f"✅ <b>Answer Recorded:</b> <code>{selected_answer}</code>\n"
                f"<b>Field:</b> {clean_q}\n\n"
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
            else:
                import asyncio
                async def _del():
                    await asyncio.sleep(4)
                    await safe_delete_message(context.bot, query.message.chat_id, query.message.message_id)
                asyncio.create_task(_del())
            return

    elif data == "btn_clean_questions":
        await clean_all_questions_action(context, query.message.chat_id, trigger_msg_id=query.message.message_id)
        m = get_realtime_metrics()
        await safe_edit(query, format_status_message(metrics=m), reply_markup=get_smart_keyboard(m))
        return

    # 2. Control panel buttons
    if data == "btn_status":
        m = get_realtime_metrics()
        await safe_edit(query, format_status_message(metrics=m), reply_markup=get_smart_keyboard(m))

    elif data == "btn_setup_wizard" or data == "onboard:step:1":
        text_out, kb = get_onboarding_step_message(1)
        await safe_edit(query, text_out, reply_markup=kb)

    elif data.startswith("onboard:step:"):
        try:
            step_num = int(data.split(":")[-1])
        except Exception:
            step_num = 1
        text_out, kb = get_onboarding_step_message(step_num)
        await safe_edit(query, text_out, reply_markup=kb)

    elif data == "onboard:launch":
        launch_runner(workers=3)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 3
        await safe_edit(query, format_status_message(header="🚀 <b>Setup Complete! 3 Parallel Workers Launched!</b>", metrics=m), reply_markup=get_smart_keyboard(m))
        await query.answer("🚀 Setup Complete! 3 parallel workers active!", show_alert=True)

    elif data == "btn_run":
        launch_runner(workers=3)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 3
        await safe_edit(query, format_status_message(header="🚀 <b>Launched 3 Parallel Workers! Auto-Applying...</b>", metrics=m), reply_markup=get_smart_keyboard(m))
        await query.answer("🚀 3 parallel workers active!", show_alert=False)

    elif data == "btn_turbo":
        turbo_w, desc = calculate_dynamic_turbo_workers()
        launch_runner(workers=turbo_w, delay=1.0)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = turbo_w
        await safe_edit(query, format_status_message(header=f"⚡ <b>TURBO VELOCITY ACTIVE ({turbo_w} Workers)!</b>", metrics=m), reply_markup=get_smart_keyboard(m))
        await query.answer(f"⚡ Turbo: {desc}", show_alert=True)

    elif data == "btn_sweep":
        launch_runner(workers=1, delay=3.0)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 1
        await safe_edit(query, format_status_message(header="🚀 <b>Single Worker Sweep Launched!</b>", metrics=m), reply_markup=get_smart_keyboard(m))
        await query.answer("🚀 1-Worker Sweep active!", show_alert=False)

    elif data == "btn_stop":
        stopped = halt_runner()
        m = get_realtime_metrics()
        m["is_running"] = False
        m["worker_count"] = 0
        await safe_edit(query, format_status_message(header=f"🛑 <b>Runner Paused ({stopped} halted).</b> System idle.", metrics=m), reply_markup=get_smart_keyboard(m))
        await query.answer(f"🛑 Halted {stopped} worker process(es)", show_alert=False)

    elif data == "btn_recent":
        m = get_realtime_metrics()
        recent = m["recent"]
        if not recent:
            lines = ["📋 <b>Latest Verified Submissions:</b>\n\n<i>No submissions recorded yet today.</i>"]
        else:
            lines = ["📋 <b>Latest Verified Submissions:</b>\n"]
            for r in reversed(recent):
                url = r.get("Job URL", "")
                link_html = f'<a href="{url}">{r.get("Company")}</a>' if url else f"<b>{r.get('Company')}</b>"
                lines.append(f"• {link_html} — {r.get('Role')} (<i>{r.get('Date Applied')}</i>)")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]])
        await safe_edit(query, "\n".join(lines), reply_markup=kb)

    elif data == "btn_stats":
        m = get_realtime_metrics()
        top_co = sorted(m["companies"].items(), key=lambda x: -x[1])[:5]
        top_str = "\n".join(f"  • {c}: {count} applied" for c, count in top_co) if top_co else "  • No data yet"
        cats = m["roles_category"]
        cats_str = "\n".join(f"  • {k}: {v}" for k, v in cats.items())

        stats_msg = (
            "📈 <b>Comprehensive Portfolio Analytics</b>\n\n"
            f"🎯 <b>Total Verified Applications:</b> {m['total_applied']} / 3000\n"
            f"📅 <b>Applied Today:</b> +{m['today_applied']}\n"
            f"📋 <b>Active Queue Inventory:</b> {m['unapplied_count']} unapplied ({m['queue_count']} total)\n\n"
            f"🏢 <b>Top Companies Applied:</b>\n{top_str}\n\n"
            f"🛡️ <b>Specialization Breakdown:</b>\n{cats_str}\n\n"
            f"⚡ <b>Runner Hardware:</b> {m['worker_count']} workers active ({m['total_mem_mb']}MB RSS)"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]])
        await safe_edit(query, stats_msg, reply_markup=kb)

    elif data == "btn_replenish":
        await safe_edit(query, "⏳ <i>Scanning 2,000+ job sources for fresh Cyber, IAM & Cloud roles...</i>")
        added = await asyncio.to_thread(replenish_queue_action)
        m = get_realtime_metrics()
        await safe_edit(
            query,
            format_status_message(header=f"🎯 <b>Queue Replenished (+{added} fresh roles)!</b>", metrics=m),
            reply_markup=get_smart_keyboard(m)
        )

    elif data == "btn_questions":
        ans = telegram_query_engine.answer_natural_language_query("pending questions")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]])
        await safe_edit(query, ans, reply_markup=kb)

    elif data == "btn_alerts":
        m = get_realtime_metrics()
        inbox = m["inbox_actions"]
        msg = ("📬 <b>Urgent Recruiter Inbox Items:</b>\n\n" + "\n".join(inbox[:10])) if inbox else "✅ <b>No urgent recruiter actions pending!</b>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]])
        await safe_edit(query, msg, reply_markup=kb)

    elif data == "btn_target":
        target_text = (
            "✈️ <b>Targeted Priority Mode:</b>\n\n"
            "To target a specific company or URL immediately, simply reply in chat:\n"
            "<code>target: [Company Name or URL]</code>\n\n"
            "<i>Example:</i> <code>target: Boeing</code> or <code>target: Lockheed Martin</code>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]])
        await safe_edit(query, target_text, reply_markup=kb)

    elif data == "btn_resume":
        await send_quickview_doc(query.message, context, is_letter=False)

    elif data == "btn_view":
        await send_screen_cam(query.message, context)

    elif data == "btn_hud":
        await handle_live_hud(query.message, context)
        m = get_realtime_metrics()
        await safe_edit(query, format_status_message(metrics=m), reply_markup=get_smart_keyboard(m))

    elif data == "btn_interview":
        session_text = start_interview_session(query.message.chat_id, "Target Employer", "Cybersecurity Specialist")
        sent = await safe_reply(query.message, session_text)
        if sent:
            telegram_query_engine.save_application_message(sent.message_id, query.message.chat_id)

    elif data == "btn_decisions":
        summary = get_decision_pipeline_summary()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 Scan Decisions Now", callback_data="btn_scan_inbox")],
            [InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]
        ])
        await safe_edit(query, summary, reply_markup=kb)

    elif data == "btn_scan_inbox":
        await safe_edit(query, "⏳ <i>Scanning Gmail for decision emails, stage advancements & deadlines...</i>")
        new_advs = await asyncio.to_thread(scan_and_track_decision_emails, 30)
        if new_advs:
            for adv in new_advs:
                comp = adv.get("company", "Target")
                kb_rows = []
                if adv.get("email_link"):
                    kb_rows.append([InlineKeyboardButton("📬 Open Email in Gmail", url=adv["email_link"])])
                kb_rows.append([
                    InlineKeyboardButton("⚔️ Prep Battlecard", callback_data=f"prep:{comp}"),
                    InlineKeyboardButton("📄 Quick Resume", callback_data="btn_resume"),
                ])
                adv_kb = InlineKeyboardMarkup(kb_rows)
                alert_msg = await query.message.reply_text(format_advancement_telegram_alert(adv), reply_markup=adv_kb, parse_mode=ParseMode.HTML)
                telegram_query_engine.save_application_message(alert_msg.message_id, query.message.chat_id)
        summary = get_decision_pipeline_summary()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 Scan Decisions Again", callback_data="btn_scan_inbox")],
            [InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]
        ])
        await safe_edit(query, summary, reply_markup=kb)

    elif data == "btn_optimize_pc":
        await query.answer("🧹 Optimizing PC memory & priority...", show_alert=False)
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
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 Boost Again", callback_data="btn_optimize_pc")],
            [InlineKeyboardButton("⬅️ Back to Controls", callback_data="btn_status")]
        ])
        await safe_edit(query, msg, reply_markup=kb)

    elif data == "btn_pin_status":
        pinned_id = await ensure_pinned_live_status(context, chat_id=query.message.chat_id, force_repin=True)
        await query.answer("📌 Live status pinned to top banner!", show_alert=False)
        m = get_realtime_metrics()
        await safe_edit(
            query,
            format_status_message(header="📌 <b>Live Status View (Pinned at Top Banner)</b>", metrics=m),
            reply_markup=get_smart_keyboard(m)
        )

    elif data.startswith("dl_pdf:"):
        pdf_path_str = data.split(":", 1)[1]
        pdf_p = Path(pdf_path_str)
        if pdf_p.exists():
            with open(pdf_p, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    caption=f"📄 <b>Document:</b> <code>{pdf_p.name}</code>",
                    parse_mode=ParseMode.HTML
                )
        else:
            await query.message.reply_text("❌ PDF file not found on disk.")


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
            f"📄 <b>Quick-View {doc_type}:</b> <code>{co_display}</code>\n"
            f"🎯 <i>Tap photo above to view full-screen without downloading!</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download PDF File", callback_data=f"dl_pdf:{pdf_path}")]
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
                caption=f"📄 <b>{doc_type}</b> ({pdf_path.name})",
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
            f"📍 <b>Active Target:</b> <i>{m.get('current_target') or 'None'}</i>\n\n"
            f"<i>Tap [🚀 Launch 3 Workers] below to start active browser automation!</i>"
        )
        sent = await safe_reply(target_msg, status_text, reply_markup=get_smart_keyboard(m))
        if sent:
            telegram_query_engine.save_application_message(sent.message_id, target_msg.chat_id)
        return
    img_bytes, caption = snap
    sent = await target_msg.reply_photo(
        photo=img_bytes,
        caption=f"{caption}\n<i>⚡ Live view from active Playwright worker</i>",
        reply_markup=get_smart_keyboard(m),
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
                text="📡 <b>[AJ Dynamic HUD — Turned OFF]</b>\n\n<i>Live dynamic ticker paused. Tap [📡 Live Dynamic HUD] below or text /hud to restart anytime.</i>",
                reply_markup=get_smart_keyboard(m),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        await safe_reply(target_msg, "📡 <b>Dynamic HUD Ticker Turned OFF.</b>", reply_markup=get_smart_keyboard(m))
        return

    # If HUD is NOT active -> TOGGLE ON
    m = get_realtime_metrics()
    now_str = datetime.now().strftime("%I:%M:%S %p")
    target_str = f"📍 <b>Target:</b> <i>{m['current_target']}</i>\n" if m.get("current_target") else ""
    hud_text = (
        f"📡 <b>[AJ Dynamic HUD — Live Ticker ACTIVE]</b> <i>({now_str})</i>\n\n"
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
                text="📡 <b>[AJ Dynamic HUD — Auto-Paused]</b>\n\n<i>Live ticker paused after 3 minutes of active telemetry. Tap button below to resume anytime!</i>",
                reply_markup=get_smart_keyboard(m),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    m = get_realtime_metrics()
    now_str = datetime.now().strftime("%I:%M:%S %p")
    target_str = f"📍 <b>Target:</b> <i>{m['current_target']}</i>\n" if m.get("current_target") else ""

    hud_text = (
        f"📡 <b>[AJ Dynamic HUD — Live Ticker ACTIVE]</b> <i>({now_str})</i>\n\n"
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

    await safe_reply(
        target_msg,
        f"🎯 <b>Auto-Apply Triggered!</b>\n"
        f"<b>Employer:</b> {comp_name}\n"
        f"<b>URL:</b> <code>{canonical_url}</code>\n\n"
        f"⚡ <i>Launching isolated priority worker in headless mode...</i>"
    )

    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(ROOT / "fill.py"),
        canonical_url,
        "--headless",
        "--company", comp_name,
        "--resume", "resumes/Candidate_Resume.pdf"
    ]
    subprocess.Popen(cmd, cwd=str(ROOT))


async def send_daily_morning_brief(context: ContextTypes.DEFAULT_TYPE):
    """Delivers an executive morning brief at 8:00 AM daily."""
    m = get_realtime_metrics()
    today_applied = m["today_applied"]
    total = m["total_applied"]
    unapplied = m["unapplied_count"]
    now_str = datetime.now().strftime("%A, %B %d, %Y")

    brief = (
        f"🌅 <b>GOOD MORNING MICHAEL — EXECUTIVE BRIEFING</b>\n"
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
            reply_markup=get_smart_keyboard(m),
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
                f"{urgent_items}\n\n"
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
            f"🗣️ <b>Voice Command Heard:</b> <i>\"{transcribed_text}\"</i>",
            parse_mode=ParseMode.HTML
        )
        update.message.text = transcribed_text
        await handle_text(update, context)
    except Exception as e:
        await safe_reply(update.message, f"⚠️ Voice memo error: {e}")


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

    # Priority 1: Instant URL Drop & Auto-Apply
    if text.startswith("http://") or text.startswith("https://") or t_lower.startswith("/add") or t_lower.startswith("add:"):
        url = text.split(":", 1)[1].strip() if (t_lower.startswith("add:") or t_lower.startswith("/add")) else text.strip()
        await handle_url_drop(url, update.message, context)
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
        m = get_realtime_metrics()
        await safe_reply(
            update.message,
            "📌 <b>Live Status View has been pinned to the top of your chat banner!</b>\n\n"
            f"• <b>Total Verified:</b> <b>{m['total_applied']} / 3000</b> | <b>Today:</b> +{m['today_applied']}\n"
            f"• <b>Runner Status:</b> {'🟢 Running' if m['is_running'] else '⚪ Idle'}\n\n"
            "<i>The banner at the top of your chat updates continuously and keeps your full controls one tap away at all times.</i>",
            reply_markup=get_smart_keyboard(m)
        )
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
        strat = analyze_offer_and_strategize(comp, amount, loc)
        await safe_reply(update.message, strat["telegram_summary"])
        return

    # Priority 7: ATS Keyword Gap & Resume Heatmap
    elif t_lower.startswith("/gap") or t_lower.startswith("gap:") or t_lower.startswith("/heatmap") or t_lower.startswith("heatmap:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        gap_res = analyze_ats_gap(comp, "Cybersecurity Specialist")
        await safe_reply(update.message, gap_res["telegram_summary"])
        return

    # Priority 8: Speed Shifters (Turbo / Stealth / Nuke)
    elif t_lower in ["/turbo", "turbo"]:
        turbo_w, desc = calculate_dynamic_turbo_workers()
        launch_runner(workers=turbo_w, delay=1.0)
        m = get_realtime_metrics()
        await safe_reply(
            update.message,
            f"⚡ <b>TURBO VELOCITY ACTIVATED ({turbo_w} Workers)!</b>\n\n"
            f"• <b>Auto-Tuned:</b> <i>{desc}</i>\n"
            f"• <b>Fast-Fill Delay:</b> <code>1.0s</code> (Accelerated)\n\n"
            f"<i>Headless browser workers running at peak machine velocity!</i>",
            reply_markup=get_smart_keyboard(m)
        )
        return
    elif t_lower in ["/stealth", "stealth"]:
        launch_runner(workers=1, delay=8.0)
        m = get_realtime_metrics()
        await safe_reply(update.message, "🕵️ <b>STEALTH MODE ACTIVATED!</b> Launched 1 worker with human jitter (8s delay).", reply_markup=get_smart_keyboard(m))
        return
    elif t_lower in ["/nuke", "nuke", "/halt", "halt"]:
        stopped = halt_runner()
        m = get_realtime_metrics()
        await safe_reply(update.message, f"💥 <b>SYSTEM NUKED!</b> Halted {stopped} worker process(es) and purged lock files.", reply_markup=get_smart_keyboard(m))
        return

    # Priority 9: Recruiter Inbox Radar
    elif t_lower in ["/inbox", "inbox"]:
        m = get_realtime_metrics()
        inbox = m.get("inbox_actions", [])
        if not inbox:
            await safe_reply(update.message, "✅ <b>No urgent recruiter actions pending in your inbox!</b>")
        else:
            await safe_reply(update.message, "📬 <b>Urgent Recruiter Inbox Items:</b>\n\n" + "\n".join(f"• {item}" for item in inbox[:10]))
        return

    # Priority 10: Decision Tracking & Stage Advancements
    elif t_lower in ["/decisions", "decisions", "/advancements", "advancements", "/stages", "stages"]:
        summary = get_decision_pipeline_summary()
        await safe_reply(update.message, summary)
        return
    elif t_lower in ["/scan_inbox", "scan_inbox", "/check_inbox", "check_inbox", "/scan"]:
        await safe_reply(update.message, "⏳ <i>Scanning Gmail for decision emails and stage advancements...</i>")
        new_advs = scan_and_track_decision_emails(days_back=30)
        if new_advs:
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
                await safe_reply(update.message, msg, reply_markup=InlineKeyboardMarkup(kb_rows))
        summary = get_decision_pipeline_summary()
        await safe_reply(update.message, summary)
        return
    elif any(k in t_lower for k in ["optimize", "/optimize", "boost", "clean ram", "optimize pc", "free ram", "boost pc", "lag", "speed up"]):
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

    if any(k in t_lower for k in ["setup", "/setup", "onboarding", "/onboarding", "welcome", "/welcome", "wizard"]):
        text_out, kb = get_onboarding_step_message(1)
        await safe_reply(update.message, text_out, reply_markup=kb)
        return

    elif any(k in t_lower for k in ["imessage", "/imessage", "test imessage", "ping imessage"]):
        from agents.imessage_bridge import send_imessage, is_imessage_available, IMESSAGE_TARGET_HANDLE
        res = send_imessage(
            "🔔 Test Alert from Job Deck Autonomous Cockpit: Your dual-channel iMessage Pager is live and connected! "
            "You will receive instant blue-bubble notifications here for all interview invitations, assessments, and offers.",
            recipient=IMESSAGE_TARGET_HANDLE
        )
        if res.get("success"):
            await safe_reply(
                update.message,
                f"📱 <b>iMessage Notification Dispatched!</b>\n\n"
                f"• <b>Target:</b> <code>{IMESSAGE_TARGET_HANDLE}</code>\n"
                f"• <b>Transport:</b> <code>{res.get('method')}</code>\n\n"
                f"<i>Your dual-channel pager is active. Critical recruiter alerts will ping your iPhone instantly.</i>"
            )
        else:
            await safe_reply(update.message, f"⚠️ <b>iMessage Notice:</b>\n{res.get('error', 'Check configuration in .env')}")
        return

    if any(k in t_lower for k in ["clean", "clear", "clearchat", "clean chat", "clear chat", "wipe chat", "reset chat", "clean apps", "clear apps"]) or t_lower in ["/clean", "/clear"]:
        await clean_all_questions_action(context, update.effective_chat.id, trigger_msg_id=update.message.message_id)
        return
    elif any(k in t_lower for k in ["status", "update", "metrics", "dashboard", "how are things", "how is it going", "how are we doing", "progress", "stats", "give me an update"]) or t_lower in ["/status", "/update"]:
        m = get_realtime_metrics()
        await safe_reply(update.message, format_status_message(metrics=m), reply_markup=get_smart_keyboard(m))
    elif any(k in t_lower for k in ["start applying", "start runner", "start workers", "launch workers", "keep applying", "run workers", "start", "begin", "launch", "apply", "run"]) or t_lower in ["/run", "/apply", "/start"]:
        launch_runner(workers=3)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 3
        await safe_reply(update.message, "🚀 <b>Started 3 headless workers!</b>", reply_markup=get_smart_keyboard(m))
    elif any(k in t_lower for k in ["stop applying", "pause runner", "stop workers", "halt workers", "pause", "halt", "freeze", "stop", "terminate", "end", "close"]) or t_lower in ["/stop", "/pause", "/halt"]:
        stopped = halt_runner()
        m = get_realtime_metrics()
        m["is_running"] = False
        m["worker_count"] = 0
        await safe_reply(update.message, f"🛑 <b>Runner paused ({stopped} stopped).</b>", reply_markup=get_smart_keyboard(m))
    elif t_lower.startswith("prep:") or t_lower.startswith("/prep") or t_lower.startswith("battlecard:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        from agents import interview_prep
        card = interview_prep.generate_interview_battlecard(company=comp, role="Cybersecurity Specialist")
        await safe_reply(update.message, card["telegram_summary"])
        return
    elif t_lower.startswith("radar:") or t_lower.startswith("/radar") or t_lower.startswith("/referrals") or t_lower.startswith("referral:"):
        parts = text.split(":", 1) if ":" in text else text.split(maxsplit=1)
        comp = parts[1].strip() if len(parts) > 1 else "Target Employer"
        from agents import referral_radar
        dossier = referral_radar.build_referral_dossier(company=comp, role="Cybersecurity")
        await safe_reply(update.message, dossier["telegram_summary"])
        return
    elif t_lower.startswith("target:"):
        target_query = text.split(":", 1)[1].strip()
        launch_runner(workers=1, queue="queue_cyber_iam.txt")
        await safe_reply(update.message, f"🎯 <b>Targeting '{target_query}'!</b> Worker launched in priority mode.")
    elif t_lower.startswith("answer:") or t_lower.startswith("ans:") or t_lower in ["yes", "no", "i agree"]:
        ans_val = text.split(":", 1)[1].strip() if ":" in text else text.strip()
        res = telegram_query_engine.resolve_pending_question("latest", ans_val)
        if res.get("ok"):
            q_msg_id = res.get("message_id")
            if q_msg_id:
                await safe_delete_message(context.bot, update.effective_chat.id, q_msg_id)

            clean_q = res.get("question", "Field")
            reply_msg = await safe_reply(
                update.message,
                f"✅ <b>Rule Saved:</b> <code>{res['answer']}</code>\n<b>Field:</b> {clean_q}\n\n<i>🧹 Deleting confirmation in 4s to keep chat clean...</i>"
            )
            if context.job_queue:
                context.job_queue.run_once(_delayed_delete_job, when=4.0, data={"chat_id": update.effective_chat.id, "message_id": reply_msg.message_id})
                context.job_queue.run_once(_delayed_delete_job, when=4.0, data={"chat_id": update.effective_chat.id, "message_id": update.message.message_id})
            return
        else:
            await safe_reply(update.message, res.get("msg", "No pending question found."))
            return
    else:
        # Route through natural language query & rule answering engine
        answer = telegram_query_engine.answer_natural_language_query(text)
        m = get_realtime_metrics()
        await safe_reply(update.message, answer, reply_markup=get_smart_keyboard(m))


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
        clean_note = f"\n\n🧹 <i>Cleaned {deleted_apps} application updates from chat to prevent message buildup.</i>" if deleted_apps > 0 else ""
        msg = format_status_message(header="🕒 <b>3-Hour Scheduled Update</b>", metrics=m) + clean_note
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=msg,
            reply_markup=get_smart_keyboard(m),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        print(f"[3-Hour Update Error] {e}", flush=True)


async def refresh_pinned_status_job(context: ContextTypes.DEFAULT_TYPE):
    """Silently refreshes the pinned live status message so the pinned banner stays real-time."""
    if not AUTHORIZED_USER_ID:
        return
    try:
        await ensure_pinned_live_status(context, chat_id=AUTHORIZED_USER_ID, force_repin=False)
    except Exception:
        pass


async def periodic_pc_optimizer_job(context: ContextTypes.DEFAULT_TYPE):
    """Silently trims unused memory and clears zombie browsers every 5 minutes."""
    try:
        from agents.pc_optimizer import run_full_system_optimization
        await asyncio.to_thread(run_full_system_optimization)
    except Exception as e:
        print(f"[Periodic PC Optimizer] {e}", flush=True)


def main():
    if not BOT_TOKEN or not AUTHORIZED_USER_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    print("[Job Deck Control Bot] Initializing two-way AI engine...", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["setup", "onboarding", "welcome", "wizard"], cmd_setup))
    app.add_handler(CommandHandler(["status", "update"], cmd_status))
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
