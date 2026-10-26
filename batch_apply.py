"""
Batch Autonomous Job Application Runner.
Reads queue.txt, applies to jobs sequentially in headless mode (zero UI),
handles account creation and logins automatically, and logs results to applications.csv.
"""
import json, os, argparse
import pathlib
import re
import subprocess
import sys
import time

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

try:
    import results_engine as RE  # fit scoring, protected companies, daily cap, results ledger
except ImportError:
    RE = None

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
QUEUE_FILE = HERE / "queue.txt"
# A queue line with a note like "(AJ: pick ...)", "(... OK relocation first)" or "(confirm ... first)"
# is waiting on a decision. It's held unless you pass --include-held (or delete the note).
HOLD_RE = re.compile(r"\((?=[^)]*(?<![A-Za-z])(?:AJ|first|confirm|OK)(?![A-Za-z]))[^)]*\)", re.I)


def run_logged(cmd, timeout, stdin, log_path, prefix="", procs_list=None, procs_lock=None):
    """Like subprocess.run, but also copies the job's output to records/<date>/<job>.log (site fixer input)."""
    import threading
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="ignore") as log:
        proc = subprocess.Popen(cmd, cwd=str(HERE), stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="ignore")
        if procs_list is not None and procs_lock is not None:
            with procs_lock:
                procs_list.append(proc)
        def pump():
            if proc.stdout is not None:
                for line in proc.stdout:
                    msg = f"[{prefix}] {line}" if prefix else line
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
            import subprocess as sp
            try:
                sp.run(f"taskkill /F /T /PID {proc.pid}", shell=True, capture_output=True)
            except Exception:
                proc.kill()
            t.join(3)
            raise
        finally:
            if procs_list is not None and procs_lock is not None:
                with procs_lock:
                    if proc in procs_list:
                        procs_list.remove(proc)
        t.join(5)
    return proc


def parse_queue():
    if not QUEUE_FILE.exists():
        print(f"Queue file not found: {QUEUE_FILE}")
        return []

    entries = []
    lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue

        # Look for URL in the line
        m = re.search(r'(https?://[^\s]+)', raw)
        if not m:
            continue

        url = m.group(1)
        prefix = raw[:m.start()].strip()
        suffix = raw[m.end():].strip()

        hold = HOLD_RE.search(prefix)
        prefix = HOLD_RE.sub("", prefix).strip()

        # Company and role from prefix
        company = prefix.split()[0] if prefix else ""
        role = " ".join(prefix.split()[1:]) if len(prefix.split()) > 1 else ""

        # Resume from suffix
        resume = suffix if suffix and (ROOT / suffix).exists() else None

        entries.append({
            "line": raw,
            "company": company,
            "role": role,
            "url": url,
            "resume": resume,
            "hold": hold.group(0) if hold else None,
        })

    return entries


def main():
    import threading
    parser = argparse.ArgumentParser(description="Run headless batch applications from queue.txt")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of applications to run in this batch (default: 500)")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel worker processes to run (default: 1)")
    parser.add_argument("--resume", default="resumes/master_resume.pdf", help="Resume to use for all applications")
    parser.add_argument("--use-tailored", action="store_true", help="Use tailored resume from queue.txt if present instead of master resume")
    parser.add_argument("--include-held", action="store_true", help="Also run queue lines that have a pending-decision note")
    parser.add_argument("--headful", action="store_true", help="Force browser window visible instead of headless")
    parser.add_argument("--timeout", type=int, default=260, help="Per-job timeout in seconds (default: 260s)")
    parser.add_argument("--delay", type=int, default=3, help="Delay between jobs in seconds (default: 3s)")
    parser.add_argument("--queue", default="queue.txt", help="Queue file (e.g. queue_ranked.txt from triage.py)")
    parser.add_argument("--daily-cap", type=int, default=None, help="Max submissions per day (default: strategy.json daily_cap)")
    parser.add_argument("--no-triage", action="store_true", help="Apply to everything: ignore fit score, protected companies and daily cap")
    args = parser.parse_args()
    lock_file = HERE / ".batch_apply.lock"
    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            out = subprocess.check_output(f'tasklist /FI "PID eq {old_pid}"', shell=True, text=True)
            if str(old_pid) in out and "python" in out.lower():
                print(f"[Batch Apply] Another batch_apply process (PID {old_pid}) is already running. Exiting.")
                return
        except Exception:
            pass
    lock_file.write_text(str(os.getpid()))
    import atexit
    atexit.register(lambda: lock_file.unlink(missing_ok=True))

    global QUEUE_FILE
    QUEUE_FILE = HERE / args.queue
    strat = RE.strategy() if RE else {}
    daily_cap = args.daily_cap if args.daily_cap is not None else strat.get("daily_cap", 10**6)

    jobs = parse_queue()
    retry_file = HERE / "queue_retry.txt"
    if retry_file.exists():
        try:
            r_lines = [l.strip() for l in retry_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            if r_lines:
                print(f"[Batch Apply] Found {len(r_lines)} self-healed job(s) in queue_retry.txt - prioritizing retries!")
                retry_entries = []
                for raw in r_lines:
                    m = re.search(r'(https?://[^\s]+)', raw)
                    if m:
                        url = m.group(1)
                        prefix = raw[:m.start()].strip()
                        comp = prefix.split()[0] if prefix else ""
                        rl = " ".join(prefix.split()[1:]) if len(prefix.split()) > 1 else ""
                        retry_entries.append({"line": raw, "company": comp, "role": rl, "url": url, "resume": None, "hold": None, "is_retry": True})
                jobs = retry_entries + jobs
        except Exception:
            pass
    if not args.include_held:
        jobs = [j for j in jobs if not j.get("hold")]
    if not jobs:
        print("[Batch Apply] No active jobs found in queue.")
        return

    # Filter out jobs already recorded as Applied in applications.csv
    applied_urls = set()
    applied_pairs = set()
    csv_file = ROOT / "applications.csv"
    if csv_file.exists():
        import csv
        try:
            with open(csv_file, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("Stage") == "Applied":
                        if row.get("Job URL"): applied_urls.add(row["Job URL"].strip())
                        if row.get("Company") and row.get("Role"):
                            applied_pairs.add((row["Company"].strip().lower(), row["Role"].strip().lower()))
        except Exception:
            pass

    workers_count = max(1, args.workers)
    print(f"\n==========================================")
    print(f"  AJ AUTONOMOUS APPLICATION PIPELINE")
    print(f"  Mode: {'VISIBLE UI' if args.headful else 'HEADLESS (ZERO UI)'}")
    print(f"  Workers: {workers_count} concurrent process(es)")
    print(f"  Resume: {args.resume if not args.use_tailored else 'tailored per job (from queue.txt)'}")
    print(f"  Found {len(jobs)} jobs in queue. Running up to {args.limit}...")
    print(f"==========================================\n")

    # Shared thread-safe state
    state_lock = threading.Lock()
    job_cursor = 0
    attempts = 0
    completed_count = 0
    stop_flag = False
    site_failures = {}

    active_procs = []
    procs_lock = threading.Lock()

    def kill_all_active():
        with procs_lock:
            for p in active_procs:
                try:
                    subprocess.run(f"taskkill /F /T /PID {p.pid}", shell=True, capture_output=True)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
    atexit.register(kill_all_active)

    def get_next_job(worker_id):
        nonlocal job_cursor, attempts, stop_flag
        tag = f"[W{worker_id}] " if workers_count > 1 else ""
        with state_lock:
            while not stop_flag and job_cursor < len(jobs):
                if attempts >= args.limit:
                    stop_flag = True
                    return None
                if RE and not args.no_triage:
                    if RE.submitted_today() >= daily_cap:
                        print(f"{tag}[Results Engine] Daily cap of {daily_cap} submissions reached - stopping.")
                        stop_flag = True
                        return None

                i = job_cursor
                job = jobs[job_cursor]
                job_cursor += 1

                # Check if already applied
                if job["url"] in applied_urls or (job["company"].lower(), job["role"].lower()) in applied_pairs:
                    print(f"{tag}[{i+1}/{len(jobs)}] Already applied to {job['company']} - {job['role']}. Skipping...")
                    continue

                # Triage & Smarts gates
                if RE and not args.no_triage:
                    score, cat, why = RE.score_job(job["company"], job["role"], job["url"])
                    if RE.is_protected(job["company"]):
                        print(f"{tag}[{i+1}] MANUAL: {job['company']} is a protected company - apply by hand. Skipping.")
                        continue
                    if score < strat.get("min_fit_score", 5.0):
                        print(f"{tag}[{i+1}] LOW FIT {score} ({cat}{': ' + why[0] if cat == 'ineligible' else ''}): {job['company']} - {job['role']}. Skipping.")
                        continue

                    # Agent Brain: Fast-Fail
                    try:
                        import urllib.parse
                        from brain.vault import get_vault
                        parsed_dom = urllib.parse.urlparse(job["url"]).netloc.lower()
                        if get_vault().is_fast_fail(parsed_dom):
                            print(f"{tag}[{i+1}] [Brain Fast-Fail] {parsed_dom} has known impassable auth barrier. Skipping.")
                            continue
                    except Exception:
                        pass

                    sk = RE.site_key(job["url"])
                    if sk in strat.get("skip_sites", []):
                        print(f"{tag}[{i+1}] {sk} is on the skip list - skipping.")
                        continue
                    if site_failures.get(sk, 0) >= strat.get("max_failures_per_site_per_run", 5):
                        print(f"{tag}[{i+1}] {sk} failed {site_failures[sk]}x this run - skipping site.")
                        continue

                    try:
                        from agents import smarts
                        ok, why_skip = smarts.should_attempt(job["company"], job["role"], job["url"])
                        if not ok:
                            print(f"{tag}[{i+1}] {job['company']} - {job['role']}: {why_skip}. Skipping.")
                            continue
                        if why_skip:
                            print(f"{tag}     {why_skip}")
                        if score >= 9:
                            from agents import outreach_drafter
                            if outreach_drafter.draft(job["company"], job["role"], score, job["url"], pre_apply=True):
                                print(f"{tag}     [Outreach] referral note drafted (see outreach_drafts.csv)")
                    except Exception as e:
                        print(f"{tag}     [smarts] {e}")

                # Tailor resume
                resume_to_use = (job["resume"] if (args.use_tailored and job["resume"]) else args.resume)
                try:
                    from agents import resume_tailor
                    resume_to_use = resume_tailor.tailor(job["company"], job["role"], job["url"], resume_to_use)
                except Exception as e:
                    print(f"{tag}     [Resume Tailor] skipped: {e}")

                # Pre-submit guard
                try:
                    from agents.supervisor import pre_submit_check
                    guard_fail = pre_submit_check(job["url"], job["company"], str(resume_to_use) if resume_to_use else "")
                    if guard_fail:
                        print(f"{tag}[{i+1}] [Pre-Submit Guard] {guard_fail}. Skipping.")
                        continue
                except Exception:
                    pass

                # Claim job atomically
                applied_urls.add(job["url"])
                if job["company"] and job["role"]:
                    applied_pairs.add((job["company"].lower(), job["role"].lower()))

                attempts += 1
                return (job, i + 1, attempts, resume_to_use)

            return None

    def worker_loop(worker_id):
        nonlocal completed_count
        w_tag = f"[W{worker_id}] " if workers_count > 1 else ""
        w_prefix = f"W{worker_id}" if workers_count > 1 else ""

        while not stop_flag:
            item = get_next_job(worker_id)
            if not item:
                break
            job, idx, attempt_num, resume_to_use = item

            print(f"\n{w_tag}[{idx}] Starting attempt {attempt_num}/{args.limit}: {job['company']} - {job['role']}")
            print(f"{w_tag}     URL: {job['url']}")
            print(f"{w_tag}     Resume: {resume_to_use}")

            # Quick pre-flight check to skip dead domains
            import urllib.request
            try:
                req = urllib.request.Request(job["url"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    pass
            except Exception as e:
                err_msg = str(e).lower()
                if "getaddrinfo failed" in err_msg or "not known" in err_msg or "http error 404" in err_msg:
                    print(f"{w_tag}[Batch Apply] Pre-flight skip: URL unreachable ({str(e)}). Advancing...")
                    continue

            cmd = [sys.executable, "-u", str(HERE / "fill.py"), job["url"]]
            if job["company"]: cmd.extend(["--company", job["company"]])
            if job["role"]: cmd.extend(["--role", job["role"]])
            if resume_to_use: cmd.extend(["--resume", str(resume_to_use)])
            if args.headful: cmd.append("--headful")
            else: cmd.append("--headless")
            if workers_count > 1: cmd.extend(["--worker-id", str(worker_id)])

            t0 = time.time()
            try:
                stdin_mode = None if args.headful else subprocess.DEVNULL
                log_path = (RE.RECORDS_DIR / time.strftime("%Y-%m-%d") / f"{RE._slug(job['company'], job['role'])}.log") if RE else HERE / "last_job.log"
                job_timeout = max(args.timeout, strat.get("ats_timeouts", {}).get(RE.ats_of(job["url"])[0], 0)) if RE else args.timeout
                try:
                    from agents import smarts
                    job_timeout = smarts.site_timeout(job["url"], job_timeout)
                except Exception:
                    smarts = None
                t0 = time.time()
                os.environ["AF_DEADLINE"] = str(job_timeout)

                res = run_logged(cmd, job_timeout, stdin_mode, log_path, prefix=w_prefix, procs_list=active_procs, procs_lock=procs_lock)
                dur = round(time.time() - t0, 2)

                if smarts:
                    smarts.site_record(job["url"], "submitted" if res.returncode == 0 else "not_submitted", dur)
                if RE:
                    RE.ledger_add(job["company"], job["role"], job["url"], "submitted" if res.returncode == 0 else "not_submitted")

                with state_lock:
                    if res.returncode == 0:
                        print(f"{w_tag}[Batch Apply] SUCCESS: {job['company']} submitted and logged to applications.csv!")
                        completed_count += 1
                        try:
                            r_file = HERE / "queue_retry.txt"
                            if r_file.exists():
                                cur_lines = [l for l in r_file.read_text(encoding="utf-8").splitlines() if job["url"] not in l]
                                r_file.write_text("\n".join(cur_lines) + ("\n" if cur_lines else ""), encoding="utf-8")
                        except Exception:
                            pass
                    else:
                        sk = RE.site_key(job["url"]) if RE else "other"
                        site_failures[sk] = site_failures.get(sk, 0) + 1
                        if res.returncode == 2:
                            print(f"{w_tag}[Batch Apply] SKIPPED: {job['company']} (site offline, blocked, or required missing inputs).")
                        else:
                            print(f"{w_tag}[Batch Apply] ERROR: {job['company']} exited with code {res.returncode}.")

                # Live self-healing
                if res.returncode != 0:
                    try:
                        from agents.supervisor import on_job_complete
                        heal_rec = {"company": job["company"], "role": job["role"], "url": job["url"], "status": "not_submitted"}
                        try:
                            rec_path = log_path.with_suffix(".json")
                            if rec_path.exists():
                                heal_rec = json.loads(rec_path.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                        heal_msg = on_job_complete(heal_rec, log_path)
                        if heal_msg:
                            print(f"{w_tag}     {heal_msg}")
                    except Exception as he:
                        print(f"{w_tag}     [Supervisor] heal callback error: {he}")

                # Agent Brain: Record outcome and periodic auto-tune
                try:
                    import urllib.parse
                    from brain.vault import get_vault
                    from brain.auto_tuner import AutoTuner
                    v = get_vault()
                    dom = urllib.parse.urlparse(job["url"]).netloc.lower()
                    if res.returncode == 0:
                        v.record_success(dom, answers_count=15, duration_sec=dur)
                    else:
                        v.record_error(
                            ats=RE.ats_of(job["url"])[0] if RE else "unknown",
                            domain=dom,
                            url=job["url"],
                            step=0,
                            selector="",
                            label=f"{job['company']} - {job['role']}",
                            error_type=f"exit_code_{res.returncode}",
                            details=f"Job exited with code {res.returncode} after {dur}s"
                        )
                    with state_lock:
                        if completed_count > 0 and completed_count % 5 == 0:
                            tuned = AutoTuner().tune_all()
                            if tuned.get("patches_applied"):
                                print(f"{w_tag}     [Agent Brain] Auto-tuned: {len(tuned['patches_applied'])} patches applied.")
                except Exception:
                    pass

            except subprocess.TimeoutExpired:
                print(f"{w_tag}[Batch Apply Watchdog] {job['company']} exceeded {args.timeout}s timeout - advancing to next job.")
                try:
                    from agents import smarts
                    smarts.site_record(job["url"], "timeout", time.time() - t0)
                except Exception:
                    pass
                if RE:
                    RE.ledger_add(job["company"], job["role"], job["url"], "timeout")
                    with state_lock:
                        sk = RE.site_key(job["url"])
                        site_failures[sk] = site_failures.get(sk, 0) + 1
            except Exception as e:
                print(f"{w_tag}[Batch Apply] Error running job: {e}")

            if not stop_flag:
                import random
                jitter = random.uniform(args.delay, args.delay + 2.5)
                time.sleep(jitter)

    # Spawn worker threads
    threads = []
    for w_id in range(1, workers_count + 1):
        t = threading.Thread(target=worker_loop, args=(w_id,), daemon=True)
        threads.append(t)
        t.start()
        if w_id < workers_count:
            time.sleep(1.5)

    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[Batch Apply] Stopped by user. Terminating active workers...")
        stop_flag = True
        kill_all_active()

    print(f"\n[Batch Apply] Batch run complete. Truly submitted: {completed_count}/{attempts} attempted. Check applications.csv.")


if __name__ == "__main__":
    main()
