# Architecture

Two deployable services and a managed Postgres. Nothing else, on purpose.

## The flow

```
  browser (Hebrew, RTL)
    │
    ├── sign in / refresh ──────────────► Supabase Auth
    │                                       (ES256 tokens, publishable key)
    │
    └── everything else ───────────────► backend  (FastAPI)
                                            │  verifies the token: signature,
                                            │  issuer, audience, expiry
                                            │  authorizes the caller
                                            │
                                            ├──► Supabase Postgres
                                            │      service role, bypasses RLS,
                                            │      so every query is scoped here
                                            │
                                            ├──► PubMed / Europe PMC
                                            │      through one guarded client
                                            │
                                            └──► AI provider
                                                   research material only

  job consumer (inside the same backend process)
    └── claims work from research_jobs, atomically, with a lease
```

The browser never talks to PostgREST and never holds a secret key. RLS is still
the floor under everything - if the API layer forgot a filter, the database would
still refuse a cross-user read.

## Repository

```
frontend/   static HTML/CSS/JS, Caddy, its own Dockerfile and railway.json
backend/    FastAPI app, research adapters, AI seam, job consumer
supabase/   migrations, seeds, live acceptance scripts
docs/       this, decisions, data model, deployment, researcher guide, privacy
```

Each service builds from its own directory and needs nothing from the other.

## Backend layout

| Package | Holds |
|---|---|
| `app/api/v1/` | Request-facing and staff endpoints. Authorization decisions live here |
| `app/auth/` | Token verification and role lookup |
| `app/domain/` | Schemas, permitted status transitions, content hashing |
| `app/services/` | The PostgREST client and plant identification |
| `app/research/` | Guarded HTTP, provider adapters, labelling, dedupe, the pipeline |
| `app/ai/` | The provider seam, the prompt, the output contract |
| `app/jobs/` | Queue operations, handlers, the consumer |

## Why the job queue is in Postgres

Long research work cannot run inside an HTTP request, and `BackgroundTasks` does
not survive a restart. A third service (Redis, a worker) would be more machinery
than this pilot needs.

So the queue is a table. Claiming is one atomic `UPDATE ... WHERE id = (SELECT ...
FOR UPDATE SKIP LOCKED)`, which gives two properties at once: two processes never
take the same job, and a second process is not blocked by the first. A claimed
job carries a lease that the worker refreshes; if the process dies, the lease
expires and the job becomes claimable again.

That is the whole restart story - nothing is lost, and nothing is done twice.

**Capacity:** one job at a time per process. Adding replicas is safe but does not
raise per-replica throughput. For the pilot this is enough; it is written down
rather than discovered later.

## Where each guarantee actually lives

The product's hard rules are not comments. Each one has a place in the stack:

| Guarantee | Enforced by |
|---|---|
| A user reads only their own data | RLS policies and column grants |
| A user never sees a draft | A policy naming `state = 'published'`, plus the API |
| A user never sees internal status | `status` is not granted; `user_visible_status` is |
| Nobody promotes themselves | No write grant on `user_roles` at all |
| Publication requires approval | No transition leads to `published` |
| Approval binds to what was read | A content hash compared inside the transaction |
| All four checks were made | A check constraint on `approvals` |
| One published version per request | A partial unique index |
| A claim has a source and a location | A check constraint on `evidence_items` |
| A failure is not a finding | Constraints on `search_runs` and `research_jobs` |
| No fabricated citations | Validators reject ids that were not supplied |
| No numeric score, no GRADE, no PRISMA | Validators on the draft body |

The pattern is deliberate: where a rule can be a constraint, it is a constraint.
Application code is where rules go to be forgotten.

## What is not here

No Redis, no separate worker service, no frontend framework, no ORM, no vendor
SDK for the AI provider. Each absence is a decision recorded in
`docs/decisions.md`, not an omission.

## Known gaps

- **The Dockerfiles have never been built.** Docker is not installed on the
  development machine; their first build happens on Railway.
- **`extract` is not implemented.** Structured extraction needs full text, which
  needs article upload to Storage.
- **Article upload to Storage** is not built; no buckets exist yet.
- **The pilot questionnaires** have a table but no screens.
