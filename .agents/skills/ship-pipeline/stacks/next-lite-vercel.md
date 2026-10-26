# Stack: next-lite-vercel

Next.js only, no accounts. Fastest path to a live demo: tools, calculators,
generators, single-flow apps. Optional AI and email features.

## 1. Scaffold

```bash
npx create-next-app@latest . --ts --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-npm --yes
npm i zod
npm i -D @playwright/test
npx playwright install --with-deps chromium
```

## 2. Required files

- `src/lib/env.ts` — zod-validated env (even if empty, so adding a key later fails loudly).
- `src/app/api/health/route.ts` — `{ ok: true }`.
- `gan-harness/acceptance/playwright.config.ts` — same `BASE_URL` pattern as
  `next-supabase-vercel`.

Persistence, if a feature needs it: browser `localStorage` for per-user data
(wrapped in try/catch), or add Vercel Postgres / Upstash only if the spec
truly needs shared state. If it does, consider switching to
`next-supabase-vercel` before Phase 3 instead of bolting it on.

## 3. Scripts

`typecheck` (`tsc --noEmit`), `lint`, `build`, `test:acceptance`.

## 4. Deploy

Same Vercel commands as `next-supabase-vercel` §5, with only this stack's env vars.

## Known pitfalls

- AI routes on Vercel have function time limits; stream long responses and
  set `export const maxDuration` within the plan's limit.
