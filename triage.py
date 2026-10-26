"""
Triage a queue: score every job for fit, drop duplicates / already-applied / ineligible roles,
route protected companies to manual, and order the rest best-first (fit, then ATS completion rate).

    python triage.py                       # queue.txt -> queue_ranked.txt (queue.txt is not touched)
    python triage.py --in queue_phase2.txt --out queue_ranked.txt --min-score 6

Then run:  python batch_apply.py --queue queue_ranked.txt
Thresholds and company lists live in strategy.json.
"""
import argparse, collections, pathlib
import results_engine as RE

HERE = pathlib.Path(__file__).resolve().parent


def scout_jobs(jobs, applied, min_score):
    """Run the Job Scout on jobs the title rules didn't already rule out (results are cached)."""
    from concurrent.futures import ThreadPoolExecutor
    from agents import job_scout, llm
    eng = llm.engine("job_scout")
    if eng == "off":
        print("[Job Scout] off in strategy.json - using title rules")
        return
    todo = []
    for j in jobs:
        if j["hold"] or RE.is_protected(j["company"]) or RE.job_key(j["company"], j["role"], j["url"]) in applied:
            continue
        hit = job_scout.cached(j["company"], j["role"], j["url"])
        if hit and not (hit.get("engine") == "local" and eng == "ai"):
            continue
        score, cat, _ = RE.score_job(j["company"], j["role"], j["url"])
        if cat != "ineligible" and score >= min_score - 2:
            todo.append(j)
    todo = todo[: llm.config()["scout_limit_per_run"]]
    print(f"[Job Scout] reading {len(todo)} job descriptions ({'AI' if eng == 'ai' else 'rule-based, free'})...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        done = list(ex.map(lambda j: job_scout.scout(j["company"], j["role"], j["url"]), todo))
    print(f"[Job Scout] scored {sum(1 for d in done if d)} / {len(todo)} (spent today ${llm.spent_today():.2f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="queue.txt")
    ap.add_argument("--out", default="queue_ranked.txt")
    ap.add_argument("--min-score", type=float, default=None, help="default: strategy.json min_fit_score")
    ap.add_argument("--scout", action="store_true", help="Agent 1: read full job descriptions and score with AI (cached)")
    ap.add_argument("--check-live", action="store_true", default=True, help="Pre-flight check: filter closed/expired job postings")
    a = ap.parse_args()
    min_score = a.min_score if a.min_score is not None else RE.strategy()["min_fit_score"]

    jobs = RE.parse_queue_file(HERE / a.inp)
    applied = RE.already_applied_keys()
    if a.scout:
        scout_jobs(jobs, applied, min_score)
    seen = set()
    run, manual, held, skipped = [], [], [], []
    for j in jobs:
        key = RE.job_key(j["company"], j["role"], j["url"])
        score, cat, why = RE.score_job(j["company"], j["role"], j["url"])
        ats, _ = RE.ats_of(j["url"])
        tag = f"{j['company']} {j['role']}   {j['url']}"
        if key in applied:
            skipped.append(("already applied", tag)); continue
        if key in seen:
            skipped.append(("duplicate posting", tag)); continue
        seen.add(key)
        if j["hold"]:
            held.append(j["line"]); continue
        if RE.is_protected(j["company"]):
            manual.append(f"# MANUAL (protected company - apply by hand) fit {score}: {tag}"); continue
        if cat == "ineligible":
            skipped.append((why[-1], tag)); continue
        if score < min_score:
            skipped.append((f"fit {score} < {min_score} ({cat})", tag)); continue
        try:
            import urllib.parse
            from brain.vault import get_vault
            dom = urllib.parse.urlparse(j["url"]).netloc.lower()
            if get_vault().is_fast_fail(dom):
                skipped.append((f"fast_fail_domain ({dom})", tag)); continue
        except Exception:
            pass
    if a.check_live and run:
        try:
            from agents import job_validator
            print(f"[Triage Validator] Pre-checking {len(run)} candidate postings for live status...")
            jobs_to_check = [{"company": t.split()[0], "role": t.split()[1], "url": t.split()[-1]} for _, _, _, _, t in run]
            active, closed = job_validator.filter_active_jobs(jobs_to_check, max_workers=10)
            active_urls = {j["url"] for j in active}
            new_run = [item for item in run if item[4].split()[-1] in active_urls]
            for c_job, c_reason in closed:
                skipped.append((f"closed_posting ({c_reason})", f"{c_job['company']} {c_job['role']}   {c_job['url']}"))
            print(f"[Triage Validator] {len(new_run)} active jobs verified, {len(closed)} dead postings filtered.")
            run = new_run
        except Exception as e:
            print(f"[Triage Validator] Warning: pre-check encountered {e}; proceeding without filter.")

    run.sort(key=lambda x: (-x[0], x[1]))
    out = [f"# Ranked by triage.py - {len(run)} to run (best fit first, easiest ATS first within a score).",
           "# Edit strategy.json to change min score, protected companies or target companies.", ""]
    out += [f"# fit {s} | {c} | {at}\n{t}" for s, _, c, at, t in run]
    if held:
        out += ["", "# ---- HELD (waiting on your decision - remove the note to release)"] + held
    if manual:
        out += ["", "# ---- PROTECTED: apply by hand"] + manual
    out += ["", "# ---- SKIPPED"] + [f"# SKIP ({why}): {t}" for why, t in skipped]
    (HERE / a.out).write_text("\n".join(out) + "\n", encoding="utf-8")

    cats = collections.Counter(c for _, _, c, _, _ in run)
    atss = collections.Counter(at for _, _, _, at, _ in run)
    reasons = collections.Counter(w.split(" (")[0] if w.startswith("fit") else w for w, _ in skipped)
    print(f"Read {len(jobs)} jobs from {a.inp}")
    print(f"  to run : {len(run)}  {dict(cats)}")
    print(f"           by ATS {dict(atss)}")
    print(f"  manual : {len(manual)} (protected companies)")
    print(f"  held   : {len(held)}")
    print(f"  skipped: {len(skipped)}  {dict(reasons)}")
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
