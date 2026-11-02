"""
Enterprise Telegram Command & Control Dashboard for Job Deck
Built on python-telegram-bot (v22+) with native asyncio, interactive inline buttons,
JobQueue 3-hour scheduled updates, and immediate sub-second command responses.
"""

import os
import sys
import csv
import subprocess
from datetime import datetime
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

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_STR = os.getenv("TELEGRAM_CHAT_ID", "").strip()
AUTHORIZED_USER_ID = int(CHAT_ID_STR) if CHAT_ID_STR.isdigit() else 0


def get_keyboard():
    """Generates the interactive touch buttons for Telegram."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Live Status", callback_data="btn_status"),
            InlineKeyboardButton("▶ Run 3 Workers", callback_data="btn_run"),
        ],
        [
            InlineKeyboardButton("✈ Apply Boeing", callback_data="btn_boeing"),
            InlineKeyboardButton("🛑 Pause Runner", callback_data="btn_stop"),
        ],
        [
            InlineKeyboardButton("📂 Queue Count", callback_data="btn_queue"),
            InlineKeyboardButton("🔄 Refresh Obsidian", callback_data="btn_obsidian"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_current_stats_fast():
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

    queue_count = 0
    q_path = ROOT / "queue_cyber_iam.txt"
    if q_path.exists():
        with open(q_path, "r", encoding="utf-8", errors="ignore") as f:
            queue_count = len([l for l in f if l.strip() and not l.startswith("#")])

    curr_pid = os.getpid()
    python_count = 0
    try:
        python_count = sum(
            1 for p in psutil.process_iter(["pid", "name", "cmdline"])
            if "python" in (p.info["name"] or "").lower()
            and p.info["pid"] != curr_pid
            and ("batch_apply" in " ".join(p.info["cmdline"] or []) or "fill.py" in " ".join(p.info["cmdline"] or []))
        )
    except Exception:
        pass

    return total_applied, queue_count, python_count, recent


def format_status_message(header="📊 <b>Job Deck Live Control Panel</b>"):
    total, queue_count, py_count, recent = get_current_stats_fast()
    workers_state = f"Active ({py_count} workers)" if py_count > 0 else "Idle (ready)"
    now_str = datetime.now().strftime("%I:%M:%S %p")

    lines = [
        f"{header} <i>({now_str})</i>",
        "",
        f"🎯 <b>Total Verified Applications:</b> {total}",
        f"📋 <b>Queue Remaining:</b> {queue_count} prioritized roles",
        f"⚡ <b>Runner State:</b> {workers_state}",
        "",
    ]
    if recent:
        lines.append("<b>Recent Submissions:</b>")
        for r in recent:
            lines.append(f"• <b>{r.get('Company')}</b> — {r.get('Role')}")
    return "\n".join(lines)


def launch_runner(workers=3, queue="queue_cyber_iam.txt"):
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(ROOT / "batch_apply_parallel.py"),
        "--queue", queue,
        "--workers", str(workers),
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
    return stopped


# ---- Handlers ----

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    text = (
        "👋 <b>Welcome to Job Deck Control!</b>\n\n"
        "Tap any button below to view status or start/pause applications in real-time."
    )
    await update.message.reply_text(text, reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return
    await update.message.reply_text(format_status_message(), reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != AUTHORIZED_USER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "btn_status":
        await query.message.edit_text(format_status_message(), reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "btn_run":
        launch_runner(workers=3)
        await query.message.reply_text("🚀 <b>Launched 3 workers!</b> Applying in headless mode...", parse_mode=ParseMode.HTML)
    elif data == "btn_stop":
        stopped = halt_runner()
        await query.message.reply_text(f"🛑 <b>Halted {stopped} worker processes.</b>", parse_mode=ParseMode.HTML)
    elif data == "btn_boeing":
        launch_runner(workers=1, queue="queue_cyber_iam.txt")
        await query.message.reply_text("✈️ <b>Boeing Priority Run Launched!</b> Worker is targeting top of queue...", parse_mode=ParseMode.HTML)
    elif data == "btn_queue":
        _, q_count, _, _ = get_current_stats_fast()
        await query.message.reply_text(f"📋 <b>Queue Inventory:</b> {q_count} prioritized Cyber/IAM/Cloud roles remaining in queue.", parse_mode=ParseMode.HTML)
    elif data == "btn_obsidian":
        try:
            import sync_obsidian
            count = sync_obsidian.export_applications_to_obsidian()
            await query.message.reply_text(f"🔄 <b>Obsidian Vault Synced!</b> {count} new/updated notes in Desktop/Obsidian Job Tracker.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"Obsidian sync notice: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    t = (update.message.text or "").strip().lower()
    if "status" in t or "update" in t:
        await update.message.reply_text(format_status_message(), reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)
    elif "run" in t or "apply" in t or "start" in t:
        launch_runner(workers=3)
        await update.message.reply_text("🚀 <b>Started 3 headless workers!</b>", reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)
    elif "stop" in t or "pause" in t:
        stopped = halt_runner()
        await update.message.reply_text(f"🛑 <b>Runner paused ({stopped} stopped).</b>", reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)
    elif "boeing" in t:
        await update.message.reply_text("✈️ Boeing roles are #1 on the queue. Tap <b>Apply Boeing</b> below to process immediately!", reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"⚡ <b>Received:</b> \"{update.message.text}\"\nInstruction noted for Job Deck.", reply_markup=get_keyboard(), parse_mode=ParseMode.HTML)


async def send_3hour_update(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue scheduled job: executes every 3 hours."""
    try:
        msg = format_status_message(header="🕒 <b>3-Hour Scheduled Update</b>")
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=msg,
            reply_markup=get_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        print(f"[3-Hour Update Error] {e}", flush=True)


def main():
    if not BOT_TOKEN or not AUTHORIZED_USER_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    print("[Job Deck Control Bot] Initializing python-telegram-bot v22...", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands & buttons
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["status", "update"], cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Schedule 3-hour updates (10800 seconds)
    if app.job_queue:
        app.job_queue.run_repeating(send_3hour_update, interval=3 * 3600, first=3 * 3600)
        print("[Job Deck Control Bot] 3-hour JobQueue interval scheduled.", flush=True)

    print("[Job Deck Control Bot] Polling started. Ready!", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
