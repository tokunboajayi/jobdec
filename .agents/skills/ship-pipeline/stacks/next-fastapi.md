# Stack: next-fastapi

Next.js frontend on Vercel + FastAPI backend on Fly.io + Postgres (Supabase or
Neon). Use when the core logic is Python: trading, data pipelines, ML, agents.

## 1. Scaffold

```
web/   Next.js (same scaffold as next-supabase-vercel, minus Supabase auth if not needed)
api/   FastAPI service
gan-harness/acceptance/   Playwright (UI) + pytest (API) acceptance tests
```

```bash
npx create-next-app@latest web --ts --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-npm --yes
mkdir api && cd api
uv init --app && uv add fastapi "uvicorn[standard]" pydantic-settings \
  "sqlalchemy>=2" "psycopg[binary]" alembic httpx
uv add --dev pytest ruff mypy
```

(No `uv`? Use `python3 -m venv .venv` + `pip install` with a `requirements.txt`.)

## 2. Required files

| File | Purpose |
|------|---------|
| `api/app/main.py` | FastAPI app, CORS limited to the web origin from env |
| `api/app/settings.py` | pydantic-settings; fails on missing env |
| `api/app/routes/health.py` | `GET /health` → `{ok, db}` |
| `api/alembic/` | migrations; `alembic upgrade head` on deploy |
| `api/Dockerfile` | `uvicorn app.main:app --host 0.0.0.0 --port 8080` |
| `api/fly.toml` | `internal_port = 8080`, health check on `/health` |
| `web/src/lib/api.ts` | typed fetch wrapper using `NEXT_PUBLIC_API_URL` |
| `gan-harness/acceptance/test_api.py` | httpx against `API_URL` env |
| `gan-harness/acceptance/*.spec.ts` | UI flows against `BASE_URL` |

Money and risk logic (orders, stop-losses, balances) lives in the API with
unit tests, never in the frontend. Use `Decimal`, not `float`, for money.

## 3. Scripts

- `web`: `typecheck`, `lint`, `build`, `test:acceptance`.
- `api`: `uv run ruff check .`, `uv run mypy app`, `uv run pytest`,
  `uv run pytest ../gan-harness/acceptance` for API acceptance.

## 4. Deploy

```bash
cd api && fly launch --no-deploy --copy-config --name <app>-api --yes
fly secrets set DATABASE_URL="$DATABASE_URL" ...   # every api secret
fly deploy --remote-only
API_URL=https://<app>-api.fly.dev uv run pytest ../gan-harness/acceptance
cd ../web   # then the Vercel steps from next-supabase-vercel, with NEXT_PUBLIC_API_URL set
```

## Known pitfalls

- **CORS:** set the allowed origin to the exact Vercel URL(s), including the
  preview URL during verification; `*` with credentials fails.
- **Fly cold start:** first request after idle can take seconds; give the
  health wait a 60s timeout.
- **Postgres pooler:** use the pooled connection string for the app and the
  direct one for Alembic migrations if they differ.
