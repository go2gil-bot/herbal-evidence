-- Pin search_path on the two trigger functions.
--
-- Flagged by `supabase db advisors --type security` (0011_function_search_path_mutable).
-- Neither is SECURITY DEFINER, but a mutable search_path is still a way to get a
-- function to resolve a name somewhere unexpected.

create or replace function private.touch_updated_at()
returns trigger language plpgsql set search_path = '' as $fn$
begin
  new.updated_at = now();
  return new;
end;
$fn$;

create or replace function private.stamp_clarification_answer()
returns trigger language plpgsql set search_path = '' as $fn$
begin
  if new.answer is distinct from old.answer and new.answer is not null then
    new.answered_at = now();
  end if;
  return new;
end;
$fn$;
