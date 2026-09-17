-- Pilot comprehension measurement.
--
-- The pilot measures whether people understood the finding, its certainty,
-- whether it concerned humans, and whether a dose described in a study is a
-- personal recommendation. It does not measure whether they liked the answer.
--
-- The answer key lives here rather than in the response body, because the body
-- is readable by the participant. A participant who can read the key is not
-- being measured.

create table public.pilot_answer_keys (
  response_version_id bigint primary key
    references public.response_versions (id) on delete cascade,
  questionnaire_version text not null,
  -- {question_id: correct_option_id}
  answers jsonb not null,
  approved_by uuid not null references auth.users (id),
  approved_at timestamptz not null default now()
);

comment on table public.pilot_answer_keys is
  'Never readable by a participant. No grants, no policies - service role only.';

alter table public.pilot_answer_keys enable row level security;
alter table public.pilot_answer_keys force row level security;

-- No grants and no policies: unreachable from any client role, like the rest of
-- the staff tables.

-- A participant answers each phase once per questionnaire version. The existing
-- unique constraint on pilot_assessments already enforces that; this index makes
-- the per-response lookup cheap.
create index pilot_assessments_user_response_idx
  on public.pilot_assessments (user_id, response_version_id);

-- Scoring is computed and stored when the assessment is submitted, so a later
-- edit to the key cannot silently rewrite history.
alter table public.pilot_assessments
  add column score int check (score is null or score >= 0),
  add column max_score int check (max_score is null or max_score >= 0),
  add column scored_against_key_at timestamptz;

comment on column public.pilot_assessments.score is
  'Computed at submission against the key as it stood then. Null means unscored.';
