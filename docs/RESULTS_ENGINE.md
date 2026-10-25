# Results Engine - handoff (2026-10-14)

Goal: optimize for **interviews**, not submission count. The 10/13-14 overnight run proved the
automation works, but ~half of its submissions were software-engineering roles that don't match AJ's
PM / analyst / AI resume. Only ~10% of queued jobs completed, answers weren't visible, and sign-in
retries locked AJ's Cox and Invesco accounts. This layer fixes those five problems without changing
how forms get filled.

## Files

| File | Purpose |
|---|---|
| `results_engine.py` | Shared logic: fit scoring, ATS ordering, dedupe keys, sensitive-question guard, answer records, account guard, results ledger |
| `strategy.json` | All tunables (created on first run). Edit this, not code |
| `triage.py` | Scores a queue -> writes `queue_ranked.txt` (best fit first, easiest ATS first). Never edits `queue.txt` |
| `outcomes.py` | Scans Gmail (read-only) for confirmations / rejections / assessments / interviews -> `outcomes_report.md` |
| `results.csv` | Ledger: one row per batch attempt (date, company, role, ats, category, fit, status, response) |
| `records/<date>/<company>_<role>.json` | Every answer given on that application, tagged `rule` / `guess` / `code` |
| `auth_state.json` | Per-site sign-in successes/failures (account lockout guard) |

Hooks added to existing files (all marked with `RE.` / `results_engine`):
- `fill.py`: records every answer; refuses to *guess* on sensitive questions (skips the job instead);
  account guard before sign-in; writes the record at the end of each run.
- `batch_apply.py`: `--queue`, `--daily-cap`, `--no-triage`; skips protected companies and low-fit roles;
  stops retrying a site after repeated failures in a run; writes `results.csv`.

## Daily workflow

```
python triage.py                                   # queue.txt -> queue_ranked.txt
python batch_apply.py --queue queue_ranked.txt     # stops at daily_cap (25)
python outcomes.py                                 # weekly: what's getting responses?
```

## The five fixes

1. **Targeting** - `score_job()`: base 3 + category weight (product 4, AI/analyst/business-systems 3,
   consulting/finance 2, SWE 0) + target company 1.5 + Atlanta/remote 1.5 + summer-2027 0.5.
   Ineligible = 0 (grad-only, high school, long co-ops, new grad / full-time / "Engineer I").
   Runs only `>= min_fit_score` (6). On the 550-job queue: 232 run, 312 skipped (mostly SWE), 6 manual.
   Queue titles are truncated (~25 chars), so classification also reads the job title from the URL.
2. **Throughput** - Greenhouse/Lever/Ashby run before Workday at equal fit; Workday sites where an
   account already works get a boost. Duplicate postings (same requisition, different page) are dropped.
   After `max_failures_per_site_per_run` (2) failures, the rest of that site is skipped for the run.
3. **Visibility** - every answer is saved per application. If a legal / eligibility / EEO question has
   no rule in `profile.json`, the job is **skipped and logged** instead of guessed
   (`block_sensitive_guesses`). Explicit rules are always used as-is. Fix by adding a rule, then rerun.
4. **Accounts** - after one failed sign-in on a site (`max_auth_failures_per_site`), it is never retried
   automatically. Protected companies (Cox, Invesco, BlackRock, Amex, Jane Street, Goldman, Delta,
   McKinsey) are never auto-applied - AJ applies by hand. To unlock a site: sign in by hand, then delete
   its entry from `auth_state.json`.
5. **Measurement** - `outcomes.py` reports response rate by channel (auto vs manual) and category.
   Baseline on 10/14: manual 15 applied / 8 responses / 3 positive; auto 14 applied / 0 so far (1-2 days old).
   Re-check weekly; after 2-3 weeks shift `category_weights` toward what produces interviews.

## Rules for whoever works on this next

- Don't remove the hooks to "unblock" a run. If a job skips on a sensitive question, add a rule to `profile.json`.
- Don't raise `max_auth_failures_per_site` - that's what locked Cox and Invesco.
- Change behavior through `strategy.json`. Keep `results.csv` and `records/` - they're the evidence base.
- `outcomes.py` must stay read-only on Gmail and must not modify `applications.csv`.
- Test against local mock pages. Real submissions only through the batch with a triaged queue.

## Known gaps / next steps

- The SimplifyJobs harvester truncates role titles to ~25 chars - fix it to keep full titles (better scoring).
- `fill.py` still treats "form cleared with no inputs" as submitted; this can over-count.
  `outcomes.py` confirmation emails are the real check.
- Rule 130 in `profile.json` answers Gender = Male (explicit rule - used as-is). Confirm with AJ.
- The old batch (`batch_apply.py --limit 150` on the untriaged 550 queue) may still be running.
  Stop it and restart with `--queue queue_ranked.txt` to apply the new logic.

> **AI agents:** see `AGENTS.md` - seven Claude agents now sit on top of this engine (`python daily_run.py`).
