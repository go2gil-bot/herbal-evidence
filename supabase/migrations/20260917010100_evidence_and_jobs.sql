-- Evidence, reviews, personalized responses, the durable job queue, audit and pilot.

-- ---------------------------------------------------------------- evidence

create table public.sources (
  id bigint generated always as identity primary key,
  id_kind text not null check (id_kind in ('pmid', 'doi', 'pmcid', 'url', 'manual')),
  external_id text not null,
  title text not null,
  journal text,
  publication_year int check (publication_year between 1800 and 2100),
  url text,

  -- Human / animal / lab is a labelling decision, never an inference at read time.
  evidence_type text not null check (evidence_type in ('human', 'animal', 'in_vitro', 'review', 'other')),
  study_design text,
  -- False means the finding is INDIRECT evidence for an oncology population.
  is_oncology boolean,

  access_level text not null check (access_level in ('full_text', 'abstract_only', 'not_accessed')),
  file_provenance text,
  storage_path text,
  retrieved_at timestamptz not null default now(),
  created_at timestamptz not null default now(),

  unique (id_kind, external_id)
);

comment on column public.sources.access_level is
  'Abstract-only must stay visible downstream. Paywalls are never bypassed.';

create index sources_evidence_type_idx on public.sources (evidence_type);

create table public.evidence_items (
  id bigint generated always as identity primary key,
  source_id bigint not null references public.sources (id) on delete cascade,
  research_question_id bigint references public.research_questions (id) on delete set null,

  population text,
  sample_size int check (sample_size is null or sample_size > 0),
  intervention text,
  comparator text,
  outcome text,
  measurement_method text,
  result text,
  uncertainty text,
  safety text,
  limitations text,

  -- A substantive claim must name where it is supported. No invented page numbers.
  claim text,
  support_kind text check (support_kind in ('full_text_location', 'abstract_passage')),
  support_location text,

  created_at timestamptz not null default now(),

  constraint evidence_items_claim_needs_support
    check (claim is null or (support_kind is not null and length(btrim(coalesce(support_location, ''))) > 0))
);

comment on constraint evidence_items_claim_needs_support on public.evidence_items is
  'Unreported fields stay null. A claim without a supporting location cannot be stored.';

create index evidence_items_source_id_idx on public.evidence_items (source_id);
create index evidence_items_research_question_idx on public.evidence_items (research_question_id);

-- ---------------------------------------------------------------- reviews

create table public.reviews (
  id bigint generated always as identity primary key,
  research_question_id bigint not null references public.research_questions (id) on delete cascade,
  created_at timestamptz not null default now()
);

comment on table public.reviews is
  'Reusable across requests. Must never contain personal information.';

create index reviews_research_question_idx on public.reviews (research_question_id);

create table public.review_versions (
  id bigint generated always as identity primary key,
  review_id bigint not null references public.reviews (id) on delete cascade,
  version int not null check (version > 0),
  body jsonb not null,
  literature_search_date date,
  source_ids bigint[] not null default '{}',
  content_hash text not null,
  approved_by uuid references auth.users (id),
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  unique (review_id, version)
);

create index review_versions_review_id_idx on public.review_versions (review_id);

-- ---------------------------------------------------------------- responses

create table public.response_versions (
  id bigint generated always as identity primary key,
  request_id bigint not null references public.requests (id) on delete cascade,
  version int not null check (version > 0),
  body jsonb not null,
  review_version_id bigint references public.review_versions (id),
  source_ids bigint[] not null default '{}',
  content_hash text not null,

  state text not null default 'draft'
    check (state in ('draft', 'published', 'superseded', 'withdrawn')),
  published_at timestamptz,
  withdrawn_at timestamptz,
  withdrawn_reason text,

  -- Provenance of the draft. Never shown to the requester.
  ai_provider text,
  ai_model text,
  prompt_version text,
  generated_at timestamptz,

  created_at timestamptz not null default now(),

  unique (request_id, version),
  constraint response_versions_published_has_time
    check (state <> 'published' or published_at is not null),
  constraint response_versions_withdrawn_has_reason
    check (state <> 'withdrawn' or (withdrawn_at is not null and withdrawn_reason is not null))
);

comment on table public.response_versions is
  'Personalized. A draft is reachable only through the backend service role.';

create index response_versions_request_id_idx on public.response_versions (request_id);
create index response_versions_review_version_idx on public.response_versions (review_version_id);

-- An update draft cannot replace a published version until it is approved.
create unique index response_versions_single_published
  on public.response_versions (request_id) where state = 'published';

create table public.approvals (
  id bigint generated always as identity primary key,
  response_version_id bigint not null unique references public.response_versions (id) on delete cascade,
  approved_by uuid not null references auth.users (id),
  approved_at timestamptz not null default now(),
  -- The exact content that was approved. Mismatch means the draft moved.
  approved_content_hash text not null,

  checked_sources boolean not null,
  checked_claim_evidence_alignment boolean not null,
  checked_limitations boolean not null,
  checked_user_wording boolean not null,

  constraint approvals_requires_every_check
    check (checked_sources and checked_claim_evidence_alignment
           and checked_limitations and checked_user_wording)
);

comment on constraint approvals_requires_every_check on public.approvals is
  'Filling fields does not approve anything. All four checks are explicit and required.';

create index approvals_approved_by_idx on public.approvals (approved_by);

-- ---------------------------------------------------------------- job queue

create table public.research_jobs (
  id bigint generated always as identity primary key,
  request_id bigint not null references public.requests (id) on delete cascade,
  job_type text not null check (job_type in ('identify_plant', 'literature_search', 'extract', 'draft')),
  idempotency_key text not null unique,

  state text not null default 'queued' check (state in ('queued', 'running', 'succeeded', 'failed', 'dead')),
  attempts int not null default 0,
  max_attempts int not null default 3 check (max_attempts > 0),
  run_after timestamptz not null default now(),

  locked_by text,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,

  -- Processing failure lives here, never on the request status.
  last_error jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint research_jobs_failure_has_error
    check (state not in ('failed', 'dead') or last_error is not null)
);

comment on constraint research_jobs_failure_has_error on public.research_jobs is
  'A failure must carry its reason. A failed search is never a finding of no evidence.';

create index research_jobs_request_id_idx on public.research_jobs (request_id);
create index research_jobs_claimable_idx on public.research_jobs (run_after)
  where state in ('queued', 'running');

create trigger research_jobs_touch before update on public.research_jobs
  for each row execute function private.touch_updated_at();

create table public.search_runs (
  id bigint generated always as identity primary key,
  research_job_id bigint not null references public.research_jobs (id) on delete cascade,
  provider text not null,
  query text not null,
  status text not null check (status in ('succeeded', 'failed', 'partial')),
  result_count int check (result_count is null or result_count >= 0),
  error jsonb,
  ran_at timestamptz not null default now(),

  constraint search_runs_failure_has_error
    check (status = 'succeeded' or error is not null),
  constraint search_runs_success_has_count
    check (status <> 'succeeded' or result_count is not null)
);

comment on table public.search_runs is
  'Zero results and a failed search are different rows. Never collapse them.';

create index search_runs_job_id_idx on public.search_runs (research_job_id);

-- ---------------------------------------------------------------- audit, pilot

create table public.audit_events (
  id bigint generated always as identity primary key,
  actor_id uuid references auth.users (id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id text not null,
  -- Identifiers and outcomes only. No question text, no treatment detail, no article body.
  metadata jsonb,
  created_at timestamptz not null default now()
);

create index audit_events_entity_idx on public.audit_events (entity_type, entity_id);
create index audit_events_created_at_idx on public.audit_events (created_at desc);

create table public.pilot_assessments (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  response_version_id bigint references public.response_versions (id) on delete set null,
  questionnaire_version text not null,
  phase text not null check (phase in ('pre', 'post')),
  answers jsonb not null,
  -- Patients and caregivers are analysed separately.
  participant_category text check (participant_category in ('patient', 'caregiver')),
  created_at timestamptz not null default now(),
  unique (user_id, response_version_id, phase, questionnaire_version)
);

create index pilot_assessments_response_version_idx on public.pilot_assessments (response_version_id);
