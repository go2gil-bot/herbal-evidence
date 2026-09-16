# Engineering Decisions (changeable implementation choices)

These entries are **implementation defaults**, not previously approved product decisions. Product-level binding decisions live in the specification (sections 1–2) and are not restated here.

| # | Date | Decision | Rationale | Status |
|---|------|----------|-----------|--------|
| D-001 | 2026-09-16 | Working name **Herbal Evidence** (Hebrew UI: ראיות צמחים). Hebrew RTL first, structured for future localization (string tables, `dir` attributes, bidi isolation). | Spec §3 | default |
| D-002 | 2026-09-16 | Backend: Python 3.13, FastAPI, Uvicorn, `uv` for dependency management. | Spec §3; uv installed locally | default |
| D-003 | 2026-09-16 | Frontend: plain HTML/CSS/JS, no framework. Served by a static server (Caddy) in its own Railway service. | Spec §3 | default |
| D-004 | 2026-09-16 | Auth: Supabase Auth, email/password, email verification, password reset. Backend validates Supabase JWTs (iss/aud/exp). | Spec §3 | default |
| D-005 | 2026-09-16 | Admin manually assigns requests to researchers. Simple `assigned_researcher_id` column; replaceable. | Spec §3, open business decision | default |
| D-006 | 2026-09-16 | No request-update emails in v1. | Spec §3 | default |
| D-007 | 2026-09-16 | Separate Supabase projects `herbal-evidence-dev` and `herbal-evidence-prod`, in a **new Supabase organization** created for this product. | Spec §3, §12; user choice during planning | default |
| D-008 | 2026-09-16 | AI provider interface is replaceable; first concrete adapter targets **OpenAI**. Model and key via `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`. Without a key the provider raises a structured "not configured" job failure — never mock content. | Spec §3; user choice during planning | default |
| D-009 | 2026-09-16 | Literature adapters: PubMed E-utilities (esearch/efetch) + Europe PMC REST. Optional `NCBI_API_KEY` for higher rate limits. | Spec §6 | default |
| D-010 | 2026-09-16 | Durable job queue in Postgres (`research_jobs`), claimed with `FOR UPDATE SKIP LOCKED`, lease + heartbeat, bounded retries, idempotency key; consumer runs inside the backend process lifespan. No Redis, no third service. | Spec §8 | default |
| D-011 | 2026-09-16 | Drafts and staff artifacts have **no** RLS policies for `anon`/`authenticated`; they are reachable only through the backend using the service-role key with explicit server-side authorization. | Spec §9–10 | default |
| D-012 | 2026-09-16 | Design created in Google Stitch (project `12444680124780591192`, design system asset `602809031577218080`). Screen IDs in `docs/design/stitch.md`. | Spec §11 | default |
| D-013 | 2026-09-16 | Work is executed in phases (0–6) with a review stop after each; progress logged in Obsidian `HERBAL_EVIDENCE_PROJECT/`. | User instruction | default |
| D-014 | 2026-09-16 | **Supersedes D-007.** Both Supabase projects live in the existing organization **`Gil AI Course`** (`bmwbpotofrnbijikkeib`) — "גיל AI קורסים" — not in a new organization. | User instruction, 2026-09-16 | active |
| D-015 | 2026-09-16 | **Supersedes D-002's `uv` choice.** `uv` is **not installed** on this machine; dependencies are declared in `backend/pyproject.toml` and installed with `pip`. Python 3.14 locally, `python:3.12-slim` in the image. Revisit if `uv` is installed later. | Verified with `Get-Command uv` | active |
| D-016 | 2026-09-16 | **Docker is not installed locally.** Dockerfiles are written for Railway's remote build and cannot be built or run here. Local verification uses a plain static server for the frontend and Uvicorn for the backend. This is a verification gap, recorded rather than papered over. | Verified with `Get-Command docker` | active |
| D-017 | 2026-09-16 | No local Supabase stack (Docker). Schema work runs against the remote `dev` project with `npx supabase db push --linked`; `supabase start` and `db diff` are unavailable. | Spec §12 adapted to the machine | active |
| D-018 | 2026-09-16 | **Supersedes D-013's Obsidian path.** Progress and product documentation live in the Obsidian vault folder **`Herbal Evidence/`** (`E:\Google Drive\ClaudeVo\Herbal Evidence`). `HERBAL_EVIDENCE_PROJECT/` was referenced by an earlier session but never created. | User instruction, 2026-09-16 | active |
| D-019 | 2026-09-16 | Repository lives at `E:\Google Drive\Claude Projects\קורס AI\plants app`, remote `github.com/go2gil-bot/herbal-evidence`. Moved there with full history from a sibling folder. | User instruction, 2026-09-16 | active |
| D-020 | 2026-09-16 | **Supersedes D-012.** The Stitch project in D-012 is not accessible from this account and cannot be cited as evidence of a design. Real project: `318546168212711602`; design system `assets/16b8291a31b74b9d8b5d37ec7bafa0b1` ("Clinical Evidence Review"). | Verified with `list_projects` / `get_project` | active |
| D-021 | 2026-09-16 | Stitch generated **1 of 10** screens; the rest timed out. `list_screens` returns empty even for existing screens, so a timed-out generation is unrecoverable. Remaining screens are designed directly in HTML/CSS against the recorded tokens rather than blocking on the MCP. | Observed over four generation calls | active |
| D-022 | 2026-09-16 | The generated mockup's "GRADE Low", "PRISMA", scanned-item counts, Cochrane Central and "share with your doctor" are **rejected** — they claim methodology and scope the product does not have. See `docs/design/stitch.md`. | Spec §5, §11 | active |
