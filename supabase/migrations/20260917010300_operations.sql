-- Operations that must be atomic, expressed once in the database rather than
-- three times in application code.
--
-- All of these live in `private` and are callable only by the service role, i.e.
-- by the backend after it has authorized the caller.

-- ---------------------------------------------------------------- approval
--
-- Approval binds to ONE exact version of the content. If the draft moved while
-- the researcher was reading it, this fails loudly instead of publishing
-- something nobody reviewed.

create or replace function private.approve_response_version(
  p_response_version_id bigint,
  p_expected_content_hash text,
  p_approver uuid,
  p_checked_sources boolean,
  p_checked_claim_evidence_alignment boolean,
  p_checked_limitations boolean,
  p_checked_user_wording boolean
) returns public.approvals
language plpgsql security definer set search_path = '' as $fn$
declare
  v_row public.response_versions;
  v_approval public.approvals;
begin
  select * into v_row
  from public.response_versions
  where id = p_response_version_id
  for update;

  if not found then
    raise exception 'response version % not found', p_response_version_id
      using errcode = 'no_data_found';
  end if;

  if v_row.state <> 'draft' then
    raise exception 'response version % is %, only a draft can be approved', p_response_version_id, v_row.state
      using errcode = 'invalid_parameter_value';
  end if;

  -- The core guarantee. A concurrent edit changes the hash and stops publication.
  if v_row.content_hash is distinct from p_expected_content_hash then
    raise exception 'draft changed since it was reviewed; approval refused'
      using errcode = 'serialization_failure';
  end if;

  insert into public.approvals (
    response_version_id, approved_by, approved_content_hash,
    checked_sources, checked_claim_evidence_alignment,
    checked_limitations, checked_user_wording
  ) values (
    p_response_version_id, p_approver, p_expected_content_hash,
    p_checked_sources, p_checked_claim_evidence_alignment,
    p_checked_limitations, p_checked_user_wording
  ) returning * into v_approval;

  -- An older published version steps aside only now, inside the same transaction.
  update public.response_versions
  set state = 'superseded'
  where request_id = v_row.request_id and state = 'published';

  update public.response_versions
  set state = 'published', published_at = now()
  where id = p_response_version_id;

  update public.requests
  set status = 'published'
  where id = v_row.request_id;

  insert into public.audit_events (actor_id, action, entity_type, entity_id, metadata)
  values (p_approver, 'response.approved', 'response_version', p_response_version_id::text,
          jsonb_build_object('request_id', v_row.request_id, 'version', v_row.version));

  return v_approval;
end;
$fn$;

-- ---------------------------------------------------------------- withdrawal

create or replace function private.withdraw_response_version(
  p_response_version_id bigint,
  p_actor uuid,
  p_reason text
) returns void
language plpgsql security definer set search_path = '' as $fn$
declare
  v_request_id bigint;
begin
  if length(btrim(coalesce(p_reason, ''))) = 0 then
    raise exception 'a withdrawal requires a reason'
      using errcode = 'invalid_parameter_value';
  end if;

  update public.response_versions
  set state = 'withdrawn', withdrawn_at = now(), withdrawn_reason = p_reason
  where id = p_response_version_id and state = 'published'
  returning request_id into v_request_id;

  if v_request_id is null then
    raise exception 'response version % is not published', p_response_version_id
      using errcode = 'invalid_parameter_value';
  end if;

  -- The request stops claiming it has an answer.
  update public.requests set status = 'in_review' where id = v_request_id;

  insert into public.audit_events (actor_id, action, entity_type, entity_id, metadata)
  values (p_actor, 'response.withdrawn', 'response_version', p_response_version_id::text,
          jsonb_build_object('request_id', v_request_id));
end;
$fn$;

-- ---------------------------------------------------------------- job queue
--
-- Claiming uses FOR UPDATE SKIP LOCKED so a second replica never picks up a job
-- that is already being worked on. An expired lease is reclaimable, which is what
-- makes an unfinished job survive a backend restart.

create or replace function private.claim_research_job(
  p_worker text,
  p_lease interval default interval '5 minutes'
) returns public.research_jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  v_job public.research_jobs;
begin
  update public.research_jobs j
  set state = 'running',
      attempts = j.attempts + 1,
      locked_by = p_worker,
      lease_expires_at = now() + p_lease,
      heartbeat_at = now()
  where j.id = (
    select c.id
    from public.research_jobs c
    where (c.state = 'queued' and c.run_after <= now())
       or (c.state = 'running' and c.lease_expires_at < now())
    order by c.run_after
    limit 1
    for update skip locked
  )
  returning j.* into v_job;

  return v_job;
end;
$fn$;

create or replace function private.heartbeat_research_job(
  p_job_id bigint,
  p_worker text,
  p_lease interval default interval '5 minutes'
) returns boolean
language plpgsql security definer set search_path = '' as $fn$
declare
  v_updated int;
begin
  update public.research_jobs
  set heartbeat_at = now(), lease_expires_at = now() + p_lease
  where id = p_job_id and locked_by = p_worker and state = 'running';

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$fn$;

-- A failure is stored as a failure. It never becomes a finding.
create or replace function private.fail_research_job(
  p_job_id bigint,
  p_error jsonb,
  p_retry_after interval default interval '2 minutes'
) returns public.research_jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  v_job public.research_jobs;
begin
  select * into v_job from public.research_jobs where id = p_job_id for update;

  if not found then
    raise exception 'job % not found', p_job_id using errcode = 'no_data_found';
  end if;

  if v_job.attempts >= v_job.max_attempts then
    update public.research_jobs
    set state = 'dead', last_error = p_error, locked_by = null, lease_expires_at = null
    where id = p_job_id
    returning * into v_job;
  else
    update public.research_jobs
    set state = 'queued', last_error = p_error, run_after = now() + p_retry_after,
        locked_by = null, lease_expires_at = null
    where id = p_job_id
    returning * into v_job;
  end if;

  return v_job;
end;
$fn$;

create or replace function private.complete_research_job(p_job_id bigint, p_worker text)
returns boolean
language plpgsql security definer set search_path = '' as $fn$
declare
  v_updated int;
begin
  update public.research_jobs
  set state = 'succeeded', locked_by = null, lease_expires_at = null, last_error = null
  where id = p_job_id and locked_by = p_worker and state = 'running';

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$fn$;

-- ---------------------------------------------------------------- privileges

revoke all on all routines in schema private from public, anon, authenticated;
grant usage on schema private to service_role;
grant execute on all routines in schema private to service_role;
