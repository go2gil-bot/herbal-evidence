-- Row Level Security and privileges.
--
-- The model, in one sentence: client roles start with NOTHING, and get back only
-- the exact columns of the exact rows a requester owns.
--
-- Staff (researchers, admins) do NOT read these tables from the client. All staff
-- access goes through the backend with the service role, which authorizes every
-- operation server-side (decision D-011). That is why there are no staff policies
-- here: a researcher pointing supabase-js at this database sees nothing, and a
-- leaked staff JWT is not a read primitive.

-- ------------------------------------------------- start from zero

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all routines in schema public from anon, authenticated;

revoke all on all routines in schema private from public, anon, authenticated, service_role;

-- New tables must not inherit grants either.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on routines from anon, authenticated;

-- ------------------------------------------------- enable RLS everywhere

alter table public.profiles               enable row level security;
alter table public.user_roles             enable row level security;
alter table public.plants                 enable row level security;
alter table public.plant_aliases          enable row level security;
alter table public.research_questions     enable row level security;
alter table public.requests               enable row level security;
alter table public.request_clarifications enable row level security;
alter table public.sources                enable row level security;
alter table public.evidence_items         enable row level security;
alter table public.reviews                enable row level security;
alter table public.review_versions        enable row level security;
alter table public.response_versions      enable row level security;
alter table public.approvals              enable row level security;
alter table public.research_jobs          enable row level security;
alter table public.search_runs            enable row level security;
alter table public.audit_events           enable row level security;
alter table public.pilot_assessments      enable row level security;

alter table public.profiles               force row level security;
alter table public.user_roles             force row level security;
alter table public.research_questions     force row level security;
alter table public.requests               force row level security;
alter table public.request_clarifications force row level security;
alter table public.sources                force row level security;
alter table public.evidence_items         force row level security;
alter table public.reviews                force row level security;
alter table public.review_versions        force row level security;
alter table public.response_versions      force row level security;
alter table public.approvals              force row level security;
alter table public.research_jobs          force row level security;
alter table public.search_runs            force row level security;
alter table public.audit_events           force row level security;
alter table public.pilot_assessments      force row level security;

-- ------------------------------------------------- profiles

grant select (id, display_name, participant_category, created_at) on public.profiles to authenticated;
grant insert (id, display_name, participant_category) on public.profiles to authenticated;
grant update (display_name, participant_category) on public.profiles to authenticated;

create policy profiles_select_own on public.profiles
  for select to authenticated
  using (id = (select auth.uid()));

create policy profiles_insert_own on public.profiles
  for insert to authenticated
  with check (id = (select auth.uid()));

create policy profiles_update_own on public.profiles
  for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

-- ------------------------------------------------- user_roles (read-only, server-managed)

grant select (user_id, role) on public.user_roles to authenticated;

create policy user_roles_select_own on public.user_roles
  for select to authenticated
  using (user_id = (select auth.uid()));

-- No insert/update/delete grant and no policy: a user cannot promote themselves.

-- ------------------------------------------------- plant catalogue (reference data)

grant select on public.plants to authenticated;
grant select on public.plant_aliases to authenticated;

create policy plants_select_all on public.plants
  for select to authenticated using (true);

create policy plant_aliases_select_all on public.plant_aliases
  for select to authenticated using (true);

-- ------------------------------------------------- requests

-- Note the columns that are NOT granted: status, assigned_researcher_id and
-- research_question_id. The requester reads user_visible_status instead.
grant select (
  id, owner_id, herb_input, preparation_input, cancer_type_input, treatment_input,
  question_input, preparation_unknown, cancer_type_unknown, treatment_unknown,
  identified_plant_id, identification_state, user_visible_status, closed_reason,
  created_at, updated_at
) on public.requests to authenticated;

-- A requester may only submit the inputs. Status and assignment are server-side.
grant insert (
  owner_id, herb_input, preparation_input, cancer_type_input, treatment_input,
  question_input, preparation_unknown, cancer_type_unknown, treatment_unknown
) on public.requests to authenticated;

create policy requests_select_own on public.requests
  for select to authenticated
  using (owner_id = (select auth.uid()));

create policy requests_insert_own on public.requests
  for insert to authenticated
  with check (owner_id = (select auth.uid()));

-- No update policy: a requester cannot edit a submitted request, and cannot
-- touch role, status or approval fields through any payload.

-- ------------------------------------------------- clarifications

grant select (id, request_id, question, answer, asked_at, answered_at)
  on public.request_clarifications to authenticated;
grant update (answer) on public.request_clarifications to authenticated;

create policy clarifications_select_own on public.request_clarifications
  for select to authenticated
  using (exists (
    select 1 from public.requests r
    where r.id = request_id and r.owner_id = (select auth.uid())
  ));

-- Answer once. An answered clarification is part of the record, not a scratchpad.
create policy clarifications_answer_own on public.request_clarifications
  for update to authenticated
  using (
    answer is null
    and exists (
      select 1 from public.requests r
      where r.id = request_id and r.owner_id = (select auth.uid())
    )
  )
  with check (exists (
    select 1 from public.requests r
    where r.id = request_id and r.owner_id = (select auth.uid())
  ));

-- ------------------------------------------------- responses

-- Drafts and withdrawn versions are not selectable: the policy names 'published'
-- explicitly, and provenance columns are not granted at all.
grant select (id, request_id, version, body, published_at, created_at)
  on public.response_versions to authenticated;

create policy response_versions_select_published_own on public.response_versions
  for select to authenticated
  using (
    state = 'published'
    and exists (
      select 1 from public.requests r
      where r.id = request_id and r.owner_id = (select auth.uid())
    )
  );

-- ------------------------------------------------- pilot

grant select (id, user_id, response_version_id, questionnaire_version, phase, answers, participant_category, created_at)
  on public.pilot_assessments to authenticated;
grant insert (user_id, response_version_id, questionnaire_version, phase, answers, participant_category)
  on public.pilot_assessments to authenticated;

create policy pilot_select_own on public.pilot_assessments
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy pilot_insert_own on public.pilot_assessments
  for insert to authenticated
  with check (user_id = (select auth.uid()));

-- ------------------------------------------------- staff-only tables
--
-- research_questions, sources, evidence_items, reviews, review_versions,
-- approvals, research_jobs, search_runs and audit_events have RLS enabled,
-- no grants and no policies. They are reachable only via the service role.

-- ------------------------------------------------- anon gets nothing

-- anon holds no grants after the blanket revoke above and appears in no policy.
