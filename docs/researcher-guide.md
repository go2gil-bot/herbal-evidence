# Researcher guide

You are the last check before a person who is unwell reads this. The system can
refuse obvious mistakes; it cannot tell whether a sentence is true.

## What the platform is answering

One herb, one outcome: **appetite**. Not weight, not food intake, not quality of
life - those are separate secondary outcomes and are reported separately.

The user chose the herb. We do not recommend one, do not prescribe a dose, and do
not approve combining anything with their treatment.

## The queue

Open **תור הבקשות**. By default you see what is assigned to you; administrators
see everything and do the assigning.

Each request shows its herb, preparation, age in days and internal status. The
requester sees only five simple states and never the internal one.

### When the herb is not resolved

`ambiguous` means several plants share the name the user typed - the user is
asked to choose, not the system. `pending` means nothing matched and a human has
to look. Both are normal outcomes, not errors.

If the user described a multi-ingredient product, ask them to pick one herb or
close the request as out of scope with an explanation.

## Working a request

1. **Read what was actually submitted.** Optional fields are often empty. An
   empty field means unknown - never fill it in from what seems likely.
2. **Ask a clarification** if the request is ambiguous. Keep it to one or two
   specific questions. The user answers once, in a short form; it is not a chat.
3. **Run the literature search** from the request page. It queries PubMed and
   Europe PMC and stores what it finds, labelled.
4. **Check the labels.** They come from MeSH headings, which are usually right
   and occasionally are not. `is_oncology` may be blank - that means the record
   was not indexed for it, not that the study sat outside oncology.
5. **Generate a draft**, or write one by hand. Either way it is a draft.
6. **Edit it.** The draft is a starting point written by a model that has seen
   only titles and metadata. Treat every sentence as unverified.

## Checking a draft

Read each claim against the source it names. If a claim has no source, or the
source does not say what the claim says, delete or correct it.

Specific things to look for:

| Look for | Why |
|---|---|
| A weight or intake result presented as an appetite finding | They are different outcomes |
| An animal or lab finding used as evidence about people | It is not |
| "Safe" resting on nothing having been reported | Absence of reports is not safety |
| A study in a different population read as directly relevant | That is indirect evidence; say so |
| A preparation mismatch - an extract study answering a question about tea | Common and easy to miss |
| A review counted alongside the trial it discusses | That is one body of evidence, not two |
| A confident conclusion from abstracts alone | Note that the full text was not read |

### When there is not enough evidence

That is a real answer and often the right one. Write it plainly:

> אין מספיק ראיות מבני אדם כדי להעריך תועלת לשיפור תיאבון בהקשר שנבדק.

Distinguish three different situations, because they are not the same thing:

- **not studied** - nobody looked
- **inconclusive** - people looked and the results do not settle it
- **no benefit found** - people looked and did not find one

If a search failed technically, that is not any of the three. Retry it; never
write "no studies exist" because a provider was down.

### Certainty

A word, with an explanation: how many studies, of what quality, how consistent,
how directly they bear on this question, and what limits them.

Allowed words: גבוהה · בינונית · נמוכה · נמוכה מאוד · לא ניתן להעריך

No numeric score. Do not call it GRADE - we have not implemented that
methodology, and naming it would claim something untrue.

## Approving

Approval binds to the exact text you read. The four confirmations are not a
formality:

- **המקורות** - they exist, and they say what the draft says they say
- **התאמה בין טענה לראיה** - each claim is supported by the source it names
- **המגבלות** - what is missing and what conflicts is visible to the reader
- **הניסוח** - a worried reader will understand it and will not over-read it

If someone edits the draft while you are reading it, approval fails with a
message saying so. That is intended. Re-read the new version; do not approve
what you did not read.

## After publishing

A published response can be withdrawn with a reason. Withdrawn content stops
being shown to the user immediately - it does not linger as an approved answer.

To publish a corrected version, create a new draft and approve it. The previous
version becomes `superseded` inside the same transaction, so the user is never
briefly left with two answers or none.

## When something is broken

Job failures appear under **עבודות ותקלות** with their error and a retry button.
While a job is failing, the user sees only "בבדיקה". They are never shown a
draft, a partial result, or an estimated time.

If the AI provider is not configured, draft jobs record `not_configured` and
produce nothing. That is by design - there is no placeholder draft, because a
plausible wrong draft is more dangerous than no draft.

## Things the system will not let you do

Not restrictions to work around - each one exists because of a specific failure:

- publish by setting a status
- approve without all four confirmations
- approve a version that changed since you read it
- store a claim with no supporting location
- have two published versions of one response
- close a request without an explanation for the user
