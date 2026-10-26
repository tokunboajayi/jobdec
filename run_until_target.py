"""
Autonomous Target Runner: Scales applications to target (default 3,000).
Orchestrates:
  1. Real-time submission tracking against applications.csv.
  2. Dynamic multi-source job ingestion (GitHub intern repos + ATS APIs).
  3. Triage & Fit scoring into queue_ranked.txt.
  4. Parallel multi-worker execution via batch_apply.py (--workers N).
  5. Continuous self-healing & brain auto-tuning.
"""
import argparse
import csv
import pathlib
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

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CSV_FILE = ROOT / "applications.csv"


def get_applied_count() -> int:
    """Counts verified applied submissions from applications.csv."""
    if not CSV_FILE.exists():
        return 0
    count = 0
    try:
        with open(CSV_FILE, encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                if row.get("Stage") == "Applied":
                    count += 1
    except Exception as e:
        print(f"[Tracker] Error reading {CSV_FILE}: {e}")
    return count


def run_ingestion():
    """Ingests fresh roles from multiple sources into queue.txt."""
    print("\n--- [Step 1: Multi-Source Job Ingestion] ---")
    try:
        from agents import job_sources
        added = job_sources.add_new_jobs_to_queue(max_age_days=60)
        print(f"[Ingestion] Added {added} fresh jobs to queue.txt.")
        return added
    except Exception as e:
        print(f"[Ingestion] Error: {e}")
        return 0


def run_triage():
    """Scores, gates, and ranks jobs from queue.txt into queue_ranked.txt."""
    print("\n--- [Step 2: Triage & Fit Ranking] ---")
    try:
        res = subprocess.run([sys.executable, "triage.py"], cwd=str(HERE), capture_output=True, text=True)
        print(res.stdout[-600:] if len(res.stdout) > 600 else res.stdout)
    except Exception as e:
        print(f"[Triage] Error: {e}")


def run_batch(workers: int, limit: int, target: int, queue_file: str = "queue_ranked.txt"):
    """Runs a batch of applications using the parallel multi-worker engine."""
    print(f"\n--- [Step 3: Multi-Worker Parallel Apply (Workers={workers}, Limit={limit}, Target={target})] ---")
    cmd = [
        sys.executable, "-u", "batch_apply_parallel.py",
        "--queue", queue_file,
        "--limit", str(limit),
        "--target", str(target),
        "--workers", str(workers),
    ]
    try:
        proc = subprocess.Popen(cmd, cwd=str(HERE))
        proc.wait()
    except KeyboardInterrupt:
        print("\n[Runner] Interrupted by user. Stopping batch.")
        raise


def main():
    parser = argparse.ArgumentParser(description="Autonomous Runner to reach application target milestone")
    parser.add_argument("--target", type=int, default=None, help="Goal number of total submitted applications (default: 3000 or baseline + target_new)")
    parser.add_argument("--target-new", type=int, default=300, help="Target number of NEW verified submissions in this session (default: 300)")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent browser workers (default: 3)")
    parser.add_argument("--batch-size", type=int, default=150, help="Applications attempted per cycle (default: 150)")
    args = parser.parse_args()

    start_time = time.time()
    initial_count = get_applied_count()
    effective_target = args.target if args.target is not None else (initial_count + args.target_new)
    if effective_target <= initial_count:
        effective_target = initial_count + (args.target_new or 300)

    print("================================================================")
    print("      AUTONOMOUS SCALE ENGINE: PARALLEL APPLICATOR RUNNER       ")
    print(f"  Target Milestone: {effective_target} verified submissions (+{effective_target - initial_count} new)")
    print(f"  Current Baseline: {initial_count} submissions logged in applications.csv")
    print(f"  Workers:          {args.workers} concurrent isolated instances")
    print("================================================================\n")

    cycle = 1
    while True:
        cur_count = get_applied_count()
        remaining = max(0, effective_target - cur_count)
        elapsed_min = (time.time() - start_time) / 60.0
        session_submitted = cur_count - initial_count

        print(f"\n========================================================")
        print(f"  CYCLE {cycle} STATUS REPORT")
        print(f"  Total Applied: {cur_count} / {effective_target} ({cur_count / effective_target * 100:.1f}%)")
        print(f"  Remaining: {remaining} needed")
        print(f"  Submitted This Session: +{session_submitted} (in {elapsed_min:.1f} min)")
        print(f"========================================================\n")

        if cur_count >= effective_target:
            print(f"\n*** TARGET OF {effective_target} APPLICATIONS ACHIEVED! ***")
            print(f"Total time elapsed: {elapsed_min / 60.0:.2f} hours.")
            break

        # Check ranked queue size
        ranked_file = HERE / "queue_ranked.txt"
        ranked_count = 0
        if ranked_file.exists():
            ranked_count = len([l for l in ranked_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")])

        print(f"[Runner] Current queue_ranked.txt has {ranked_count} jobs.")
        if ranked_count < 100:
            print("[Runner] Queue is low. Ingesting new roles...")
            run_ingestion()
            run_triage()
        else:
            print("[Runner] Ranked queue has ample supply. Proceeding to apply.")

        batch_limit = args.batch_size
        try:
            run_batch(workers=args.workers, limit=batch_limit, target=effective_target, queue_file="queue_ranked.txt")
        except KeyboardInterrupt:
            print("\n[Runner] Graceful exit requested. Saving state.")
            break

        # Refresh triage after each batch to re-rank fresh items
        run_triage()
        cycle += 1
        time.sleep(5)


if __name__ == "__main__":
    main()
