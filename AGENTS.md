# AGENTS.md

Project background, architecture, deployment topology and detailed changelog live in
`CLAUDE.md` (root). Read it for product/domain context. This file only holds durable,
non-obvious guidance for agents running in the Cursor Cloud VM.

## Cursor Cloud specific instructions

### Services & how to run them
- **Backend** (FastAPI): `python3 -m uvicorn api:app --host 0.0.0.0 --port 8000` from the repo
  root. The console scripts from `requirements.txt` install to `~/.local/bin`, which is **not on
  PATH** — always invoke via `python3 -m uvicorn` (and `python3 -m ...` for the crons) rather than
  bare `uvicorn`.
- **Frontend** (Next.js 15): `npm run dev` in `frontend/` (serves on port 3000). It proxies
  `/api/*` to `BACKEND_URL`.
- Standard lint/test/build commands are in `.github/workflows/pr-guardrails.yml` (the required CI
  check). Backend: `python3 -m py_compile api.py src/*.py` and
  `python3 -m unittest discover -s tests -t .` (176 tests, stdlib-only, no network/secrets).
  Frontend: `npm run build`.
- ⚠️ `npm run lint` (`next lint`) is **not configured** in this repo — it drops into an interactive
  ESLint setup prompt and will hang a non-TTY session. Use `npm run build` as the frontend check
  (that is what CI runs); do not run `next lint`.

### Local env config (not committed; only public values)
- Backend reads `/workspace/.env`; frontend reads `/workspace/frontend/.env.local`. Both are
  gitignored. For local dev, set `BACKEND_URL`/`NEXT_PUBLIC_BACKEND_URL` to `http://localhost:8000`
  (see `frontend/.env.local.example` and `.env.example`).
- Auth-gated endpoints (most of the API) need `SUPABASE_URL` + `SUPABASE_ANON_KEY` on the backend.
  The Supabase **anon key is public** (also hardcoded as a default in
  `frontend/app/lib/supabase.ts`), so login works with no real secret. Without these two vars
  `/health` shows `"supabase": false` and auth-gated endpoints 401.
- ⚠️ Local dev points at the **production** Supabase project (`zcxaxwqkswuefzlzpgvi`) by default
  (hardcoded). Writes hit the prod DB — use the QA test account and clean up test rows. Dev vs prod
  URLs are in `CLAUDE.md`.
- Core features (analysis, generation, publishing, outreach, billing) require real third-party
  secrets that are **not present by default**: `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, `OPENAI_API_KEY`,
  `ZERNIO_API_KEY`, `UNIPILE_*`, `MANYCHAT_*`, `STRIPE_*`. The app boots and degrades cleanly without
  them (`/health` reports `apify`/`anthropic` false; feature-gated endpoints return "non configuré").
  Add real keys via the Secrets panel to exercise those flows.

### Gotchas
- ⚠️ The **first** request from the VM to Supabase has high cold-start latency and can even hit a
  one-off `httpx.ReadTimeout` (500). Subsequent requests are fast (<1s). Do not conclude there's a
  bug from a single first-call timeout — retry once the connection is warm.
- QA test login (works against the prod Supabase, no secret needed):
  `qa.playwright@lkd-outreach.app` / `Lkd!Test2026`. Good for local login + a reversible core action
  (e.g. add/remove an idea in the "Mes idées de posts" reservoir). It's the same account the
  Playwright suite uses (`CLAUDE.md` › "Tests E2E").
