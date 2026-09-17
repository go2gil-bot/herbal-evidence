-- Use SQLSTATEs PostgREST maps to HTTP, instead of ones it retries.
--
-- The stale-draft refusal originally raised `serialization_failure` (40001).
-- PostgREST automatically retries that class, so a refusal that is supposed to be
-- final turned into a retry loop and the request hung instead of returning 409.
-- PostgREST maps a `PTxyz` SQLSTATE to HTTP status xyz, which is what we want:
-- these are deliberate, final answers.

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
      using errcode = 'PT404';
  end if;

  if v_row.state <> 'draft' then
    raise exception 'response version % is %, only a draft can be approved',
      p_response_version_id, v_row.state
      using errcode = 'PT409';
  end if;

  -- The core guarantee. A concurrent edit changes the hash and stops publication.
  if v_row.content_hash is distinct from p_expected_content_hash then
    raise exception 'draft changed since it was reviewed; approval refused'
      using errcode = 'PT409';
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
    raise exception 'a withdrawal requires a reason' using errcode = 'PT400';
  end if;

  update public.response_versions
  set state = 'withdrawn', withdrawn_at = now(), withdrawn_reason = p_reason
  where id = p_response_version_id and state = 'published'
  returning request_id into v_request_id;

  if v_request_id is null then
    raise exception 'response version % is not published', p_response_version_id
      using errcode = 'PT409';
  end if;

  update public.requests set status = 'in_review' where id = v_request_id;

  insert into public.audit_events (actor_id, action, entity_type, entity_id, metadata)
  values (p_actor, 'response.withdrawn', 'response_version', p_response_version_id::text,
          jsonb_build_object('request_id', v_request_id));
end;
$fn$;

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
    raise exception 'job % not found', p_job_id using errcode = 'PT404';
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
