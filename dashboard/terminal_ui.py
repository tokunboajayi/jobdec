"""
CYBERDECK CLI TERMINAL TUI // AJ AUTONOMOUS APPLICATION PIPELINE
Full-screen matrix black & green hacker HUD for Windows Terminal / PowerShell.
Reads directly from applications.csv, results.csv, and overnight_run.log in real-time.
"""
import csv
import os
import pathlib
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

# Enable ANSI escape sequences & Disable QuickEdit Mode (prevents terminal freeze on mouse click)
if sys.platform == "win32":
    import ctypes
    try:
        kernel32 = ctypes.windll.kernel32
        # Enable ANSI output
        h_out = kernel32.GetStdHandle(-11)
        kernel32.SetConsoleMode(h_out, 7)
        
        # Disable QuickEdit mode on stdin so mouse clicks don't freeze the script
        h_in = kernel32.GetStdHandle(-10)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_in, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(h_in, new_mode)
    except Exception:
        pass

if sys.platform == "win32":
    import msvcrt
else:
    msvcrt = None
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
AUTOFILL_DIR = HERE.parent
ROOT_DIR = AUTOFILL_DIR.parent

# ANSI Colors
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_GREEN = "\033[38;5;46m"        # Pure Neon Matrix Green
CLR_DARK_GREEN = "\033[38;5;28m"   # Dark Phosphor Green
CLR_MINT = "\033[38;5;49m"         # Cyber Mint
CLR_CYAN = "\033[38;5;51m"         # Neon Cyan
CLR_AMBER = "\033[38;5;214m"       # Warning Amber
CLR_RED = "\033[38;5;196m"         # Error Red
CLR_BG_DARK = "\033[48;5;232m"     # Void Black BG
CLR_WHITE = "\033[97m"

def read_log_file(p):
    if not p.exists():
        return []
    try:
        raw = p.read_bytes()
        if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:100]:
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        return [l for l in text.splitlines() if l.strip()]
    except Exception:
        return []

def get_stats():
    today = time.strftime("%Y-%m-%d")
    total_applied = 0
    app_csv = ROOT_DIR / "applications.csv"
    if app_csv.exists():
        try:
            with open(app_csv, "r", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if row.get("Stage", "").strip().lower() == "applied":
                        total_applied += 1
        except Exception:
            pass

    submitted_today = 0
    res_csv = AUTOFILL_DIR / "results.csv"
    if res_csv.exists():
        try:
            with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if row.get("date") == today and row.get("status") == "submitted":
                        submitted_today += 1
        except Exception:
            pass

    queue_count = 0
    q_file = AUTOFILL_DIR / "queue_ranked.txt"
    if q_file.exists():
        try:
            for l in q_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if l.strip() and not l.strip().startswith("#"):
                    queue_count += 1
        except Exception:
            pass

    active_job = "Auto-Owners Insurance (Verified) -> Next Target"
    active_url = "https://aoins.wd5.myworkdayjobs.com/..."
    log_file = AUTOFILL_DIR / "overnight_run.log"
    recent_lines = []
    lines = read_log_file(log_file)
    if lines:
        recent_lines = lines[-14:]
        for l in reversed(lines):
            m = re.search(r"Starting:\s*([^\-]+?)\s*-\s*(.+)$", l)
            if m:
                active_job = f"{m.group(1).strip()} - {m.group(2).strip()}"
                break
        for l in reversed(lines):
            m = re.search(r"URL:\s*(https?://[^\s]+)", l)
            if m:
                active_url = m.group(1).strip()
                break

    return {
        "applied": total_applied,
        "velocity": submitted_today,
        "cap": 100,
        "queue": queue_count,
        "active_job": active_job[:58],
        "active_url": active_url[:58],
        "lines": recent_lines
    }

import shutil

def render_frame():
    cols, rows = shutil.get_terminal_size((90, 30))
    # Keep width bounded to terminal width or 92
    box_w = min(cols - 2, 90)
    box_w = max(box_w, 60)
    
    stats = get_stats()
    now_utc = time.strftime("%H:%M:%S UTC", time.gmtime())
    
    # Progress bar for daily cap
    cap_pct = min(100, int((stats['velocity'] / stats['cap']) * 100))
    bar_chars = max(10, min(24, box_w - 65))
    filled_chars = int((cap_pct / 100) * bar_chars)
    bar = f"{CLR_GREEN}{'█' * filled_chars}{CLR_DARK_GREEN}{'░' * (bar_chars - filled_chars)}{CLR_RESET}"

    out = []

    # Show full 3D ASCII art header
    if rows >= 18:
        out.append(f"{CLR_GREEN}")
        out.append(r"         ██╗ ██████╗ ██████╗ ██████╗ ███████╗ ██████╗██╗  ██╗")
        out.append(r"         ██║██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔════╝██║ ██╔╝")
        out.append(r"         ██║██║   ██║██████╔╝██║  ██║█████╗  ██║     █████═╝ ")
        out.append(r"    ██   ██║██║   ██║██╔══██╗██║  ██║██╔══╝  ██║     ██╔═██╗ ")
        out.append(r"    ╚█████╔╝╚██████╔╝██████╔╝██████╔╝███████╗╚██████╗██║  ██╗")
        out.append(r"     ╚════╝  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝╚═╝  ╚═╝")
        out.append(f"{CLR_RESET}")
    else:
        out.append(f"{CLR_GREEN}{CLR_BOLD}  [ ■ JOBDECK AUTONOMOUS KERNEL // AJ APPLICATION ENGINE v4.2 ■ ]{CLR_RESET}")

    # Top Status Banner
    bar_h = "═" * (box_w - 2)
    out.append(f"{CLR_DARK_GREEN}╔{bar_h}╗{CLR_RESET}")
    title = f"{CLR_GREEN}{CLR_BOLD}AJ // JOBDECK_KERNEL{CLR_RESET}   {CLR_CYAN}[LOCAL: http://localhost:8888]{CLR_RESET}   {CLR_MINT}{now_utc}{CLR_RESET}"
    out.append(f"{CLR_DARK_GREEN}║ {title}{' ' * max(0, box_w - 68)} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}╠{bar_h}╣{CLR_RESET}")
    
    # Telemetry HUD Row
    applied_str = f"{CLR_WHITE}{CLR_BOLD}{stats['applied']}{CLR_RESET} {CLR_GREEN}VERIFIED{CLR_RESET}"
    velo_str = f"{CLR_WHITE}{CLR_BOLD}{stats['velocity']}{CLR_RESET}/{stats['cap']} {bar}"
    queue_str = f"{CLR_WHITE}{CLR_BOLD}{stats['queue']}{CLR_RESET} {CLR_CYAN}ROLES{CLR_RESET}"
    
    out.append(f"{CLR_DARK_GREEN}║ {CLR_GREEN}APPLIED:{CLR_RESET} {applied_str:<22}  {CLR_GREEN}TODAY:{CLR_RESET} {velo_str} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}║ {CLR_GREEN}TARGET QUEUE:{CLR_RESET} {queue_str:<18}  {CLR_GREEN}STATUS:{CLR_RESET} {CLR_GREEN}● ONLINE // KG: 785+ ENTITIES{CLR_RESET} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}╠{bar_h}╣{CLR_RESET}")
    
    # Active Radar Target
    job_str = stats['active_job'][:box_w - 18]
    url_str = stats['active_url'][:box_w - 18]
    out.append(f"{CLR_DARK_GREEN}║ {CLR_MINT}{CLR_BOLD}[RADAR]{CLR_RESET} {CLR_WHITE}{job_str:<{box_w - 12}}{CLR_RESET} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}║ {CLR_DIM}URL:    {url_str:<{box_w - 12}}{CLR_RESET} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}╠{bar_h}╣{CLR_RESET}")
    
    # Log Feed Section Header
    out.append(f"{CLR_DARK_GREEN}║ {CLR_GREEN}{CLR_BOLD}LIVE KERNEL LOG STREAM (overnight_run.log){CLR_RESET}{' ' * max(0, box_w - 64)}{CLR_DIM}[CTRL+C TO DETACH]{CLR_RESET} {CLR_DARK_GREEN}║{CLR_RESET}")
    out.append(f"{CLR_DARK_GREEN}╠{bar_h}╣{CLR_RESET}")
    
    # Calculate how many log lines fit in the remaining window rows
    used_rows = len(out) + 4
    available_log_rows = max(4, min(14, rows - used_rows))
    display_lines = stats['lines'][-available_log_rows:]
    
    # Log Lines
    for l in display_lines:
        l_clean = l.strip()
        if not l_clean:
            continue
        
        tag = f"{CLR_GREEN}INFO{CLR_RESET}"
        text_color = CLR_GREEN
        if "submitted" in l_clean.lower() or "[success]" in l_clean.lower():
            tag = f"{CLR_GREEN}{CLR_BOLD}SUCCESS{CLR_RESET}"
            text_color = f"{CLR_GREEN}{CLR_BOLD}"
        elif "submit" in l_clean.lower():
            tag = f"{CLR_CYAN}SUBMIT{CLR_RESET}"
            text_color = CLR_CYAN
        elif "code" in l_clean.lower() or "auth" in l_clean.lower():
            tag = f"{CLR_AMBER}AUTH{CLR_RESET}"
            text_color = CLR_AMBER
        elif "error" in l_clean.lower() or "blocked" in l_clean.lower() or "timeout" in l_clean.lower():
            tag = f"{CLR_RED}WARN{CLR_RESET}"
            text_color = CLR_RED

        max_text_len = box_w - 14
        display_line = l_clean[:max_text_len]
        out.append(f"{CLR_DARK_GREEN}║{CLR_RESET} [{tag}] {text_color}{display_line:<{max_text_len}}{CLR_RESET} {CLR_DARK_GREEN}║{CLR_RESET}")

    out.append(f"{CLR_DARK_GREEN}╚{bar_h}╝{CLR_RESET}")
    out.append(f"{CLR_CYAN}aj@jobdeck:~$ {CLR_GREEN}HOTKEYS: {CLR_WHITE}[B]{CLR_MINT} Web GUI  {CLR_WHITE}[K]{CLR_MINT} Knowledge Graph  {CLR_WHITE}[L]{CLR_MINT} Log  {CLR_WHITE}[Q]{CLR_MINT} Exit{CLR_RESET}")
    
    # Overwrite in-place smoothly: cursor home, each line cleared to end (\033[K), erase trailing with \033[J
    rendered_frame = "\033[H" + "\n".join(f"{line}\033[K" for line in out) + "\033[J\n"
    sys.stdout.write(rendered_frame)
    sys.stdout.flush()

def main():
    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    # Initial one-time clear on startup
    if os.name == "nt":
        os.system("cls")
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    try:
        while True:
            render_frame()
            for _ in range(15):
                if sys.platform == "win32" and msvcrt and msvcrt.kbhit():
                    ch = msvcrt.getch().decode("utf-8", errors="ignore").lower()
                    if ch == "b":
                        webbrowser.open("http://localhost:8888")
                    elif ch == "l":
                        log_p = AUTOFILL_DIR / "overnight_run.log"
                        os.system(f'start notepad "{log_p}"')
                    elif ch in ("q", "\x03"):
                        return
                    elif ch == "r":
                        break
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor again
        sys.stdout.write("\033[?25h\n" + CLR_RESET)
        sys.stdout.flush()

        print(f"\n{CLR_GREEN}[JOBDECK] Terminal view detached. Background process continues running autonomously.{CLR_RESET}")
        print(f"{CLR_CYAN}[JOBDECK] Web dashboard active at http://localhost:8888{CLR_RESET}\n")

if __name__ == "__main__":
    main()
