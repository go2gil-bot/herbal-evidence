# Herbal Evidence (ראיות צמחים)

Hebrew-first (RTL) web platform where people with cancer and their caregivers submit a claim about a **single herb and appetite improvement**. The system prepares an AI-assisted evidence-review draft; a **human researcher checks, edits, and approves** every personalized response before it is published to the user's account.

The platform does **not** recommend which herb to take, does not prescribe doses, and does not approve combinations with treatment.

## Monorepo layout

| Path | Purpose |
|------|---------|
| `frontend/` | Static HTML/CSS/JS site (own Railway service) |
| `backend/` | FastAPI + Uvicorn API, research/AI workflow, Postgres-backed job queue (own Railway service) |
| `supabase/` | Supabase CLI config, migrations, mock seed |
| `docs/` | Architecture, decisions, data model, deployment, researcher guide, privacy |

## Environments

| Env | Git branch | Railway env | Supabase project |
|-----|-----------|-------------|------------------|
| dev | `dev` | `dev` | `herbal-evidence-dev` |
| production | `main` | `production` | `herbal-evidence-prod` |

Details and setup steps: see `docs/deployment.md`. Development status per phase is tracked in the project's Obsidian vault (`HERBAL_EVIDENCE_PROJECT/`).

## Local development

No Docker and no `uv` on the current machine — see `docs/decisions.md` D-015 to D-017.

**Backend** (Python 3.12+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

`GET /health` returns liveness. `GET /ready` reports which configuration is present
("set" / "missing") and never a value.

**Frontend** (any static server):

```bash
cd frontend
python -m http.server 4173
```

`config.js` in the repo holds local defaults. In the container it is rewritten from
environment variables by `entrypoint.sh` — public values only.

**Supabase**: remote-only. `npx supabase db push --linked` against the `dev` project.
`supabase start` and `db diff` need Docker and are unavailable here.

## Status

**Phase 1 — skeleton. Done and verified locally:**

| Item | State |
|------|-------|
| `dev` branch created from `main` | ✅ |
| Backend: FastAPI, `/health`, `/ready`, CORS from env, Dockerfile | ✅ 2 tests pass |
| Frontend: Hebrew RTL landing page, Caddy Dockerfile, runtime config | ✅ renders, desktop + mobile |
| Supabase schema, Auth, RLS | ⬜ phase 3 |
| Railway services | ⬜ phase 7 |

Neither Dockerfile has been built — Docker is not installed here (D-016).

Phase plan and progress: Obsidian vault, `Herbal Evidence/תוכנית שלבים`.
Engineering choices: `docs/decisions.md`.
