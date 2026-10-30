"""
High-Throughput Parallel Autonomous Job Application Runner.
Implements Phase 2 Multi-Worker Execution Architecture from scaling_to_3000_plan.md.

Key Features:
- True Sandbox Isolation: Each parallel worker operates in a sandboxed, dedicated
  Chromium profile (.browser-profile-w1, .browser-profile-w2, etc.) to eliminate browser lock contention.
- Atomic Dynamic Task Partitioning: Jobs from queue_ranked.txt are claimed atomically
  with zero race conditions or collision across workers.
- Thread/Process-Safe Ledgers: applications.csv, results.csv, and auth_state.json
  are updated with cross-process FileLock.
- Asset Blocking (3x Speedup): Automatically aborts media/trackers in headless mode.
- Real-Time Live Telemetry: Shows active workers, submission rate, fit scores, and ETA towards target (e.g. 300).
"""
import argparse
import atexit
import csv
import json
import os
import pathlib
import random
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CSV_FILE = ROOT / "applications.csv"

import results_engine as RE


def get_applied_count() -> int:
    """Reads distinct verified applied jobs from applications.csv."""
    if not CSV_FILE.exists():
        return 0
    applied_count = 0
    try:
        with open(CSV_FILE, encoding="utf-8-sig", errors="ignore") as f:
            for row in csv.DictReader(f):
                if row.get("Stage") == "Applied":
                    applied_count += 1
    except Exception:
        pass
    return applied_count


def load_applied_signatures() -> Tuple[Set[str], Set[Tuple[str, str]]]:
    """Loads applied URLs and normalized (company, role) pairs to prevent duplicate submissions."""
    applied_urls = set()
    applied_pairs = set()

    if CSV_FILE.exists():
        try:
            with open(CSV_FILE, encoding="utf-8-sig", errors="ignore") as f:
                for row in csv.DictReader(f):
                    if row.get("Stage") == "Applied":
                        u = (row.get("Job URL") or "").strip()
                        if u:
                            applied_urls.add(u)
                        c = (row.get("Company") or "").strip().lower()
                        r = (row.get("Role") or "").strip().lower()
                        if c and r:
                            applied_pairs.add((c, r))
        except Exception:
            pass

    for r in RE.ledger_rows():
        if r.get("status") == "submitted":
            u = (r.get("url") or "").strip()
            if u:
                applied_urls.add(u)
            c = (r.get("company") or "").strip().lower()
            ro = (r.get("role") or "").strip().lower()
            if c and ro:
                applied_pairs.add((c, ro))

    return applied_urls, applied_pairs


def parse_queue(queue_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Queue file -> job entries; a resume named on the line is kept only if the file exists."""
    if not queue_path.exists():
        return []
    jobs = RE.parse_queue_file(queue_path)
    for j in jobs:
        if j["resume"] and not (ROOT / j["resume"]).exists():
            j["resume"] = None
    return jobs


def run_logged_worker(cmd: List[str], timeout: int | float, log_path: pathlib.Path, prefix: str,
                      active_pids: List[int], pids_lock: threading.Lock, env: Optional[Dict[str, str]] = None) -> int:
    """Executes fill.py in subprocess with streaming prefixed output and PID tracking."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(HERE),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    with pids_lock:
        active_pids.append(proc.pid)

    with open(log_path, "w", encoding="utf-8", errors="ignore") as log:
        def pump():
            if proc.stdout is not None:
                for line in proc.stdout:
                    msg = f"[{prefix}] {line}"
                    try:
                        print(msg, end="", flush=True)
                    except Exception:
                        try:
                            sys.stdout.buffer.write(msg.encode("utf-8", errors="replace"))
                            sys.stdout.buffer.flush()
                        except Exception:
                            pass
                    try:
                        log.write(line)
                        log.flush()
                    except Exception:
                        pass

        t = threading.Thread(target=pump, daemon=True)
        t.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(f"taskkill /F /T /PID {proc.pid}", shell=True, capture_output=True)
            else:
                proc.kill()
            t.join(3)
            raise
        finally:
            with pids_lock:
                if proc.pid in active_pids:
                    active_pids.remove(proc.pid)
            t.join(3)

    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="Parallel Multi-Worker Autonomous Application Runner")
    parser.add_argument("--workers", type=int, default=3, help="Number of concurrent worker instances (default: 3)")
    parser.add_argument("--limit", type=int, default=1000, help="Max applications to attempt in this run (default: 1000)")
    parser.add_argument("--target", type=int, default=3000, help="Stop automatically when total verified submissions reach this target (default: 3000)")
    parser.add_argument("--target-new", type=int, default=None, help="Stop automatically after this many NEW verified submissions in this session")
    parser.add_argument("--queue", default="queue_ranked.txt", help="Queue file to read from (default: queue_ranked.txt)")
    parser.add_argument("--resume", default="resumes/master_resume.pdf", help="Default resume to use")
    parser.add_argument("--use-tailored", action="store_true", default=True, help="Use tailored resume if specified in queue or tailor dynamically")
    parser.add_argument("--timeout", type=int, default=260, help="Per-application timeout in seconds (default: 260)")
    parser.add_argument("--headful", action="store_true", help="Force visible browser window (default: False)")
    parser.add_argument("--no-block-assets", action="store_true", help="Disable asset blocking")
    parser.add_argument("--no-triage", action="store_true", help="Bypass fit score checks and company filters")
    parser.add_argument("--include-held", action="store_true", help="Also run queue lines that have a pending-decision note")
    parser.add_argument("--daily-cap", type=int, default=None, help="Max submissions per day (default: strategy.json daily_cap)")
    parser.add_argument("--delay", type=float, default=2.0, help="Jitter delay between tasks per worker (default: 2.0s)")
    args = parser.parse_args()

    # Process concurrency lock: prevent multiple batch instances from clashing
    lock_file = HERE / ".batch_apply_parallel.lock"
    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            if sys.platform == "win32":
                out = subprocess.check_output(f'tasklist /FI "PID eq {old_pid}"', shell=True, text=True)
                if str(old_pid) in out and "python" in out.lower():
                    print(f"[Parallel Runner] Another runner (PID {old_pid}) is currently running. Exiting.")
                    return
        except Exception:
            pass
    lock_file.write_text(str(os.getpid()))
    atexit.register(lambda: lock_file.unlink(missing_ok=True))

    queue_file = HERE / args.queue
    if not queue_file.exists() and (HERE / "queue.txt").exists():
        queue_file = HERE / "queue.txt"

    jobs = parse_queue(queue_file)

    # Check for healed retries
    retry_file = HERE / "queue_retry.txt"
    retries = parse_queue(retry_file)
    if retries:
        print(f"[Parallel Runner] Prioritizing {len(retries)} healed jobs from queue_retry.txt!")
        jobs = retries + jobs
        # one pass per heal: never drained, the same 227 retries took every batch's 150 attempts (2026-10-28)
        retry_file.unlink(missing_ok=True)

    # A queue line with a note like "(AJ: pick ...)" is waiting on a decision: held unless --include-held.
    if not args.include_held:
        jobs = [j for j in jobs if not j["hold"]]

    if not jobs:
        print(f"[Parallel Runner] No jobs found in {queue_file.name}.")
        return

    applied_urls, applied_pairs = load_applied_signatures()
    initial_applied_count = get_applied_count()
    if args.target_new is not None:
        args.target = initial_applied_count + args.target_new

    num_workers = max(1, min(args.workers, 6))
    strat = RE.strategy()
    daily_cap = args.daily_cap if args.daily_cap is not None else strat.get("daily_cap", 3000)

    print("\n" + "=" * 68)
    print("      AJ AUTONOMOUS HIGH-THROUGHPUT PARALLEL APPLICATOR FRAMEWORK")
    print(f"  Target Milestone:     {args.target} verified submissions")
    print(f"  Current Baseline:     {initial_applied_count} applied in applications.csv")
    print(f"  Concurrent Workers:   {num_workers} isolated sandboxed browser processes")
    print(f"  Asset Blocker:        {'DISABLED' if args.no_block_assets else 'ACTIVE (3x Speedup, Images/Trackers Aborted)'}")
    print(f"  Queue Inventory:      {len(jobs)} postings loaded from {queue_file.name}")
    print(f"  Max Batch Limit:      {args.limit} attempts")
    print("=" * 68 + "\n")

    # Thread-safe dispatch state
    state_lock = threading.Lock()
    job_cursor = 0
    attempts = 0
    completed_this_session = 0
    stop_flag = False
    site_failures = {}
    active_companies = set()
    claimed_indices = set()

    active_pids: List[int] = []
    pids_lock = threading.Lock()

    def kill_all_workers():
        with pids_lock:
            for pid in active_pids:
                try:
                    if sys.platform == "win32":
                        subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
                    else:
                        os.kill(pid, 9)
                except Exception:
                    pass

    atexit.register(kill_all_workers)

    def get_next_job(worker_id: int):
        nonlocal job_cursor, attempts, stop_flag
        w_tag = f"W{worker_id}"

        with state_lock:
            while job_cursor < len(jobs) and job_cursor in claimed_indices:
                job_cursor += 1

            if stop_flag or job_cursor >= len(jobs):
                return None

            current_total = get_applied_count()
            if current_total >= args.target:
                print(f"[{w_tag}] TARGET OF {args.target} REACHED! (Currently {current_total}). Halting dispatch.")
                stop_flag = True
                return None

            if attempts >= args.limit:
                print(f"[{w_tag}] Batch limit of {args.limit} attempts reached. Stopping.")
                stop_flag = True
                return None

            if not args.no_triage:
                if RE.submitted_today() >= daily_cap:
                    print(f"[{w_tag}] Daily cap of {daily_cap} reached for today. Stopping.")
                    stop_flag = True
                    return None

            chosen_idx = None
            for scan_idx in range(job_cursor, len(jobs)):
                if scan_idx in claimed_indices:
                    continue
                candidate = jobs[scan_idx]
                u = candidate["url"].strip()
                c_norm = candidate["company"].strip().lower()
                r_norm = candidate["role"].strip().lower()

                if u in applied_urls or (c_norm and r_norm and (c_norm, r_norm) in applied_pairs):
                    claimed_indices.add(scan_idx)
                    continue

                if c_norm and c_norm in active_companies:
                    continue

                if not args.no_triage:
                    score, cat, why = RE.score_job(candidate["company"], candidate["role"], candidate["url"])
                    if RE.is_protected(candidate["company"]):
                        print(f"[{w_tag}][{scan_idx+1}] PROTECTED: {candidate['company']} requires manual handling. Skipping.")
                        claimed_indices.add(scan_idx)
                        continue
                    if score < strat.get("min_fit_score", 5.0):
                        claimed_indices.add(scan_idx)
                        continue

                    try:
                        import urllib.parse
                        from brain.vault import get_vault
                        dom = urllib.parse.urlparse(candidate["url"]).netloc.lower()
                        if get_vault().is_fast_fail(dom):
                            print(f"[{w_tag}][{scan_idx+1}] [Brain Fast-Fail] {dom} impassable barrier. Skipping.")
                            claimed_indices.add(scan_idx)
                            continue
                    except Exception as e:
                        print(f"[{w_tag}] [Brain Fast-Fail] check failed, not applied: {e}")

                    sk = RE.site_key(candidate["url"])
                    if sk in strat.get("skip_sites", []) or RE.ats_of(candidate["url"])[0] in strat.get("skip_ats", []):
                        claimed_indices.add(scan_idx)
                        continue
                    if site_failures.get(sk, 0) >= strat.get("max_failures_per_site_per_run", 5):
                        claimed_indices.add(scan_idx)
                        continue

                    try:
                        from agents import smarts
                        ok, why_skip = smarts.should_attempt(candidate["company"], candidate["role"], candidate["url"])
                        if not ok:
                            claimed_indices.add(scan_idx)
                            continue
                        if score >= 9:
                            from agents import outreach_drafter
                            if outreach_drafter.draft(candidate["company"], candidate["role"], score, candidate["url"], pre_apply=True):
                                print(f"[{w_tag}]      [Outreach] referral note drafted (see outreach_drafts.csv)")
                    except Exception as e:
                        print(f"[{w_tag}] [smarts] check failed, not applied: {e}")

                chosen_idx = scan_idx
                break

            if chosen_idx is None:
                while job_cursor < len(jobs) and job_cursor in claimed_indices:
                    job_cursor += 1
                return None

            job = jobs[chosen_idx]
            claimed_indices.add(chosen_idx)
            u = job["url"].strip()
            c_norm = job["company"].strip().lower()
            r_norm = job["role"].strip().lower()

            applied_urls.add(u)
            if c_norm and r_norm:
                applied_pairs.add((c_norm, r_norm))
            if c_norm:
                active_companies.add(c_norm)

            while job_cursor < len(jobs) and job_cursor in claimed_indices:
                job_cursor += 1

            resume_to_use = job["resume"] if (args.use_tailored and job["resume"]) else args.resume
            if args.use_tailored:
                try:
                    from agents import resume_tailor
                    resume_to_use = resume_tailor.tailor(job["company"], job["role"], job["url"], resume_to_use)
                except Exception as e:
                    print(f"[{w_tag}]      [Resume Tailor] skipped, using untailored resume: {e}")

            attempts += 1
            return (job, chosen_idx + 1, attempts, resume_to_use)

    def worker_loop(worker_id: int):
        nonlocal completed_this_session
        w_prefix = f"W{worker_id}"

        while not stop_flag:
            item = get_next_job(worker_id)
            if not item:
                with state_lock:
                    if stop_flag or (job_cursor >= len(jobs) and not active_companies):
                        break
                time.sleep(1.0)
                continue

            job, idx, attempt_num, resume_to_use = item
            current_total = get_applied_count()
            c_norm = job["company"].strip().lower()
            job_timeout: float = float(args.timeout)
            t0 = time.time()

            try:
                print(f"\n[{w_prefix}][{idx}] Attempt {attempt_num}/{args.limit} | Overall: {current_total}/{args.target} ({current_total/args.target*100:.1f}%)")
                print(f"[{w_prefix}]   Target: {job['company']} - {job['role']}")
                print(f"[{w_prefix}]   URL:    {job['url']}")
                print(f"[{w_prefix}]   Resume: {resume_to_use}")

                # Pre-flight DNS/HTTP & Active Status check
                try:
                    from agents import job_validator
                    is_live, dead_reason = job_validator.is_job_active(job["url"], timeout=4)
                    if not is_live:
                        print(f"[{w_prefix}] Pre-flight skip: Job closed/inactive ({dead_reason}). Advancing...")
                        continue
                except Exception as e:
                    print(f"[{w_prefix}] Pre-flight validator failed, continuing: {e}")

                try:
                    from agents.supervisor import pre_submit_check
                    guard_fail = pre_submit_check(job["url"], job["company"], str(resume_to_use) if resume_to_use else "")
                    if guard_fail:
                        print(f"[{w_prefix}] [Pre-Submit Guard] {guard_fail}. Skipping.")
                        continue
                except Exception as e:
                    print(f"[{w_prefix}] Pre-submit guard failed, continuing: {e}")

                cmd = [
                    sys.executable, "-u", str(HERE / "fill.py"), job["url"],
                    "--worker-id", str(worker_id),
                ]
                if job["company"]:
                    cmd.extend(["--company", job["company"]])
                if job["role"]:
                    cmd.extend(["--role", job["role"]])
                if resume_to_use:
                    cmd.extend(["--resume", str(resume_to_use)])
                if args.headful:
                    cmd.append("--headful")
                else:
                    cmd.append("--headless")
                if args.no_block_assets:
                    cmd.append("--no-block-assets")
                else:
                    cmd.append("--block-assets")

                log_path = RE.RECORDS_DIR / time.strftime("%Y-%m-%d") / f"{RE._slug(job['company'], job['role'])}.log"
                job_timeout = max(args.timeout, strat.get("ats_timeouts", {}).get(RE.ats_of(job["url"])[0], 0))
                try:
                    from agents import smarts
                    job_timeout = smarts.site_timeout(job["url"], job_timeout)
                except Exception as e:
                    smarts = None
                    print(f"[{w_prefix}] site timeout lookup failed: {e}")

                t0 = time.time()
                env = {**os.environ, "AF_DEADLINE": str(job_timeout)}
                try:
                    from agents import cover_letter
                    cover = cover_letter.build(job["company"], job["role"], job["url"])
                    if cover:
                        env["AF_COVER"] = cover
                except Exception as e:
                    print(f"[{w_prefix}]      [Cover Letter] skipped, using the generic letter: {e}")
                ret = run_logged_worker(cmd, job_timeout, log_path, prefix=w_prefix, active_pids=active_pids,
                                        pids_lock=pids_lock, env=env)
                dur = round(time.time() - t0, 1)

                status = "submitted" if ret == 0 else "not_submitted"
                if smarts:
                    smarts.site_record(job["url"], status, dur)
                RE.ledger_add(job["company"], job["role"], job["url"], status)

                if ret == 0:
                    with state_lock:
                        completed_this_session += 1
                        tot = get_applied_count()
                        print(f"[{w_prefix}] *** SUCCESS: {job['company']} submitted! Total verified: {tot}/{args.target} ({dur}s) ***")

                        # Remove from retry file if succeeded
                        if retry_file.exists():
                            try:
                                cur_lines = [l for l in retry_file.read_text(encoding="utf-8").splitlines() if job["url"] not in l]
                                retry_file.write_text("\n".join(cur_lines) + ("\n" if cur_lines else ""), encoding="utf-8")
                            except Exception:
                                pass

                    # Brain success feedback
                    try:
                        import urllib.parse
                        from brain.vault import get_vault
                        dom = urllib.parse.urlparse(job["url"]).netloc.lower()
                        get_vault().record_success(dom, answers_count=12, duration_sec=dur)
                    except Exception as e:
                        print(f"[{w_prefix}] brain success feedback failed: {e}")
                else:
                    sk = RE.site_key(job["url"])
                    with state_lock:
                        site_failures[sk] = site_failures.get(sk, 0) + 1
                    status_lbl = "SKIPPED (blocked/unanswerable)" if ret == 2 else f"EXIT_{ret}"
                    print(f"[{w_prefix}] {status_lbl}: {job['company']} failed after {dur}s.")

                    # Supervisor heal callback (prefers the record fill.py wrote for this job)
                    try:
                        from agents.supervisor import on_job_complete
                        heal_rec = {"company": job["company"], "role": job["role"], "url": job["url"], "status": "not_submitted"}
                        rec_path = log_path.with_suffix(".json")
                        if rec_path.exists():
                            heal_rec = json.loads(rec_path.read_text(encoding="utf-8"))
                        heal_msg = on_job_complete(heal_rec, log_path)
                        if heal_msg:
                            print(f"[{w_prefix}]   [Supervisor] {heal_msg}")
                    except Exception as e:
                        print(f"[{w_prefix}]   [Supervisor] heal callback error: {e}")

                    # Brain failure feedback
                    try:
                        import urllib.parse
                        from brain.vault import get_vault
                        get_vault().record_error(
                            ats=RE.ats_of(job["url"])[0], domain=urllib.parse.urlparse(job["url"]).netloc.lower(),
                            url=job["url"], step=0, selector="", label=f"{job['company']} - {job['role']}",
                            error_type=f"exit_code_{ret}", details=f"Job exited with code {ret} after {dur}s")
                    except Exception as e:
                        print(f"[{w_prefix}] brain failure feedback failed: {e}")

                # Periodic brain auto-tune, as the single-worker runner did
                with state_lock:
                    if ret == 0 and completed_this_session % 5 == 0:
                        try:
                            from brain.auto_tuner import AutoTuner
                            tuned = AutoTuner().tune_all()
                            if tuned.get("patches_applied"):
                                print(f"[{w_prefix}]   [Agent Brain] Auto-tuned: {len(tuned['patches_applied'])} patches applied.")
                        except Exception as e:
                            print(f"[{w_prefix}] auto-tune failed: {e}")

            except subprocess.TimeoutExpired:
                print(f"[{w_prefix}] WATCHDOG TIMEOUT: {job['company']} exceeded {job_timeout}s. Terminating worker child process.")
                sk = RE.site_key(job["url"])
                try:
                    from agents import smarts
                    smarts.site_record(job["url"], "timeout", time.time() - t0)
                except Exception as e:
                    print(f"[{w_prefix}] site_record failed: {e}")
                RE.ledger_add(job["company"], job["role"], job["url"], "timeout")
                with state_lock:
                    site_failures[sk] = site_failures.get(sk, 0) + 1
            except Exception as ex:
                print(f"[{w_prefix}] Worker error: {ex}")
            finally:
                if c_norm:
                    with state_lock:
                        active_companies.discard(c_norm)

            if not stop_flag:
                time.sleep(random.uniform(args.delay, args.delay + 1.5))

    # Spawn isolated worker threads
    threads = []
    print(f"[Parallel Runner] Launching {num_workers} concurrent browser workers...")
    for w_id in range(1, num_workers + 1):
        t = threading.Thread(target=worker_loop, args=(w_id,), daemon=True)
        threads.append(t)
        t.start()
        if w_id < num_workers:
            # Stagger startup to prevent thundering herd
            time.sleep(1.5)

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Parallel Runner] Interrupted by user. Terminating all active browser processes...")
        stop_flag = True
        kill_all_workers()

    final_count = get_applied_count()
    print("\n" + "=" * 68)
    print("      PARALLEL BATCH EXECUTION COMPLETE")
    print(f"  Verified Submissions in applications.csv: {final_count} / {args.target}")
    print(f"  Submitted this session:                   +{completed_this_session}")
    print(f"  Total attempts run:                       {attempts}")
    if final_count >= args.target:
        print(f"  STATUS: TARGET OF {args.target} APPLICATIONS REACHED! EXCELLENT WORK.")
    else:
        print(f"  STATUS: {args.target - final_count} more submissions needed to hit milestone {args.target}.")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
