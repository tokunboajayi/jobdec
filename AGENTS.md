# AI Agents - handoff (2026-10-14)

Seven agents built on the Claude API, layered on top of the results engine (`docs/RESULTS_ENGINE.md`).
**Agents decide, code acts:** agents return validated structured data; `fill.py` / `batch_apply_parallel.py` still do
all the browser work. Everything runs with no human approval, except LinkedIn messages, which are drafted, never sent.

## Two engines - no API key required

Every agent has two versions, chosen automatically per run (`strategy.json` -> `agents.engine`):

| engine | when | cost | how it works |
|---|---|---|---|
| **local** (default today) | no `ANTHROPIC_API_KEY`, or `"engine": "local"` | free | `agents/local.py`: keyword matching of the full job description against the resume, deadline / time patterns in emails, fact lookups for form questions, note templates |
| **ai** | `ANTHROPIC_API_KEY` set and `"engine": "auto"` | ~$1-3/day, capped | Claude models below; rule-based results cached earlier get re-scored by AI |

Rule-based mode does everything except write code fixes (site fixer step B is AI-only).

## Setup (once)

1. `pip install reportlab` - needed for tailored resume PDFs (without it, the standard resume is used).
2. Optional, for the AI engine: add `ANTHROPIC_API_KEY=...` to `LinkedIn Outreach/.env`.
3. Optional: Windows Task Scheduler -> daily -> run `daily_run.bat`.

## Daily run

```
python daily_run.py              # inbox -> new jobs -> scout -> apply -> fix -> drafts -> briefing
python daily_run.py --no-apply   # everything except submitting
python daily_run.py --dry-run    # read-only check
```
Output: `briefings/<date>.md` (what was submitted, inbox actions, questions only AJ can answer, drafts).

## The agents

| # | Agent | File | Model tier (ai engine) | What it does | How it stays accurate with no human |
|---|---|---|---|---|---|
| 1 | Job Scout | `agents/job_scout.py` | fast (Haiku) | Reads the full job description (Workday/Greenhouse/Lever/Ashby JSON APIs, else page text) and scores fit 0-10 with reasons, gaps, keywords | Scores clamped 0-10; ineligible = 0; cached per job; `results_engine.score_job` uses it automatically |
| 2 | Resume Tailor | `agents/resume_tailor.py` | writer (Sonnet) | Reorders bullets / skills / sections of the real resume for each job -> `resumes/tailored/<job>/Candidate_Resume.pdf` | Only permutations of `resume_gen.py` MASTER are accepted - no text added, dropped or edited; must still fit one page |
| 3 | Form Answerer | `agents/form_answerer.py` | writer (Sonnet) | Answers questions with no `profile.json` rule (hooked into `ai_responder.py`) | Dropdown answers must match an option exactly; text answers rejected if they contain numbers not in the resume or banned words; legal / demographic / pay questions need an explicit fact or stay empty (job skips) |
| 4 | Outreach Drafter | `agents/outreach_drafter.py` | writer (Sonnet) | For submitted applications with fit >= 8: who to look for, a LinkedIn search link, and a connection note -> `outreach_drafts.csv` | Drafts only. Under 300 chars, ends "- Candidate", no banned words, no invented numbers |
| 5 | Inbox Analyst | `agents/inbox_analyst.py` | fast (Haiku) | Reads replies (via `outcomes.py`): confirmation / rejection / assessment / interview / offer, deadlines, proposed times | Read-only Gmail; cached per email; urgent items -> `agents/inbox_actions.md` |
| 6 | Site Fixer | `agents/site_fixer.py` + `agents/replay.py` | writer + expert (Opus) | After each run: unanswered questions -> new `profile.json` rules (marked `"src": "site_fixer"`); stuck pages -> a code patch to `fill.py` | Rules must match the question, not common fields, and quote a real fact. Patches apply only if git-clean, they compile, the failed page replays better offline, and **no** saved page replays worse; then committed (undo: `git revert`). Unanswerable questions -> `agents/needs_you.md` |
| 7 | Coordinator | `daily_run.py` | - | Runs steps 1-6 in order and writes the briefing | Each step is isolated - one failure doesn't stop the rest |

New-job source (used by the coordinator): `agents/job_sources.py` - the SimplifyJobs Summer 2027 list,
full titles, US only, posted <= 14 days ago, deduped against the queue and past applications.

Rule-based equivalents (`agents/local.py`): `scout()`, `tailor_overlay()`, `outreach()`, `read_email()`,
`rule_for_question()`. In local mode the Form Answerer defers to `profile.json` rules + `ai_responder.py`
templates (they are the rule-based answerer).

## Settings - `strategy.json` -> `"agents"`

```json
"engine":   "auto",                       // auto = AI if a key exists else local | local | ai
"models":   {"fast": "claude-haiku-5-5", "writer": "claude-sonnet-5-5", "expert": "claude-opus-5-5"},
"autonomy": {"job_scout": "auto", ...},   // "off" = use the rule-based fallback for that agent
"daily_budget_usd": 3.0,                  // all agents stop for the day once reached
"scout_limit_per_run": 150
```
Sonnet/Opus calls use server-side refusal fallback (`fallbacks: "default"`); if a request is still declined,
the agent returns nothing and the rules take over.

## Files the agents write

| Path | Contents |
|---|---|
| `agents/logs/<date>.jsonl` | every prompt input, output, cost and error |
| `agents/usage.json` | spend per day / per agent |
| `agents/cache/*.json` | job descriptions, scout scores, form answers, email reads |
| `agents/needs_you.md` | questions only AJ can answer (add a `profile.json` rule to clear) |
| `agents/inbox_actions.md` | urgent replies: assessments, interviews, offers, deadlines |
| `agents/fixes/*.patch` | every code patch the site fixer proposed (applied or not) |
| `records/<date>/<job>.{json,log,html}` | per application: answers, run log, page snapshot on failure |
| `outreach_drafts.csv`, `briefings/<date>.md` | drafts and daily briefing |

## Rules for whoever works on this next

- This folder is now a git repo - commit your changes. The site fixer only patches `fill.py` when it's committed (clean).
- Don't bypass the verifiers or let any agent send messages. Change behavior via `strategy.json`.
- Don't add facts to prompts that aren't in `resumes/resume_gen.py` MASTER or `profile.json`.
- Test with the offline replay (`python -m agents.replay <snapshot.html>`), not live submissions.

## Neural matching + adaptive waits (2026-10-14)

- `agents/semantic.py` - pretrained sentence-transformers model (all-MiniLM-L6-v2), local and free. Used in:
  job scoring (resume<->posting meaning match, calibrated: AI/analyst/PM postings ~0.55, firmware/robotics ~0.32,
  mapped to -1.5..+1.5 around 0.45), resume bullet ranking, and new wordings of questions already answered by rules
  (required, non-sensitive fields only; similarity >= 0.72 AND every name/number in the new question must appear
  in the matched one - 'authorized in Canada' scores 0.71 vs the US question, so similarity alone is unsafe).
  Off switch: strategy.json agents.semantic = false. Falls back to keywords if the package is missing.
- `waits.py` `settle()` replaces fixed sleeps in fill.py (6) and auth_manager.py (20): moves on once URL, field
  count and text length are steady for 0.6s; the old sleep value is the maximum. Ready pages: ~0.6s instead of 3-4s.

## Answers that fit the field (2026-10-14) - why jobs weren't submitting

Live run: 12 of 89 submitted. Most failures were answers that didn't fit the field ("2027" for a Yes/No
question, "Yes" for "which state", "08" where the list says "August"), so the site rejected the page and the
filler retried the same answer 5 times. Fixes, all in `fill.py` + `agents/options.py`:

- `options.resolve(question, answer, options)`: exact > whole word ("Male" never picks "Female") > rule pattern >
  Yes/No reasoning (incl. years: "graduating in 2028 or later?" + "Dec 2027" -> No) > dates ("05/2028" ->
  "May/June 2028") > months > aliases (USA / United States) > embeddings (>= 0.78). Returns None rather than guess.
- Fact questions (school, country, state, city, zip, degree, major, graduation, GPA, year) are answered from
  profile.json facts via `options.fact_rule`, never guessed (a guess once picked "Harvard University").
- Repair loop: the site's validation messages are kept in `FIX_HINTS`; on the retry those fields are re-answered
  (overwrite + escalation to the best visible option for non-fact, non-sensitive fields).
- Comboboxes: when a typed search shows "0 results", the full list is opened and resolved.
- Checkbox lists tick only the box matching the answer (not every required box).
- `strategy.json` `ats_timeouts` (Workday 480s); `AF_DEADLINE` makes fill.py dump its stack into the job log
  10s before the batch kills it; `[Fill]` / `[Slow]` lines show where time goes. The neural model loads in a
  background thread at job start (it took ~28s per job).
- Logs are UTF-8 (a curly quote used to crash the job); "Human Resource" no longer triggers the
  "how did you hear about us" answer.
- Tests: `tests/test_answer_fit.py`, `tests/test_fill_options.py` (real browser, offline fixtures).
