# Prompt: reorganize the jobdec repo (behavior must not change)

Paste everything below the line into a coding agent (Claude Code, or the wai-harness `wai-overhaul` skill) opened in
`C:\Users\RecoveryAdmin\OneDrive\Documents\LinkedIn Outreach\Job Applications\autofill`. Run it only after the
`wai/overhaul-20261110` branch is merged, and while the pipeline is stopped.

---

You are reorganizing a working Python job-application pipeline ("jobdec"). The goal is a repo a new reader can
understand in 10 minutes. **The behavior must not change**: same commands, same outputs, same tests passing.
Reorganizing is moving and renaming, not rewriting.

## What the project is
- `run_until_target.py` → `batch_apply_parallel.py` → `fill.py` (Playwright, one process per job) fills and submits
  internship applications. `triage.py` ranks `queue.txt`. `results_engine.py` scores jobs and keeps ledgers.
- `agents/` holds helpers (job sources, resume tailor, form answering, outcome learning, site fixer, Telegram helpers).
- `brain/` holds the knowledge graph, error vault and resolvers. `dashboard/` is a local status page.
- `candidate.py` decides whose data is used: `JOBDEC_HOME=profiles/<name>` selects a person's `.env`,
  `profile.json`, `resumes/`, ledgers and caches. With nothing set, the owner's original layout is used.
- Telegram bot: `telegram_bot_service.py`, `telegram_query_engine.py`, `telegram_notify.py`.

## Hard rules
1. Never change what an application answers or uploads. No edits to answer logic, option matching or upload rules.
2. No person's name, school, address, phone, email or employer may appear in code, tests or docs. Person data
   lives only in a candidate home (`profiles/<name>/` or the owner's legacy files). `profiles/*` stays gitignored.
3. Don't touch `profile.json`, any `.env`, `applications.csv`, `results.csv`, `records/`, `resumes/` or queue
   files, other than moving code that reads them. Never print secret values.
4. Don't expand `brain/stealth_engine.py`. Add no CAPTCHA or bot-detection evasion.
5. Never force push, rewrite history or change GitHub settings. Work on a branch `chore/reorganize-<date>`.
6. Run no live applications. Verify only with tests and `--help` and dry runs.

## Steps
1. **Baseline.** `python -m pytest tests -q -p no:cacheprovider` and save the pass/fail list. Also run
   `python run_until_target.py --help`, `python batch_apply_parallel.py --help`, `python fill.py --help` and
   `python triage.py --help` and save their output. These must match at the end.
2. **Inventory.** List every top-level file with a one-line purpose and who imports it (`git grep -l "import <mod>"`).
   Mark each as entrypoint, library, script, data, doc or dead. Something is dead only if nothing imports it, no
   `.bat`/`.ps1`/README mentions it, and no test uses it.
3. **Proposed layout** (adjust to the inventory; keep the entrypoints at the top level so existing `.bat` files and
   habits keep working):
   ```
   autofill/
     run_until_target.py  batch_apply_parallel.py  fill.py  triage.py  daily_run.py   (entrypoints stay)
     candidate.py  results_engine.py                                                  (core)
     agents/        brain/        dashboard/
     telegram/      (bot service, query engine, notify; leave thin top-level shims that import from here)
     tools/         (one-off scripts: setup, migrations, probes)
     docs/          (AGENTS.md, RESULTS_ENGINE.md, design notes, REVIEW.md, OVERHAUL_LEDGER.md)
     tests/         fixtures/
     profiles/README.md   .env.example   requirements.txt   README.md
   ```
   Write the plan as a table (old path → new path → reason) and stop for approval before moving anything.
4. **Move in small commits**, one group per commit, using `git mv` so history follows each file. After each group:
   update its imports, leave a shim at the old path if anything outside the repo (a `.bat`, Task Scheduler, a habit)
   might call it, then run the full tests. Red means revert that commit and rethink.
5. **Dead code.** Move each dead file to `attic/` in a single commit; don't delete it. List them so the owner can
   decide later.
6. **Clutter.** Untrack and gitignore any generated files, backups (`*.bak*`, `*.backup*`), logs, caches and
   ledgers you find tracked. Confirm `git ls-files -ci --exclude-standard` prints nothing.
7. **README.md.** Cover what it does, setup (`pip install -r requirements.txt`, `playwright install chromium`), how
   to add a candidate (`profiles/README.md`), how to run, where logs and records go, and how to run tests. Then follow
   your own README from a clean clone and fix every step that doesn't work.
8. **Prove it.** Re-run the baseline from step 1. Tests: same or better. `--help` output: identical. Grep for
   person data (names, schools, phone patterns, emails) in tracked files: none.

## Hand back
The layout table, the commits, test results before and after, the `attic/` list, and anything you chose not to
move, with the reason.
