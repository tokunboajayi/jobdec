---
name: ship-pipeline
description: Idea-to-production pipeline — one short intake, then an unattended run that scopes the MVP, writes executable acceptance tests before code, builds on a pre-wired stack through the GAN generator-evaluator loop with acceptance tests as a hard gate, hardens, deploys, and re-verifies against the live URL. Use when the user wants a working, deployed product from an idea or brief with no babysitting after intake.
metadata:
  origin: ECC
---

# ship-pipeline

`/ship` engine. Turns an idea into a **deployed, acceptance-tested product**.
It composes existing ECC pieces (`gan-planner`, `gan-generator`,
`gan-evaluator`, `code-reviewer`, `security-reviewer`, `build-error-resolver`,
`/checkpoint`) and adds what they lack: up-front intake, a scope cap,
tests-before-code, a pre-wired stack, a deploy step, and live verification.

## When to Use

- "Build me X", "take this idea to a working app", "ship this", hackathon builds.
- The user wants the result live at a URL, not running on localhost.
- Use `orch-build-mvp` instead when the user wants approval gates between phases.
- Use `orch-add-feature` instead when the codebase already exists.

## Paths

`$SHIP_DIR` below means this skill's own directory — the base directory shown
when the skill loads. Under the ECC plugin it is
`$CLAUDE_PLUGIN_ROOT/skills/ship-pipeline`; for a manual install it is
`~/.claude/skills/ship-pipeline`. Resolve it once at the start and pass the
absolute path to every agent you launch. All run artifacts go in the
**project's** `gan-harness/` directory.

## The contract

**One human touch point (Phase 0). Everything after it runs unattended.**

Done means all of these hold, checked by commands, not by opinion:

1. Every scenario in `gan-harness/acceptance/` passes against **localhost**.
2. Typecheck, lint, and build exit 0.
3. No CRITICAL/HIGH findings open from `code-reviewer` / `security-reviewer`.
4. The app is deployed and every acceptance scenario passes against the **live URL**.

If any of these cannot be met, the run still ends with a report that says
exactly which one failed and why. It never claims success it did not verify.

## Phase 0 — Intake (the only interactive phase)

Delegate to the `ship-intake` agent. It asks at most 6 questions in one batch,
writes `gan-harness/brief.md`, and picks a stack profile from
[`stacks.json`](stacks.json) (details in [`stacks/`](stacks/)).

Then run preflight. It checks CLIs and env vars without printing secret values:

```bash
node $SHIP_DIR/scripts/preflight.js --stack <id> --features <a,b> --env-file .env.local
```

- Exit 0 → continue.
- Exit 1 → show the missing keys with where to get each (the output lists
  them), ask the user once, re-run preflight. **Do not start Phase 1 until it
  passes** — a missing key discovered at iteration 9 is the most common way
  unattended runs die.
- `--local-only` skips deploy credentials when the user explicitly has none.

## Phase 1 — Scoped spec and acceptance tests (before any code)

1. Launch `gan-planner` with `gan-harness/brief.md` and the instruction
   **`MODE: ship`** (scope-capped; see the planner's Ship Mode section).
   Output: `gan-harness/spec.md` + `gan-harness/eval-rubric.md`.
2. The planner also writes `gan-harness/acceptance/*.spec.ts` — Playwright
   tests, one per core-flow scenario, reading `BASE_URL` from the environment.
   API-only stacks write `gan-harness/acceptance/test_*.py` (pytest + httpx).
3. Sanity-check the scope: **one core loop, ≤ 6 features, ≤ 12 acceptance
   scenarios.** If the planner exceeded it, cut to the cap yourself and move
   the rest to a `## Later` section. Do not ask the user.

## Phase 2 — Scaffold the stack

Follow the stack file in `stacks/<id>.md` exactly: scaffold command, the
pre-wired modules (auth, DB, payments as selected), the `/api/health` route,
and the `test:acceptance` script. Commit: `chore: scaffold <stack>`.

Run the acceptance suite once now. It **should fail** (red). If it passes,
the tests are not testing the spec — rewrite them.

## Phase 3 — Build loop

Run the GAN loop with acceptance tests as the hard gate:

```
/gan-build "<one-line brief>" --skip-planner --acceptance --pass-threshold 7.0 --max-iterations 12
```

- `--acceptance` makes the evaluator run `npm run test:acceptance` (or the
  stack's equivalent) first. **Any failing scenario caps the score at 5.0**,
  so the loop cannot pass on looks.
- The rubric uses ship weights: functionality 0.45, craft 0.25, design 0.2,
  originality 0.1 (written into `eval-rubric.md` by the planner).
- After each iteration run `/checkpoint` (or write
  `gan-harness/checkpoint.md`: iteration, score, failing scenarios, next step)
  so a crashed run resumes instead of restarting.

**On plateau with failing scenarios:** do not stop. Switch to fix-only mode
for up to 3 more iterations: give `gan-generator` only the failing test
names and their output, with "make these pass; change nothing else". On a
build break, delegate to `build-error-resolver`.

## Phase 4 — Hardening

Run in parallel: `code-reviewer`, `security-reviewer` (always — ship runs
touch auth, input, and secrets by definition), and the stack's
`typecheck`, `lint`, `build` commands. Fix CRITICAL/HIGH findings, re-run the
acceptance suite, commit `fix: hardening`.

If a reviewer agent is not installed, do that review yourself against the
same checklist and note "reviewer agent unavailable" in the report.

Never commit `.env*` files. Confirm `.gitignore` covers them before any commit.

## Phase 5 — Deploy and verify live

Delegate to the `ship-deployer` agent with the stack id. It:

1. Pushes env vars to the host, deploys a **preview**, waits for `/api/health`.
2. Runs the acceptance suite with `BASE_URL=<preview url>`.
3. All green → promotes to production and re-runs the suite against the
   production URL. Red → reads the failure, fixes (max 2 attempts), redeploys.
   Still red → leaves production untouched and reports.

With `--local-only`, skip this phase and say so in the report.

## Phase 6 — Report

Write `gan-harness/ship-report.md` and show the user:

```markdown
# Ship report — <App name>

**Live:** <production URL or "not deployed — reason">
**Verdict:** SHIPPED | SHIPPED WITH GAPS | NOT SHIPPED

| Gate | Result |
|------|--------|
| Acceptance (local) | 9/9 |
| Typecheck / lint / build | pass / pass / pass |
| Review findings open | 0 critical, 0 high |
| Acceptance (live) | 9/9 |

**Mocked or stubbed:** <anything not real — e.g. "LLM responses mocked in tests">
**Iterations:** N · **Final score:** X.X
**Cut to Later:** <features deferred by the scope cap>
**Manual steps left:** <e.g. "add production URL to Supabase Auth redirect URLs">
```

## Resume

Keep `gan-harness/checkpoint.md` current at every phase boundary and after
every build iteration:

```markdown
phase: 3
iteration: 6
score: 6.4
failing: [checkout-redirect, empty-state]
next: fix-only iteration on failing scenarios
```

`/ship --resume` reads it and continues from `phase`/`next`. Never re-run
intake or re-scaffold on resume.

## Learn from every run

After a SHIPPED run, append what broke and how it was fixed to
`$SHIP_DIR/stacks/<id>.md` under `## Known pitfalls`, so the next
run on that stack avoids it. This is how the pipeline gets more reliable per
stack over time.

## Verification checklist

- Preflight passed before Phase 1 started.
- Acceptance tests existed and failed before implementation began.
- The final score did not pass with any acceptance scenario failing.
- Security review ran.
- Live acceptance results came from the deployed URL, not localhost.
- The report lists everything mocked and every manual step left.
