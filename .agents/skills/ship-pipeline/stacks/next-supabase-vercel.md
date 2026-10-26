# Stack: next-supabase-vercel

Next.js (App Router, TypeScript, Tailwind) + Supabase (Postgres, Auth, RLS) +
optional Stripe / Resend / LLM, deployed to Vercel.

Follow this file exactly during Phase 2. The point of a fixed stack is that
the generator spends its iterations on features, not on plumbing.

## 1. Scaffold

```bash
npx create-next-app@latest . --ts --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-npm --yes
npm i @supabase/supabase-js @supabase/ssr zod
npm i -D @playwright/test supabase
npx playwright install --with-deps chromium
```

If the directory is not empty, scaffold into `app/` and run everything from there.

## 2. Required files

| File | Purpose |
|------|---------|
| `src/lib/supabase/server.ts` | `createServerClient` from `@supabase/ssr` using `cookies()` |
| `src/lib/supabase/client.ts` | `createBrowserClient` for client components |
| `src/middleware.ts` | refreshes the session on every request; redirects signed-out users away from `/app/*` |
| `src/lib/env.ts` | zod-validates every env var at startup; fails loudly with the missing name |
| `src/app/api/health/route.ts` | `GET` returns `{ ok: true, db: <bool> }` after a trivial `select` |
| `supabase/migrations/0001_init.sql` | all tables; **`enable row level security` + policies on every table** |
| `gan-harness/acceptance/playwright.config.ts` | `baseURL: process.env.BASE_URL ?? 'http://localhost:3000'`; `webServer` only when `BASE_URL` is unset |
| `gan-harness/acceptance/fixtures.ts` | creates a confirmed test user with the admin API (see pitfalls) and deletes it after |

Use the publishable key (or legacy anon key) in the browser. The secret /
service-role key is used **only** in server code and test fixtures, never in a
`NEXT_PUBLIC_` variable.

## 3. Scripts (package.json)

```json
{
  "typecheck": "tsc --noEmit",
  "test:acceptance": "playwright test -c gan-harness/acceptance/playwright.config.ts",
  "db:push": "supabase db push --db-url \"$SUPABASE_DB_URL\""
}
```

Run `npm run db:push` after every migration change. Migrations are additive:
new file per change, never edit an applied one.

## 4. Optional features

- **payments** — `npm i stripe`. `POST /api/checkout` creates a Checkout
  Session and returns its URL. `POST /api/stripe/webhook` reads the raw body
  with `await req.text()` and verifies with `stripe.webhooks.constructEvent`;
  it updates a `subscriptions` table keyed by user id. Gate paid features on
  that table, not on the client. Acceptance test: clicking upgrade lands on
  `checkout.stripe.com` — do not try to complete a hosted payment in tests.
- **email** — `npm i resend`; send from a server action only.
- **ai** — call the provider from a route handler or server action, never
  from the browser. Stream responses; set a max token limit; handle 429s.

## 5. Deploy (used by ship-deployer)

```bash
npx vercel link --yes --project <app-slug> --token "$VERCEL_TOKEN"
# for each required env var, for preview and production:
printf '%s' "$VALUE" | npx vercel env add NAME preview --token "$VERCEL_TOKEN"
printf '%s' "$VALUE" | npx vercel env add NAME production --token "$VERCEL_TOKEN"
url=$(npx vercel deploy --yes --token "$VERCEL_TOKEN")          # preview
BASE_URL="$url" npm run test:acceptance
prod=$(npx vercel deploy --prod --yes --token "$VERCEL_TOKEN")  # production
```

Add the production URL to Supabase Auth > URL Configuration (Site URL and
redirect URLs). List it as a manual step if it cannot be done via API.

## Known pitfalls

- **Email confirmation blocks signup tests.** Create test users with
  `supabase.auth.admin.createUser({ email, password, email_confirm: true })`
  in a fixture, then log in through the UI. Never rely on inbox links.
- **Vercel preview protection returns 401 to Playwright.** Either set
  `VERCEL_AUTOMATION_BYPASS_SECRET` and send it as the
  `x-vercel-protection-bypass` header via `extraHTTPHeaders`, or verify on the
  production URL and say so in the report.
- **RLS on, no policy = empty results, no error.** If a list renders empty in
  tests but rows exist, check the policy before touching UI code.
- **`NEXT_PUBLIC_` vars are inlined at build time.** Changing them on Vercel
  needs a redeploy.
- **Stripe webhook needs the deployed URL.** Leave `STRIPE_WEBHOOK_SECRET`
  unset until after the first deploy and list it as a manual step.
