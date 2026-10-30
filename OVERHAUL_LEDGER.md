# Overhaul ledger — submissions fell from ~100/day to 10 (2026-10-29)

## Contract
- Runner process stays alive and logs to `logs/runner_<date>.log`
- Fresh postings are fetched every cycle; attempts go to jobs not already tried to death
- Closed postings are never attempted again
- No false answers (the 2026-10-28 answer gates stay)
- `python -m pytest tests -q` passes (baseline: 160 passed)

## Evidence (Oct 29 records, 366 attempts)
- 338 / 366 (92%) were URLs already attempted on earlier days; 150 of the 157 "closed" were repeats
- Ingestion: "Added 0 fresh jobs" since Oct 27, yet `job_sources.fetch(14)` finds 110 new, unqueued postings
- One c3.ai URL attempted 47 times (`results.csv`)
- Runner log ends 2026-10-28 19:42; no pipeline process running at 22:26 Oct 29

## Findings
| ID | Sev | Category | Where | Symptom | Root cause | Fix | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| F1 | High | logic | agents/smarts.py:221 `_after_last_fix` | Same failed jobs retried every cycle (92% repeats) | A failure only counted if newer than the last edit to fill.py/profile.json; constant edits (2 sessions + site fixer) reset every job's count | Count every failure; retries come only from `mark_retries` when a new rule answers the blocker | Fixed (verified) | Replay of 366 Oct 29 attempts: all 355 non-submits now skipped; `pytest tests/test_smarts.py` 7 passed |
| F2 | High | logic | agents/smarts.py `should_attempt` | 150 closed postings retried | Ledger stores closed as `not_submitted`; nothing marks a posting dead | Skip any job whose record says `closed` | Fixed (verified) | Replay: 166 closed postings -> `posting closed`; new test `test_should_attempt_never_retries_closed_posting` passes |
| F3 | High | logic | run_until_target.py ingestion gate | 0 new jobs since Oct 27 | Ingest only when ranked queue < 100; stale queue holds ~1460 | Ingest every cycle (it dedupes) | Fixed (verified) | Ingestion + triage run: ranked 617, attemptable 195 (fresh 0-2d postings first); skip check 29s for whole queue |
| F4 | High | deployment | terminal tab | Nothing running | Runner lived in a terminal tab that closed; no supervisor | Restarted 2026-10-29 in terminal tab "jobdec pipeline"; persistence (Task Scheduler) needs AJ's OK | Workaround | |
| F5 | Medium | env | laptop power | Workers froze 2:46–6:50 PM Oct 28 | Modern Standby | Needs AJ: sleep "Never" while plugged in | Needs user | |
| F6 | Medium | accounts | auth_state.json | 7% skipped by account guard | Sign-ins failed earlier | Needs AJ: sign in by hand, clear entries | Needs user | |
| F7 | Low | correctness | fill.py / ai_responder.py (Oct 28) | 7% skipped_unanswered | Intended: no guessed yes/no answers | Answer agents/needs_you.md | Won't fix (by design) | |

## Verification
- `python -m pytest tests -q`: 161 passed (160 before + 1 new)
- Backups: `agents/smarts.py.bak-20261029`, `run_until_target.py.bak-20261029`, `queue.backup_20261029.txt`
