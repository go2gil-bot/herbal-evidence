-- Bound how many requests one person can submit.
--
-- This lives in the database rather than in FastAPI because `authenticated`
-- holds a direct insert grant on public.requests (see 20260917010200_rls.sql),
-- so a limit in the API would be bypassed by posting straight to PostgREST.
-- It is also the only place that stays correct with more than one backend
-- replica - there is no shared cache between them.
--
-- What an unbounded loop actually costs here: rows, and a researcher queue
-- flooded past the point of being usable. It does NOT reach the AI provider -
-- research jobs are enqueued by staff action, never by submitting a request.
--
-- The two windows are a starting point, not a product decision. They are
-- deliberately far above anything an honest person does - someone asking about
-- their own treatment submits a handful, not dozens - and low enough that a
-- script is stopped in seconds. Change them here; nothing else reads them.

create or replace function private.enforce_request_rate_limit()
returns trigger language plpgsql
security definer set search_path = '' as $fn$
declare
  -- Per owner, per rolling window.
  c_per_hour constant int := 5;
  c_per_day  constant int := 20;
  v_recent   int;
begin
  -- The mock seed inserts a batch on purpose, under the same guard it already
  -- uses to refuse to run anywhere but development.
  if coalesce(current_setting('app.allow_mock_seed', true), '') = 'yes' then
    return new;
  end if;

  -- Serialize this owner's inserts so two concurrent submissions cannot both
  -- read a count below the limit and both pass. Per owner, so it costs nothing
  -- to anybody else, and transaction-scoped so it is released either way.
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text, 0));

  select count(*) into v_recent
  from public.requests
  where owner_id = new.owner_id
    and created_at > now() - interval '1 hour';

  if v_recent >= c_per_hour then
    raise exception 'rate limit: % requests in the last hour', v_recent
      using errcode = 'PT429';
  end if;

  select count(*) into v_recent
  from public.requests
  where owner_id = new.owner_id
    and created_at > now() - interval '24 hours';

  if v_recent >= c_per_day then
    raise exception 'rate limit: % requests in the last day', v_recent
      using errcode = 'PT429';
  end if;

  return new;
end;
$fn$;

create trigger requests_rate_limit
  before insert on public.requests
  for each row execute function private.enforce_request_rate_limit();

-- The count filters on owner and time. `requests_owner_id_idx` already covers
-- the owner; a composite is not worth it while one person's rows number in the
-- tens, and the limits above are what keep that true.
