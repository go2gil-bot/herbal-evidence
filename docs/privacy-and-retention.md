# Privacy and retention

**This describes what the system currently does. It is not an approved policy,
and it does not claim compliance with any regulation.** Retention periods, the
consent wording and the legal basis are open decisions for the team; nothing here
should be published to users as a privacy policy without that work being done.

## What is collected

| Data | Why | Where |
|---|---|---|
| Email and password | To sign in and to hold a response for one person | Supabase Auth |
| Herb name | The question being asked | `requests.herb_input` |
| Preparation, cancer type, treatment (optional) | To focus the literature search | `requests.*_input` |
| Free-text question (optional, ≤1000 chars) | Context for the researcher | `requests.question_input` |
| Clarification answers | The same | `request_clarifications.answer` |
| Pilot questionnaire answers | To measure comprehension | `pilot_assessments.answers` |

## What is deliberately not collected

No full medical profile. No national identification number. No medical records.
No uploaded documents from users. No date of birth, no address, no phone number.

The optional fields are free text, so a user *can* type something identifying
into them. The form says these details focus the search rather than establish
personal suitability, which is also a nudge to keep them short - but the
possibility is real and the retention decision should account for it.

## Who can see what

| Who | Can read |
|---|---|
| The requester | Their own requests, their clarifications, and **published** responses on them |
| Anyone else signed in | Nothing of theirs |
| Anonymous | Nothing at all |
| A researcher | Requests assigned to them, through the backend only |
| An administrator | The queue, assignments, and staff roles |

This is enforced by Row Level Security and column-level grants, not by the user
interface. A requester's token cannot read `requests.status`, a draft response,
or any staff table, even when used directly against the database. Verified by
`supabase/tests/rls_isolation.py`.

Staff do not read these tables from a browser at all - every staff operation goes
through the backend, which authorizes the caller server-side.

## What leaves the system

**To the AI provider:** the question, the herb, preparation, population and
treatment context as supplied, plus metadata about retrieved sources. No email,
no user id, no request id, no name. The provider therefore receives a research
question, not a person.

**To PubMed and Europe PMC:** a boolean query built from the herb name and
appetite terms. Nothing from the user's free text is sent. NCBI asks callers to
identify themselves with a contact address; that address is configuration and is
never taken from a user's account.

**Nowhere else.** Outbound HTTP is restricted to two allowlisted hosts.

## Logs

Logs carry request and job identifiers, HTTP statuses and error types. They do
not carry question text, treatment details, email addresses, tokens or article
bodies.

`audit_events` records who did what to which entity. Its `metadata` is limited to
identifiers and outcomes - a status transition records `from` and `to`, not the
content that changed. This is a convention enforced at each call site, not by the
database; a reviewer adding an audit call should keep it.

## Reuse between requests

Requests stay separate. Research work is reused through `reviews` and
`review_versions`, which are written to contain no personal information - they
hang off a normalized research question, not off a requester.

Two similar requests each get their own response and each needs its own approval.
Accounts are never merged, a user's request is never deleted to deduplicate, and
nothing is published automatically because it resembles something already
answered.

## Retention - open

Nothing is deleted automatically today. Decisions still needed:

- how long a request and its response are kept after publication
- what happens when a user asks for deletion: does the response go, the account,
  or both, and what happens to the reusable review derived from it
- how long job errors and `search_runs` rows are kept
- whether pilot questionnaire answers are kept beyond the pilot, and in what form

Deleting a Supabase Auth user cascades to `profiles`, `requests` (and their
clarifications and responses) and `pilot_assessments`. `audit_events.actor_id`
is set to null rather than cascading, so the audit trail survives without naming
a deleted person. That behaviour is implemented; whether it is the *right*
behaviour is part of the open decision.

## Development data

The `dev` Supabase project contains invented data only. Every mock row carries a
visible marker, and `supabase/seeds/dev_mock.sql` refuses to run unless a caller
sets `app.allow_mock_seed` first.

**No real patient data belongs in `dev`.** The production project was created
empty and verified to hold zero requests and zero sources.

## What we do not claim

We have not had this reviewed by a lawyer or a privacy officer. We do not claim
GDPR, HIPAA or Israeli Privacy Protection Law compliance. We do not claim medical
device status or any clinical validation. Saying otherwise in user-facing copy
would be a false statement, not a marketing choice.
