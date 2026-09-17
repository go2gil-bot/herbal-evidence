# What is done, what is blocked, what is untested

Written 2026-09-17. This is the honest inventory; read it before claiming
anything about the platform.

## Working and verified

| Area | State |
|---|---|
| Schema, RLS, column grants | 17 tables, RLS on all, advisors clean on both projects |
| Requester journey | Registration, request, identification, waiting state, clarifications, reading a response |
| Researcher workspace | Queue, request detail, review editor, approval, withdrawal, job failures |
| Approval | Atomic, bound to a content hash, four explicit confirmations |
| Job queue | Postgres-backed, leases, heartbeats, bounded retries, restart-recoverable |
| Literature search | PubMed and Europe PMC, live, with per-provider run records |
| Labelling | From MeSH headings and publication types, not from titles |
| AI drafts | Real `gpt-5.2` integration, strict output schema, validators on the way back |
| Pilot | Four comprehension questions, pre and post, researcher-approved answer key |
| Deployment | Two Railway environments, four services, branch wiring verified both ways |

## Blocked or not built

| Item | Why | What it would take |
|---|---|---|
| **Structured extraction (`extract` job)** | Needs full article text, which needs uploads | Storage buckets, an upload flow, then extraction into `evidence_items` |
| **Article upload to Storage** | No buckets exist | Buckets with policies, an upload endpoint, provenance recording |
| **Full-text reading** | Only abstracts and metadata are retrieved. `access_level` says `full_text` when the provider reports open access, but the text itself is not fetched or parsed | An open-access fetcher for PMC, within its terms |
| **Auth emails at any volume** | Supabase's built-in sender is rate limited and documented as test-only | SMTP configured per project, plus Site URL and redirect allow-lists |
| **Review repository reuse in the UI** | The API groups requests onto a research question and reuses review versions; no screen drives it | A "reuse this review" action in the editor |
| **`extract` and `draft` from full text** | Both currently reason over titles and metadata only | Depends on the three items above |

## Untested

| Item | Why it is untested |
|---|---|
| **Scientific quality of any output** | No automated test can establish it. The team must read sample responses against their sources before a real pilot |
| **Concurrent load** | One job at a time per process, never tested under real traffic |
| **The Dockerfiles locally** | Docker is not installed on the development machine. They build and run on Railway, which is the verification that matters, but a local `docker build` has never run |
| **Production under real use** | Production is deployed, healthy and empty. Nobody has used it |
| **Screen reader end to end** | Structural checks pass - labels, one exposed h1, focus outlines, RTL. No assistive technology has actually driven the app |
| **Rate limits** | Not implemented. Nothing stops a signed-in user submitting requests in a loop |
| **CSP** | Security headers are set (`nosniff`, `X-Frame-Options`, referrer policy) but no Content-Security-Policy header |

## Open decisions - not ours to invent

These are recorded as open in `docs/privacy-and-retention.md` and elsewhere, and
deliberately have no default in the code:

- **Retention periods.** Nothing is deleted automatically today
- **What deletion means** when a user asks - the response, the account, or both,
  and what happens to the reusable review derived from it
- **Consent wording and legal basis.** The privacy document describes behaviour,
  not policy, and claims compliance with nothing
- **Pilot sample size and success target.** The pilot reports descriptive numbers
  and says explicitly that they establish nothing
- **How requests are assigned to researchers.** An admin assigns manually; the
  mechanism is one column and is meant to be replaced
- **Whether researchers should read requests outside their assignment**

## Things that are true and easy to misread

- **A `not_configured` job failure is not a bug.** It is what a missing provider
  is supposed to look like.
- **`is_oncology = null` does not mean "not oncology".** It means the record was
  not indexed for it.
- **`access_level = full_text` means the provider says the text is available**,
  not that we read it.
- **The AI draft is a draft.** It has seen titles and metadata, not papers. Every
  sentence is unverified until a researcher checks it.
- **Production is empty on purpose.** It is not broken.

## Costs

- Two Supabase projects on the free plan. Two active projects is the cap for that
  organization, so a third environment would need one paused first.
- Railway bills by usage across four service instances.
- OpenAI bills per draft - roughly 3,700 tokens for the one measured. A usage
  limit in the OpenAI account is worth setting; the queue's bounded retries limit
  the damage from a loop but do not cap spend.
