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
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv

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

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_STR = os.getenv("TELEGRAM_CHAT_ID", "").strip()
AUTHORIZED_USER_ID = int(CHAT_ID_STR) if CHAT_ID_STR.isdigit() else 0


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

    is_running = metrics["is_running"]
    pending_q = metrics["pending_questions"]
    inbox = metrics["inbox_actions"]

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
    if is_running:
        row2 = [
            InlineKeyboardButton("⚡ Turbo (4 Workers)", callback_data="btn_turbo"),
            InlineKeyboardButton("📋 Recent Apps", callback_data="btn_recent"),
        ]
    else:
        row2 = [
            InlineKeyboardButton("🚀 1-Worker Sweep", callback_data="btn_sweep"),
            InlineKeyboardButton("📋 Recent Apps", callback_data="btn_recent"),
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
    else:
        runner_str = "⚪ <b>IDLE</b> (Ready to start)"

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

    if metrics["recent"]:
        lines.append("\n<b>Recent Submissions:</b>")
        for r in metrics["recent"][-3:]:
            lines.append(f"• <b>{r.get('Company')}</b> — {r.get('Role')}")

    return "\n".join(lines)


def launch_runner(workers=None, queue="queue_cyber_iam.txt"):
    # Clear stale lock files before launching
    for lock in ROOT.glob(".batch_apply*.lock"):
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass

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
        "--no-triage",
        "--resume", "resumes/resume.pdf"
    ]
    subprocess.Popen(cmd, cwd=str(ROOT))


def halt_runner():
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


def replenish_queue_action():
    """Scrapes external job sources and replenishes queue_cyber_iam.txt with fresh roles."""
    import agents.job_sources as js
    import re
    
    jobs = js.fetch(max_age_days=180)
    
    csv_path = ROOT / "applications.csv"
    applied_urls = set()
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            applied_urls = {r.get("Job URL", "").strip().rstrip("/") for r in csv.DictReader(f) if r.get("Job URL")}

    q_path = ROOT / "queue_cyber_iam.txt"
    existing_q = []
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            existing_q = [l.strip() for l in f if l.strip()]
    existing_urls = {p.rstrip("/") for l in existing_q for p in l.split() if p.startswith("http")}

    keywords = re.compile(
        r"security|cyber|iam|identity|cloud|soc|infosec|network|systems|support|infrastructure|devops|threat|vulnerability|incident",
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

    matches = []
    for j in jobs:
        title = (j.get("role") or j.get("title") or "").encode("ascii", "ignore").decode("ascii").strip()
        url = (j.get("url") or "").strip().rstrip("/")
        company = (j.get("company") or "").encode("ascii", "ignore").decode("ascii").strip()
        if keywords.search(title) and not swe_exclude.search(title) and not senior_exclude.search(title) and url and url not in applied_urls and url not in existing_urls:
            matches.append((company, title, url))

    # Sort priority: Greenhouse > Ashby > Workday > Lever > Other
    def sort_prio(item):
        u = item[2].lower()
        if "greenhouse.io" in u: return 0
        if "ashbyhq.com" in u: return 1
        if "myworkdayjobs.com" in u: return 2
        if "lever.co" in u: return 3
        return 4

    matches.sort(key=sort_prio)

    if matches:
        with open(q_path, "a", encoding="utf-8") as f:
            for c, t, u in matches:
                f.write(f"{c} {t}   {u}\n")

    return len(matches)



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
    """Deletes all active question messages and wipes pending questions."""
    msg_ids = telegram_query_engine.clear_all_pending_questions()
    deleted = 0
    for mid in msg_ids:
        if await safe_delete_message(context.bot, chat_id, mid):
            deleted += 1

    # In private chat, also scan backwards up to 35 messages from trigger to catch any untracked question prompts
    if trigger_msg_id:
        for past_id in range(trigger_msg_id - 1, max(1, trigger_msg_id - 35), -1):
            if past_id not in msg_ids:
                if await safe_delete_message(context.bot, chat_id, past_id):
                    deleted += 1

    # Send auto-vanishing confirmation
    confirm = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🧹 <b>Smart Chat Cleanup Complete!</b>\nCleaned <b>{deleted}</b> question prompt(s) and reset pending questions to 0.\n\n<i>Auto-deleting confirmation in 4s...</i>",
        parse_mode=ParseMode.HTML
    )
    if context.job_queue:
        context.job_queue.run_once(
            _delayed_delete_job,
            when=4.0,
            data={"chat_id": chat_id, "message_id": confirm.message_id}
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
        "👋 <b>Welcome to Job Deck Dynamic AI Control!</b>\n\n"
        "• <b>Live Adaptive Buttons:</b> Automatically shift based on active workers and pending tasks.\n"
        "• <b>Conversational AI:</b> Ask anything about your applications, stats, or target companies.\n"
        "• <b>Real-Time Screening:</b> Known facts are auto-resolved silently; novel personal questions appear right here!"
    )
    m = get_realtime_metrics()
    await update.message.reply_text(text, reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)


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

    elif data == "btn_run":
        launch_runner(workers=3)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 3
        await query.message.reply_text("🚀 <b>Launched 3 parallel workers!</b> Auto-applying...", reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)

    elif data == "btn_turbo":
        launch_runner(workers=4)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 4
        await query.message.reply_text("⚡ <b>TURBO MODE ACTIVATED (4 Workers)!</b> Maximum application velocity...", reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)

    elif data == "btn_sweep":
        launch_runner(workers=1)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 1
        await query.message.reply_text("🚀 <b>Single Worker Sweep Launched!</b> Quiet background execution...", reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)

    elif data == "btn_stop":
        stopped = halt_runner()
        m = get_realtime_metrics()
        m["is_running"] = False
        m["worker_count"] = 0
        await query.message.reply_text(f"🛑 <b>Halted {stopped} worker process(es).</b> System idle.", reply_markup=get_smart_keyboard(m), parse_mode=ParseMode.HTML)

    elif data == "btn_recent":
        m = get_realtime_metrics()
        recent = m["recent"]
        if not recent:
            await query.message.reply_text("📋 <b>No submissions found yet.</b>", parse_mode=ParseMode.HTML)
        else:
            lines = ["📋 <b>Latest Verified Submissions:</b>\n"]
            for r in reversed(recent):
                url = r.get("Job URL", "")
                link_html = f'<a href="{url}">{r.get("Company")}</a>' if url else f"<b>{r.get('Company')}</b>"
                lines.append(f"• {link_html} — {r.get('Role')} (<i>{r.get('Date Applied')}</i>)")
            await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
        await query.message.reply_text(stats_msg, parse_mode=ParseMode.HTML)

    elif data == "btn_replenish":
        await query.message.reply_text("⏳ <i>Scanning 2,000+ job sources for fresh Cyber, IAM & Cloud roles...</i>", parse_mode=ParseMode.HTML)
        added = replenish_queue_action()
        m = get_realtime_metrics()
        await query.message.reply_text(
            f"🎯 <b>Queue Replenished!</b>\n\nAdded <b>+{added} fresh roles</b>.\nActive queue now has <b>{m['unapplied_count']} unapplied postings</b>.",
            reply_markup=get_smart_keyboard(m),
            parse_mode=ParseMode.HTML
        )

    elif data == "btn_questions":
        ans = telegram_query_engine.answer_natural_language_query("pending questions")
        await safe_reply(query.message, ans)

    elif data == "btn_alerts":
        m = get_realtime_metrics()
        inbox = m["inbox_actions"]
        if not inbox:
            await query.message.reply_text("✅ <b>No urgent recruiter actions pending!</b>", parse_mode=ParseMode.HTML)
        else:
            msg = "📬 <b>Urgent Recruiter Inbox Items:</b>\n\n" + "\n".join(inbox[:10])
            await safe_reply(query.message, msg)

    elif data == "btn_target":
        await query.message.reply_text(
            "✈️ <b>Targeted Priority Mode:</b>\n\n"
            "To target a specific company or URL immediately, simply reply:\n"
            "<code>target: [Company Name or URL]</code>\n\n"
            "<i>Example:</i> <code>target: Boeing</code> or <code>target: Lockheed Martin</code>",
            parse_mode=ParseMode.HTML
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    text = update.message.text or ""
    t_lower = text.strip().lower()

    # Quick command shortcuts
    if t_lower in ["clean", "/clean", "clear", "/clear", "clearchat", "/clearchat", "clean chat", "clear questions"]:
        await clean_all_questions_action(context, update.effective_chat.id, trigger_msg_id=update.message.message_id)
        return
    elif t_lower in ["status", "/status", "update", "metrics"]:
        m = get_realtime_metrics()
        await safe_reply(update.message, format_status_message(metrics=m), reply_markup=get_smart_keyboard(m))
    elif t_lower in ["run", "apply", "/apply", "start", "begin", "launch", "initiate"]:
        launch_runner(workers=3)
        m = get_realtime_metrics()
        m["is_running"] = True
        m["worker_count"] = 3
        await safe_reply(update.message, "🚀 <b>Started 3 headless workers!</b>", reply_markup=get_smart_keyboard(m))
    elif t_lower in ["stop", "pause", "/stop", "halt", "exit", "quit", "terminate", "end", "close"]:
        stopped = halt_runner()
        m = get_realtime_metrics()
        m["is_running"] = False
        m["worker_count"] = 0
        await safe_reply(update.message, f"🛑 <b>Runner paused ({stopped} stopped).</b>", reply_markup=get_smart_keyboard(m))
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
    """JobQueue scheduled job: executes every 3 hours."""
    try:
        m = get_realtime_metrics()
        msg = format_status_message(header="🕒 <b>3-Hour Scheduled Update</b>", metrics=m)
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=msg,
            reply_markup=get_smart_keyboard(m),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        print(f"[3-Hour Update Error] {e}", flush=True)


def main():
    if not BOT_TOKEN or not AUTHORIZED_USER_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    print("[Job Deck Control Bot] Initializing two-way AI engine...", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["status", "update"], cmd_status))
    app.add_handler(CommandHandler(["clean", "clear", "clearchat"], cmd_clean))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if app.job_queue:
        app.job_queue.run_repeating(send_3hour_update, interval=3 * 3600, first=3 * 3600)
        app.job_queue.run_repeating(sweep_expired_questions_job, interval=30, first=10)
        print("[Job Deck Control Bot] 3-hour JobQueue and 30s Smart Deletion Sweeper scheduled.", flush=True)

    print("[Job Deck Control Bot] Two-way polling active. Ready!", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
