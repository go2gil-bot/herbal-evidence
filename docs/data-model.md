# Data model

Applied to the `dev` project `wnttlpxiycghqiibdpjr` (`herbal-evidence-dev`, org
`Gil AI Course`, eu-central-1) by `supabase db push` on 2026-09-17.

17 tables, all with RLS enabled, 13 policies. `supabase db advisors --type security`
reports no issues.

## The authorization model in one paragraph

Client roles start with **nothing**: the RLS migration revokes every grant from
`anon` and `authenticated`, including default privileges for future tables, and
then grants back individual **columns** of individual tables. A requester can read
their own request but not its `status` or `assigned_researcher_id`; they read
`user_visible_status` instead, a generated column that collapses nine internal
states into five. Staff do not read these tables from a browser at all - every
researcher and admin operation goes through the backend with the service role,
which authorizes the caller server-side (D-011). A leaked staff JWT is therefore
not a read primitive.

## Tables

| Table | Who can reach it from a client |
|-------|-------------------------------|
| `profiles` | owner: select / insert / update own, on three columns |
| `user_roles` | owner: **select only**. No write grant exists, so nobody can promote themselves |
| `plants`, `plant_aliases` | any authenticated user: select (reference data) |
| `requests` | owner: select (granted columns) and insert (input columns only). **No update** |
| `request_clarifications` | owner: select; update `answer` only, and only while it is still null |
| `response_versions` | owner: select **only where `state = 'published'`**, on six columns |
| `pilot_assessments` | owner: select / insert own |
| `research_questions`, `sources`, `evidence_items`, `reviews`, `review_versions`, `approvals`, `research_jobs`, `search_runs`, `audit_events` | **nobody.** RLS on, no grants, no policies - service role only |

## Constraints that carry a product rule

These are places where the specification is enforced by the database rather than
by remembering to check:

| Constraint | What it prevents |
|-----------|------------------|
| `approvals_requires_every_check` | An approval row cannot exist unless all four confirmations are true. Filling in fields does not approve anything |
| `evidence_items_claim_needs_support` | A claim cannot be stored without a support kind and location. No invented page numbers |
| `search_runs_failure_has_error` | A failed search must carry its error. A failure never becomes "no evidence found" |
| `search_runs_success_has_count` | Only a successful run may report a result count, so zero results and a failure stay different rows |
| `research_jobs_failure_has_error` | Same rule for the job itself. Processing failure lives on the job, never on the request status |
| `response_versions_single_published` (partial unique index) | One published version per request. An update draft cannot quietly replace a live answer |
| `response_versions_withdrawn_has_reason` | A withdrawal without a reason is impossible |
| `requests_closed_needs_reason` | A request cannot be closed without an explanation for the user |

## Operations that must be atomic

In `private`, wrapped in `public` functions whose EXECUTE is granted **only** to
`service_role`:

- `approve_response_version(...)` - locks the row, refuses if the state is not
  `draft`, and refuses if `content_hash` differs from the hash the researcher
  reviewed. Inserts the approval, moves any previously published version to
  `superseded`, publishes, updates the request and writes an audit event - all in
  one transaction.
- `withdraw_response_version(...)` - requires a reason; withdrawn content stops
  satisfying the reader policy immediately.
- `claim_research_job(...)` - `for update skip locked`, so two replicas never take
  the same job. It also reclaims jobs whose lease expired, which is what makes an
  unfinished job survive a backend restart.
- `heartbeat_research_job`, `fail_research_job`, `complete_research_job`.

### Why the error codes look odd

The refusals raise SQLSTATE `PT409` / `PT404` / `PT400`. PostgREST maps a `PTxyz`
state to HTTP status `xyz`. The first version raised `serialization_failure`
(40001) - **PostgREST retries that class automatically**, so a refusal that is
meant to be final turned into a retry loop and the request hung instead of
answering 409. Do not reuse retryable SQLSTATEs for deliberate refusals.

## Verification

`supabase/tests/rls_isolation.py` creates two real users, signs them in, and tries
to cross the boundaries through PostgREST exactly as a browser would.

**24/24 checks pass**, covering acceptance criteria 1-3:

- user B cannot list or fetch user A's request; anonymous cannot list requests
- the owner cannot read their own draft, and neither can anyone else
- a payload cannot set `status` or `assigned_researcher_id`, cannot grant a role,
  and cannot submit on someone else's behalf
- five staff tables return nothing
- approving a stale hash is refused; approving with one check missing is refused;
  a correct approval publishes, and only then can the owner read it
- a withdrawal removes it from the owner's view again

Run it with `python supabase/tests/rls_isolation.py`. It reads `supabase/.env`
(gitignored) and deletes the users it created. Never point it at Production.

## Auth

Supabase signs user access tokens with **ES256**; the public keys are at
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. `backend/app/auth/jwt.py` verifies
the signature against that JWKS and checks issuer, audience (`authenticated`) and
expiry, requiring all four claims to be present. The `anon` and `service_role` API
keys are HS256 project keys, not user tokens, and are rejected.

Seven offline tests in `backend/tests/test_jwt_verification.py` mint an EC keypair
and cover: a valid token, expiry, a foreign issuer, a wrong audience, a token
signed by another key, an `alg: none` token, and that the user object's `repr`
does not print a whole user id.

Role is never read from a token claim - it is looked up in `user_roles` with the
service role, so editing a claim gains nothing.

## Seeds

- `supabase/seed.sql` - five plants and sixteen aliases. Reference data, safe
  anywhere. **Not** a catalogue: every row is a human decision, never bulk
  generated.
- `supabase/seeds/dev_mock.sql` - mock research rows, every readable field prefixed
  with a Hebrew or English mock marker. It raises an exception unless the caller
  first sets `app.allow_mock_seed = 'yes'`, and that guard is tested - running it
  without the setting fails with `P0001: refusing to seed mock data`.

## Migration and rollback

Migrations live in `supabase/migrations/` and are applied with:

```bash
npx supabase db push --project-ref <ref> -p <db-password>
```

`supabase link` fails on this machine (`AlreadyExists: supabase/.temp`), so
`--project-ref` is passed directly. There is no local stack - Docker is not
installed - so `supabase start` and `db diff` are unavailable and every migration
is written by hand and applied to `dev` first.

Rollback is a new forward migration, never an edit to an applied file. The one
exception is a migration that has not yet been pushed anywhere, which may still be
corrected in place.
