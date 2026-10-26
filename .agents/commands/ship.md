---
description: Idea to deployed, acceptance-tested product. One short intake, then an unattended run - scope, tests first, build loop, hardening, deploy, live verification. Wrapper for the ship-pipeline skill.
argument-hint: "<idea or path to brief/spec> [--stack id] [--local-only] [--resume]"
---

# /ship

Turn an idea into a live product. You answer one batch of questions; the
rest runs without you until there is a URL and a report.

## Usage

```
/ship "<idea in one or two sentences>"
/ship docs/PRD.md
/ship "<idea>" --stack next-fastapi
/ship "<idea>" --local-only
/ship --resume
```

## What It Does

Invoke the `ship-pipeline` skill with `$ARGUMENTS`. It runs:

0. **Intake** (`ship-intake` agent): up to 6 questions in one batch, writes
   `gan-harness/brief.md`, then the skill's `scripts/preflight.js` blocks the run
   until every key and CLI it needs is present.
1. **Spec + acceptance tests first** (`gan-planner`, ship mode): scope capped to
   one core loop and at most 6 features; Playwright/pytest acceptance tests are
   written before any code and must fail initially.
2. **Scaffold** a pre-wired stack from `skills/ship-pipeline/stacks/`.
3. **Build loop**: `/gan-build --skip-planner --acceptance`, where any failing
   acceptance scenario caps the score at 5.0, checkpointing every iteration.
4. **Hardening**: `code-reviewer` + `security-reviewer` + typecheck/lint/build.
5. **Deploy** (`ship-deployer`): preview, acceptance against the live URL,
   promote only when green.
6. **Report**: `gan-harness/ship-report.md` with the live URL, gate results,
   anything mocked, and manual steps left.

## Arguments

- First argument: the idea, or a path to an existing brief/PRD/spec (intake
  then only asks what the doc leaves open).
- `--stack <id>`: skip the stack question. the skill's `scripts/preflight.js --list` shows options.
- `--local-only`: no deploy credentials needed; stops after Phase 4.
- `--resume`: read `gan-harness/checkpoint.md` and continue from the recorded phase.

If `$ARGUMENTS` is empty, ask for the idea in one line.
