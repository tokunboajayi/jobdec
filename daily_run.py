"""
Agent 7 - Coordinator. Runs the whole pipeline once, in order, with no prompts, then writes a briefing.

    python daily_run.py                 # full run
    python daily_run.py --no-apply      # everything except submitting applications
    python daily_run.py --dry-run       # read-only: show what would happen, change nothing

Steps:
  1. Inbox Analyst     - read replies, update results.csv, list urgent actions
  2. Job sources       - add new SimplifyJobs postings (<= 14 days old) to queue.txt
  3. Job Scout+triage  - score with the full job description, write queue_ranked.txt
  4. Batch apply       - best fit first, tailored resume per job, stops at the daily cap
  5. Site Fixer        - turn today's failures into rules / tested code fixes
  6. Outreach Drafter  - LinkedIn note drafts for today's strong applications (never sent)
  7. Briefing          - briefings/<date>.md
"""
import argparse, datetime, json, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import results_engine as RE
from agents import llm, job_sources, site_fixer, outreach_drafter, inbox_analyst, smarts

BRIEF_DIR = HERE / "briefings"


def step(name, fn, report):
    print(f"\n=== {name} ===", flush=True)
    try:
        out = fn()
        report[name] = out
        print(f"[{name}] {out if not isinstance(out, (dict, list)) or len(str(out)) < 300 else 'done'}", flush=True)
    except Exception as e:
        report[name] = f"ERROR: {type(e).__name__}: {e}"
        print(f"[{name}] ERROR: {e}", flush=True)


def run_py(args):
    r = subprocess.run([sys.executable, "-u", *args], cwd=str(HERE))
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-age", type=int, default=14, help="newest postings only (days)")
    a = ap.parse_args()
    cfg = llm.config()
    report = {}
    print(f"Agents: {'AI (Claude API)' if llm.engine('job_scout') == 'ai' else 'rule-based (no API key needed)'}; "
          f"budget ${cfg['daily_budget_usd']}/day, spent ${llm.spent_today():.2f}")

    if a.dry_run:
        jobs = job_sources.fetch(a.max_age)
        print(f"[dry-run] {len(jobs)} fresh US postings on SimplifyJobs; queue has {len(RE.parse_queue_file(HERE / 'queue.txt'))} lines")
        print(f"[dry-run] submitted today: {RE.submitted_today()} / cap {RE.strategy()['daily_cap']}")
        print("[dry-run] nothing changed.")
        return

    step("1 inbox", lambda: run_py(["outcomes.py", "--since", (datetime.date.today() - datetime.timedelta(days=30)).isoformat()]), report)
    step("1b prep packs", lambda: smarts.build_prep_packs(), report)
    step("1c learning", lambda: smarts.learner_train(), report)
    step("2 sources", lambda: job_sources.add_new(a.max_age), report)
    step("3 triage", lambda: run_py(["triage.py", "--scout"]), report)
    if not a.no_apply:
        step("4 apply", lambda: run_py(["batch_apply.py", "--queue", "queue_ranked.txt"]), report)
    step("5 site fixer", lambda: site_fixer.run(), report)
    step("6 outreach", lambda: outreach_drafter.run_for_today(), report)
    step("6b follow-ups", lambda: outreach_drafter.followups(), report)
    write_briefing(report)


def write_briefing(report):
    today = datetime.date.today().isoformat()
    rows = [r for r in RE.ledger_rows() if r["date"] == today]
    sub = [r for r in rows if r["status"] == "submitted"]
    fx = report.get("5 site fixer") if isinstance(report.get("5 site fixer"), dict) else {}
    drafts = report.get("6 outreach") if isinstance(report.get("6 outreach"), list) else []
    lines = [f"# Daily briefing - {today}", "",
             f"**Submitted {len(sub)}** of {len(rows)} attempted (cap {RE.strategy()['daily_cap']}). "
             f"AI spend today: ${llm.spent_today():.2f} / ${llm.config()['daily_budget_usd']}.", ""]
    actions = inbox_analyst.open_actions()
    lines += ["## Needs you (inbox)"] + (actions or ["- nothing urgent"]) + [""]
    due = smarts.deadlines_soon(7)
    if due:
        lines += ["## Application deadlines in the next 7 days (not applied yet)"] + [f"- {d}" for d in due] + [""]
    preps = report.get("1b prep packs") if isinstance(report.get("1b prep packs"), list) else []
    if preps:
        lines += ["## New interview / assessment prep sheets"] + [f"- {p}" for p in preps] + [""]
    fups = report.get("6b follow-ups") if isinstance(report.get("6b follow-ups"), list) else []
    if fups:
        lines += ["## Follow-ups to send (7 days, no reply)"] + [f"- **{r['company']}**: {r['followup']}" for r in fups] + [""]
    if fx.get("retries"):
        lines += ["## Retrying (a new rule answers what blocked them)"] + [f"- {r}" for r in fx["retries"]] + [""]
    learn = report.get("1c learning")
    if isinstance(learn, str) and not learn.startswith("ERROR"):
        lines += [f"_{learn}_", ""]
    if datetime.date.today().weekday() == 6:
        lines += ["## Weekly review", smarts.weekly_review(), ""]
    lines += ["## Submitted today"] + ([f"- {r['company']} - {r['role']} (fit {r['fit_score']}, {r['category']})" for r in sub] or ["- none"]) + [""]
    if fx.get("needs_you"):
        lines += ["## Questions only you can answer (jobs skip these until you add a rule)"] + fx["needs_you"] + [""]
    if fx.get("rules_added") or fx.get("code_fixes"):
        lines += ["## Site Fixer"] + [f"- rule added: {r}" for r in fx.get("rules_added", [])]
        lines += [f"- code fix {'APPLIED' if c['applied'] else 'rejected'}: {c['why']}" for c in fx.get("code_fixes", [])] + [""]
    if drafts:
        lines += ["## LinkedIn drafts (not sent - open the search link, pick a person, paste the note)"]
        lines += [f"- **{d['company']}** ({d['look_for']}): {d['linkedin_search']}\n  > {d['note']}" for d in drafts] + [""]
    errors = [f"- {k}: {v}" for k, v in report.items() if isinstance(v, str) and v.startswith("ERROR")]
    if errors:
        lines += ["## Errors"] + errors + [""]
    BRIEF_DIR.mkdir(exist_ok=True)
    out = BRIEF_DIR / f"{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nBriefing saved: {out.relative_to(HERE)}")


if __name__ == "__main__":
    main()
