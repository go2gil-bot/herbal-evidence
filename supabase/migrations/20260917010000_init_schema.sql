-- Herbal Evidence: core schema.
--
-- Two rules shape every table here:
--   1. Reusable research content never carries personal information.
--   2. Drafts are not "hidden" - they are unreachable for non-staff roles.
--      Authorization lives in RLS and column grants (see the rls migration),
--      never in the absence of a UI button.

create schema if not exists private;
revoke all on schema private from public;

-- ---------------------------------------------------------------- helpers

create or replace function private.touch_updated_at()
returns trigger language plpgsql as $fn$
begin
  new.updated_at = now();
  return new;
end;
$fn$;

-- ---------------------------------------------------------------- identity

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  -- Pilot participant category. Deliberately NOT a medical profile.
  participant_category text check (participant_category in ('patient', 'caregiver', 'staff')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.profiles is
  'Minimal display information. No medical profile, no national id, no records.';

create trigger profiles_touch before update on public.profiles
  for each row execute function private.touch_updated_at();

-- Server-managed. No client role may write here; see the rls migration.
create table public.user_roles (
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('researcher', 'admin')),
  granted_by uuid references auth.users (id),
  granted_at timestamptz not null default now(),
  primary key (user_id, role)
);

-- Role lookups run after user_roles exists, because a SQL-language body is
-- validated at creation time. They bypass RLS on purpose, so each one checks the
-- CALLING user's id explicitly. Execute is revoked from client roles later.
create or replace function private.has_role(p_role text)
returns boolean language sql stable security definer set search_path = '' as $fn$
  select exists (
    select 1 from public.user_roles ur
    where ur.user_id = (select auth.uid()) and ur.role = p_role
  );
$fn$;

create or replace function private.is_staff()
returns boolean language sql stable security definer set search_path = '' as $fn$
  select exists (
    select 1 from public.user_roles ur
    where ur.user_id = (select auth.uid()) and ur.role in ('researcher', 'admin')
  );
$fn$;

create or replace function private.is_admin()
returns boolean language sql stable security definer set search_path = '' as $fn$
  select private.has_role('admin');
$fn$;

-- ---------------------------------------------------------------- catalogue

create table public.plants (
  id bigint generated always as identity primary key,
  scientific_name text not null unique,
  created_at timestamptz not null default now()
);

comment on table public.plants is
  'Seeded only with entries a human verified. Never auto-populated from a model.';

create table public.plant_aliases (
  id bigint generated always as identity primary key,
  plant_id bigint not null references public.plants (id) on delete cascade,
  alias text not null,
  language text not null check (language in ('he', 'en', 'la', 'ar', 'ru')),
  alias_kind text not null check (alias_kind in ('common', 'scientific', 'synonym', 'trade')),
  created_at timestamptz not null default now(),
  unique (plant_id, alias, language)
);

create index plant_aliases_plant_id_idx on public.plant_aliases (plant_id);
create index plant_aliases_alias_lower_idx on public.plant_aliases (lower(alias));

-- Normalized question used to group research across requests. Carries no owner.
create table public.research_questions (
  id bigint generated always as identity primary key,
  plant_id bigint references public.plants (id),
  normalized_question text not null,
  preparation text,
  population text,
  treatment_context text,
  created_at timestamptz not null default now()
);

comment on table public.research_questions is
  'Groups research work only. Requests point here; ownership never flows back.';

create index research_questions_plant_id_idx on public.research_questions (plant_id);

-- ---------------------------------------------------------------- requests

create table public.requests (
  id bigint generated always as identity (start with 1000) primary key,
  owner_id uuid not null references auth.users (id) on delete cascade,

  herb_input text not null check (length(btrim(herb_input)) > 0),
  preparation_input text,
  cancer_type_input text,
  treatment_input text,
  question_input text check (question_input is null or length(question_input) <= 1000),

  preparation_unknown boolean not null default false,
  cancer_type_unknown boolean not null default false,
  treatment_unknown boolean not null default false,

  identified_plant_id bigint references public.plants (id),
  identification_state text not null default 'pending'
    check (identification_state in ('pending', 'resolved', 'ambiguous', 'multi_ingredient', 'out_of_scope')),
  research_question_id bigint references public.research_questions (id),

  status text not null default 'submitted' check (status in (
    'submitted', 'needs_clarification', 'queued', 'researching',
    'draft_ready', 'in_review', 'revision_required', 'published', 'closed_out_of_scope'
  )),
  assigned_researcher_id uuid references auth.users (id),
  closed_reason text,

  -- What the requester is allowed to see. Internal status is not granted to them.
  user_visible_status text generated always as (
    case status
      when 'submitted' then 'received'
      when 'needs_clarification' then 'clarification_needed'
      when 'published' then 'response_available'
      when 'closed_out_of_scope' then 'closed'
      else 'under_review'
    end
  ) stored,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint requests_closed_needs_reason
    check (status <> 'closed_out_of_scope' or closed_reason is not null)
);

comment on column public.requests.user_visible_status is
  'Five states only. Internal processing detail never reaches the requester.';

create index requests_owner_id_idx on public.requests (owner_id);
create index requests_assigned_researcher_idx on public.requests (assigned_researcher_id);
create index requests_identified_plant_idx on public.requests (identified_plant_id);
create index requests_research_question_idx on public.requests (research_question_id);
create index requests_queue_idx on public.requests (status, created_at);

create trigger requests_touch before update on public.requests
  for each row execute function private.touch_updated_at();

create table public.request_clarifications (
  id bigint generated always as identity primary key,
  request_id bigint not null references public.requests (id) on delete cascade,
  asked_by uuid not null references auth.users (id),
  question text not null,
  answer text,
  asked_at timestamptz not null default now(),
  answered_at timestamptz
);

create index request_clarifications_request_id_idx on public.request_clarifications (request_id);

-- The requester may write `answer`; the timestamp is not theirs to set.
create or replace function private.stamp_clarification_answer()
returns trigger language plpgsql as $fn$
begin
  if new.answer is distinct from old.answer and new.answer is not null then
    new.answered_at = now();
  end if;
  return new;
end;
$fn$;

create trigger request_clarifications_stamp before update on public.request_clarifications
  for each row execute function private.stamp_clarification_answer();
