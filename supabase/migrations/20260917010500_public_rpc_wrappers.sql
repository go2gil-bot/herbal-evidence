-- PostgREST only exposes `public`, and the private schema stays unexposed.
-- These wrappers are the one narrow door to the privileged operations, and only
-- the service role can open it - the backend, after it has authorized the caller.

create or replace function public.approve_response_version(
  p_response_version_id bigint,
  p_expected_content_hash text,
  p_approver uuid,
  p_checked_sources boolean,
  p_checked_claim_evidence_alignment boolean,
  p_checked_limitations boolean,
  p_checked_user_wording boolean
) returns public.approvals
language sql security definer set search_path = '' as $fn$
  select private.approve_response_version(
    p_response_version_id, p_expected_content_hash, p_approver,
    p_checked_sources, p_checked_claim_evidence_alignment,
    p_checked_limitations, p_checked_user_wording
  );
$fn$;

create or replace function public.withdraw_response_version(
  p_response_version_id bigint,
  p_actor uuid,
  p_reason text
) returns void
language sql security definer set search_path = '' as $fn$
  select private.withdraw_response_version(p_response_version_id, p_actor, p_reason);
$fn$;

create or replace function public.claim_research_job(
  p_worker text,
  p_lease_seconds int default 300
) returns public.research_jobs
language sql security definer set search_path = '' as $fn$
  select private.claim_research_job(p_worker, make_interval(secs => p_lease_seconds));
$fn$;

create or replace function public.heartbeat_research_job(
  p_job_id bigint,
  p_worker text,
  p_lease_seconds int default 300
) returns boolean
language sql security definer set search_path = '' as $fn$
  select private.heartbeat_research_job(p_job_id, p_worker, make_interval(secs => p_lease_seconds));
$fn$;

create or replace function public.fail_research_job(
  p_job_id bigint,
  p_error jsonb,
  p_retry_after_seconds int default 120
) returns public.research_jobs
language sql security definer set search_path = '' as $fn$
  select private.fail_research_job(p_job_id, p_error, make_interval(secs => p_retry_after_seconds));
$fn$;

create or replace function public.complete_research_job(p_job_id bigint, p_worker text)
returns boolean
language sql security definer set search_path = '' as $fn$
  select private.complete_research_job(p_job_id, p_worker);
$fn$;

-- Default EXECUTE on a new function goes to PUBLIC. Take it back first.
revoke all on function
  public.approve_response_version(bigint, text, uuid, boolean, boolean, boolean, boolean),
  public.withdraw_response_version(bigint, uuid, text),
  public.claim_research_job(text, int),
  public.heartbeat_research_job(bigint, text, int),
  public.fail_research_job(bigint, jsonb, int),
  public.complete_research_job(bigint, text)
from public, anon, authenticated;

grant execute on function
  public.approve_response_version(bigint, text, uuid, boolean, boolean, boolean, boolean),
  public.withdraw_response_version(bigint, uuid, text),
  public.claim_research_job(text, int),
  public.heartbeat_research_job(bigint, text, int),
  public.fail_research_job(bigint, jsonb, int),
  public.complete_research_job(bigint, text)
to service_role;
