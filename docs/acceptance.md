# Acceptance criteria

The twelve criteria from the specification, each with where it is verified and
what the last run said. Dates are 2026-09-17; the suites ran against the deployed
`dev` backend and the live `herbal-evidence-dev` project.

## Where to run them

```bash
cd backend && .venv/Scripts/python -m pytest -q          # 75 offline tests

# live, against dev - never Production
python supabase/tests/rls_isolation.py                   # 24 checks
python supabase/tests/staff_flow.py                      # 12 checks
python supabase/tests/literature_search.py               # 22 checks, hits real providers
python supabase/tests/reuse_and_recovery.py              # 14 checks

# against the deployed backend instead of a local one
API=https://backend-dev-001e.up.railway.app python supabase/tests/staff_flow.py
```

## The twelve

| # | Criterion | Verified by | Result |
|---|---|---|---|
| 1 | User A cannot read User B's requests or responses, through the API or through Supabase | `rls_isolation.py` - two real users, real tokens, direct PostgREST calls | ✅ |
| 2 | Users cannot read drafts or publish, including through direct calls and modified payloads | `rls_isolation.py` + `test_api_authorization.py` | ✅ |
| 3 | A researcher approves a specific version; concurrent edits cannot be published accidentally | `staff_flow.py` - a draft is edited between reading and approving, and approval is refused | ✅ |
| 4 | Similar requests reuse research without sharing personal details or skipping approval | `reuse_and_recovery.py` | ✅ |
| 5 | Provider or search failure does not become a conclusion that evidence is absent | `staff_flow.py`, `literature_search.py`, constraints on `search_runs` | ✅ |
| 6 | Unsupported claims are flagged; citations and missing data are not fabricated | `test_research.py` validators + `literature_search.py` checks every claim cites a source that exists | ✅ |
| 7 | Abstract-only access is labelled, and animal findings are not presented as human evidence | `test_research.py` labelling tests + `literature_search.py` | ✅ |
| 8 | A backend restart does not lose a job or publish its result twice | `reuse_and_recovery.py` - lease expiry, reclaim, and refusal to complete from the worker that lost it | ✅ |
| 9 | RTL, mobile layouts, basic accessibility and error states work | Browser checks against the deployed dev site - see below | ✅ |
| 10 | All four service instances, both branches and both Supabase projects are connected with no cross-environment access | Stage 7 - see `docs/deployment.md` | ✅ |
| 11 | End to end: registration, request, processing, researcher review, approval, reading the response | `staff_flow.py` + `literature_search.py` + browser walkthrough | ✅ |
| 12 | Mock content is limited to development; no simulated research output appears in live operation | Production verified empty; the mock seed refuses to run without being told to | ✅ |

## Criterion 9 in detail

Checked against `https://frontend-dev-62e0.up.railway.app`:

- every page: `lang="he"`, `dir="rtl"`, a viewport meta tag, one `<h1>` exposed
- every visible input has a label - none rely on a placeholder
- at 375px: **zero** horizontal overflow, no element past the right edge
- `:focus-visible` gives a 3px outline on inputs, buttons and links
- submitting the request form empty shows a Hebrew error and moves focus to the field
- status is always a word; colour is a secondary cue and never the message

`staff.html` has four `<h1>` elements in the DOM, one per tab panel. Only the
visible panel is exposed - `hidden` removes the others from the accessibility
tree - so a screen reader encounters exactly one.

## Criterion 12 in detail

`herbal-evidence-prod` was created empty and verified: **0 requests, 0 sources**,
five reference plants, RLS on all 17 tables, security advisors clean.

`supabase/seeds/dev_mock.sql` aborts unless `app.allow_mock_seed` is set to
`yes`. That guard is tested - running it without the setting fails with
`P0001: refusing to seed mock data`.

## Auth email, verified 2026-09-19

A confirmation email sent through Brevo from the dev project reached a real
Gmail inbox. Following a link is verified separately for each outcome, because
until 2026-09-19 all three rendered the same plain login form:

| Link outcome | What the page does |
|---|---|
| Confirmed | Says so, signs the person in, offers the dashboard |
| Expired (`otp_expired`) | Says the link expired and offers to send a new one |
| Recovery | Opens the form that sets a new password |

Checked against the deployed `dev` site, not only locally. The resend reports
the same message whether or not the address exists.

Not established: that mail reaches inboxes rather than spam folders at any
volume. The sender is a free webmail address and fails the recipient's DMARC
check - see `docs/limitations.md`.

## What these tests do not establish

**Automated structural and permission tests do not establish scientific
quality.** Nothing here checks whether a published review is *correct* - only
that it could not be published without a person confirming they checked it.

Before any real pilot, the team must read sample outputs against their sources.
That is a human step and this file cannot stand in for it.
