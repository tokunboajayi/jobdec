# Stack: vite-static

Vite + React + TypeScript static site on Vercel. Landing pages, portfolios,
client-only tools. No server, no secrets.

## 1. Scaffold

```bash
npm create vite@latest . -- --template react-ts
npm i
npm i -D tailwindcss @tailwindcss/vite @playwright/test
npx playwright install --with-deps chromium
```

Add the Tailwind Vite plugin to `vite.config.ts` and `@import "tailwindcss";`
to the main CSS file.

## 2. Required files

- `gan-harness/acceptance/playwright.config.ts` — `BASE_URL` pattern; local
  `webServer` is `npm run preview -- --port 3000` after `npm run build`.
- `public/` assets referenced by relative paths only.

## 3. Scripts

`typecheck` (`tsc -b`), `lint`, `build`, `test:acceptance`.

## 4. Deploy

```bash
url=$(npx vercel deploy --yes --token "$VERCEL_TOKEN")
BASE_URL="$url" npm run test:acceptance
npx vercel deploy --prod --yes --token "$VERCEL_TOKEN"
```

## Known pitfalls

- Client-side routes 404 on refresh: add a `vercel.json` rewrite of all paths
  to `/index.html` if the app uses a router.
