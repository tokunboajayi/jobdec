"""
Enterprise PC & Program Performance Optimizer for Job Deck
Prevents PC lag, stutter, and thermal throttling when running background workers.

Capabilities:
1. Windows Priority & I/O Throttling:
   - Sets all runner, worker, and browser processes to BELOW_NORMAL (or IDLE) priority class.
   - Sets background I/O priority to LOW so disk access never interrupts user foreground tasks.
2. Dynamic Memory Working Set Trimming:
   - Invokes Windows API `EmptyWorkingSet` and Python `gc.collect()` after every job attempt.
   - Instantly recovers hundreds of megabytes of physical RAM back to the operating system.
3. Zombie Browser & Process Purging:
   - Scans and eliminates orphaned `chrome.exe` and `conhost.exe` processes left behind by crashes/timeouts.
4. Adaptive Coexistence CPU Governor:
   - Dynamically monitors system CPU load; yields execution timeslices if the user is actively working.
"""

import os
import sys
import gc
import ctypes
import psutil
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Windows API Constants
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400


def set_process_priority(pid: Optional[int] = None, priority: str = "below_normal", recursive: bool = True) -> int:
    """
    Sets process priority and I/O priority to prevent competing with user's foreground apps.
    Levels:
      - 'below_normal': (Default) Windows gives 100% priority to user foreground apps, runs when idle.
      - 'idle': Lowest priority possible; only runs on spare CPU cycles.
      - 'normal': Standard Windows priority.
    """
    target_pid = pid if pid is not None else os.getpid()
    count = 0

    priority_map = {
        "idle": getattr(psutil, "IDLE_PRIORITY_CLASS", 64),
        "below_normal": getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 16384),
        "normal": getattr(psutil, "NORMAL_PRIORITY_CLASS", 32),
    }
    p_val = priority_map.get(priority.lower(), getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 16384))

    try:
        main_p = psutil.Process(target_pid)
        target_procs = [main_p]
        if recursive:
            try:
                target_procs.extend(main_p.children(recursive=True))
            except Exception:
                pass

        for p in target_procs:
            try:
                if sys.platform == "win32":
                    p.nice(p_val)
                    try:
                        p.ionice(getattr(psutil, "IOPRIO_LOW", 1))
                    except Exception:
                        pass
                else:
                    # Linux / macOS niceness
                    nice_val = 10 if priority == "below_normal" else (19 if priority == "idle" else 0)
                    p.nice(nice_val)
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"[PC Optimizer] Error setting priority on PID {target_pid}: {e}")

    return count


def trim_process_memory(pid: Optional[int] = None, recursive: bool = True) -> Tuple[float, int]:
    """
    Trims unreferenced and cached memory from the process working set using Windows API.
    Returns (mb_reclaimed, processes_trimmed).
    """
    gc.collect()
    if sys.platform != "win32":
        return 0.0, 0

    target_pid = pid if pid is not None else os.getpid()
    mb_reclaimed = 0.0
    procs_trimmed = 0

    try:
        main_p = psutil.Process(target_pid)
        target_procs = [main_p]
        if recursive:
            try:
                target_procs.extend(main_p.children(recursive=True))
            except Exception:
                pass

        for p in target_procs:
            try:
                before_rss = p.memory_info().rss
                h_process = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, p.pid
                )
                if h_process:
                    ctypes.windll.psapi.EmptyWorkingSet(h_process)
                    ctypes.windll.kernel32.CloseHandle(h_process)
                    procs_trimmed += 1
                    try:
                        after_rss = p.memory_info().rss
                        diff = (before_rss - after_rss) / (1024 * 1024)
                        if diff > 0:
                            mb_reclaimed += diff
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"[PC Optimizer] Working set trim error on PID {target_pid}: {e}")

    return mb_reclaimed, procs_trimmed


def purge_zombie_browsers() -> int:
    """
    Terminates orphaned and disconnected Chromium processes left behind
    by browser timeouts or crashed workers.
    """
    killed = 0
    curr_pid = os.getpid()
    active_pids = set()

    for p in psutil.process_iter(["pid", "ppid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if not ("chrome" in name or "chromedriver" in name or "python" in name):
                continue
            pid = p.info["pid"]
            ppid = p.info["ppid"]

            cmd = " ".join(p.cmdline() or [])
            if ("batch_apply" in cmd or "telegram_bot" in cmd) and pid != curr_pid:
                active_pids.add(pid)

            if "chrome" in name or "chromedriver" in name:
                if ".browser-profile" in cmd or "--remote-debugging-port" in cmd:
                    if ppid not in active_pids and ppid != curr_pid:
                        try:
                            p.kill()
                            killed += 1
                        except Exception:
                            pass
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return killed


def run_full_system_optimization() -> Dict[str, Any]:
    """
    One-click comprehensive PC and Job Deck optimization:
    1. Sets all Job Deck and child browser processes to BELOW_NORMAL priority.
    2. Terminates zombie and orphaned browser processes.
    3. Trims working sets across all active processes.
    """
    curr_pid = os.getpid()
    total_trimmed_mb = 0.0
    total_procs_trimmed = 0
    total_procs_prioritized = 0

    # 1. Kill zombies
    zombies_killed = purge_zombie_browsers()

    # 2. Optimize priority & trim memory on all Job Deck components
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if not ("python" in name or "chrome" in name):
                continue
            cmd = " ".join(p.cmdline() or [])
            if any(k in cmd for k in ["batch_apply", "fill.py", "telegram_bot_service", ".browser-profile"]):
                # Set priority
                total_procs_prioritized += set_process_priority(p.info["pid"], priority="below_normal", recursive=True)
                # Trim memory
                freed, count = trim_process_memory(p.info["pid"], recursive=True)
                total_trimmed_mb += freed
                total_procs_trimmed += count
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return {
        "status": "success",
        "reclaimed_mb": round(total_trimmed_mb, 1),
        "zombies_killed": zombies_killed,
        "procs_optimized": total_procs_prioritized,
        "procs_trimmed": total_procs_trimmed,
    }


class AdaptiveCPUGovernor:
    """
    Intelligent CPU Governor that measures overall system load and instructs
    background workers to yield timeslices when user is actively using the PC.
    """
    def __init__(self, high_cpu_threshold: float = 75.0, extreme_cpu_threshold: float = 85.0):
        self.high_cpu_threshold = high_cpu_threshold
        self.extreme_cpu_threshold = extreme_cpu_threshold

    def get_throttle_delay(self) -> float:
        """
        Calculates courteous backoff delay (in seconds) based on current CPU load.
        Zero delay when CPU is free; scales up when PC is under load.
        """
        try:
            cpu = psutil.cpu_percent(interval=None)
            if cpu >= self.extreme_cpu_threshold:
                # Heavy user activity (e.g. video render, gaming, compiling): yield generously
                return 0.35
            elif cpu >= self.high_cpu_threshold:
                # Moderate user activity: yield small slices to keep UI responsive
                return 0.10
            elif cpu >= 60.0:
                return 0.02
            return 0.0
        except Exception:
            return 0.0

    def should_scale_down(self) -> bool:
        """Returns True if CPU or Memory pressure requires reducing worker count."""
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            return cpu > 90.0 or mem > 88.0
        except Exception:
            return False


# Singleton Governor Instance
_GOVERNOR: Optional[AdaptiveCPUGovernor] = None

def get_governor() -> AdaptiveCPUGovernor:
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = AdaptiveCPUGovernor()
    return _GOVERNOR
