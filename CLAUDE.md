# jobdec

Automated internship-application pipeline for one candidate at a time (the owner by default), with a Telegram bot to control it.

## Commands
- Install: `pip install -r requirements.txt` then `playwright install chromium`
- Test: `python -m pytest tests -q -p no:cacheprovider` (tests run as a throwaway candidate, see `tests/conftest.py`)
- Lint: `python -m py_compile <changed .py files>` (no linter configured)
- Run pipeline: `run_pipeline.bat` (log: `logs/runner_<date>.log`). Bot: `python telegram_bot_service.py`
- Learning report: `python -m agents.learning_report` -> `learning_report.md`

## Rules
- Work is not done until a fresh `wai-verifier` run passes the test command above.
- Every review includes a live pass: watch the running bot's terminal, tail `batch_apply.log` and `logs/runner_*.log`, check the processes are alive, read fresh `records/<date>/`. Report live errors first.
- Never submit a guessed answer. No fact, no answer: the job is skipped. Never pick a first/default option.
- Internships only (`strategy.json` `internships_only`). Never loosen without asking the owner.
- Never run live applications while testing; tests must not write live ledgers or send Telegram messages.
- A Telegram message may only preview an application; launching needs the owner's button tap.
- Job Deck never takes online assessments for the candidate.
- Never read, edit, print or commit `.env`, tokens or keys. Don't edit `profile.json`, `applications.csv`, `results.csv`, queues or `records/` without backing them up first and saying so.
- Person data lives only in a candidate home (`candidate.py`, `profiles/<id>/`), never in code, tests or docs. The repo is public.
- No CAPTCHA solving or bot-detection evasion; don't expand `brain/stealth_engine.py`. LinkedIn messages are drafts only.
- Commit or push only when the owner asks. No force push, no history rewrite.
- Small diffs; don't rewrite working code for taste. On Windows, edit with the Edit tool (shell heredocs mangle `\b`).

## Skill routing
| Task | Use |
|---|---|
| Review everything | `wai-full-review` |
| Fix findings and prove it | `wai-overhaul`, then `wai-verifier` |
| Single change review | `code-review` |
| Security (Telegram, secrets, inputs) | `wai-security-review`, `security-review` |
| Bug with unknown cause | `wai-incident`, `pstack:why` |
| Tests | `testing-strategy`, `pstack:tdd` |
| LLM calls (OpenRouter, prompts, cost) | `wai-ai-engineer`, `wai-library` (`token-cost-control`) |
| Structure / reorganize | `architecture`, `wai-architect`, `REORGANIZE_PROMPT.md` |
| Smallest working change | `ponytail` |

## Token budget
- Filter tool output before reading it; do not paste whole files into the conversation.
- Use subagents only for independent branches.

## Knowledge
- Vault project slug: `jobdec`. Start workflows with `vault.py stale jobdec` and `vault.py context jobdec`.
- Decisions and findings go in the vault; notes marked stale are hints, not facts.

## Project notes
- `run_until_target.py` -> `batch_apply_parallel.py` (workers) -> `fill.py` (Playwright, one process per job).
- Every job passes `results_engine.score_job` (internship gate, exclusions, category weights in `strategy.json`).
- Answers: `profile.json` rules -> `agents/options.py` -> `agents/intelligent_resolver.py` (OpenRouter, `agents/openrouter.py`) -> fallbacks that return nothing rather than guess.
- Outcomes: `outcomes.py` reads Gmail (read-only); an email labels only the application whose role it names.
- Learning design: `LEARNING_DESIGN.md`. The learner changes job order only, never answers.
