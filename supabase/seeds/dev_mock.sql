-- MOCK DATA - DEVELOPMENT ONLY. NEVER RUN THIS AGAINST PRODUCTION.
--
-- Everything inserted here is invented. There is no real patient data, no real
-- citation and no real research finding anywhere in this file. Every text field a
-- person could read is prefixed with "[נתוני דמה]" so that a mock row showing up
-- in a screenshot is instantly recognisable.
--
-- The guard below refuses to run unless the caller says out loud that this is a
-- development database:
--
--   psql "$DEV_DB_URL" -v ON_ERROR_STOP=1 \
--        -c "set app.allow_mock_seed = 'yes'" -f supabase/seeds/dev_mock.sql
--
-- Requests need real auth users to own them, so this file only seeds the research
-- side: questions, sources, evidence and a review. Owned rows are created by
-- supabase/tests/rls_isolation.py, which cleans up after itself.

do $guard$
begin
  if coalesce(current_setting('app.allow_mock_seed', true), '') <> 'yes' then
    raise exception
      'refusing to seed mock data: set app.allow_mock_seed to ''yes'' first (never on Production)';
  end if;
end;
$guard$;

insert into public.research_questions (plant_id, normalized_question, preparation, population, treatment_context)
select p.id,
       '[נתוני דמה] האם תמצית כורכום משפרת תיאבון במבוגרים עם מחלה כרונית?',
       '[נתוני דמה] תמצית סטנדרטית',
       '[נתוני דמה] מבוגרים',
       '[נתוני דמה] לא צוין'
from public.plants p
where p.scientific_name = 'Curcuma longa'
on conflict do nothing;

insert into public.sources (
  id_kind, external_id, title, journal, publication_year,
  evidence_type, study_design, is_oncology, access_level, file_provenance
) values
  ('manual', 'MOCK-0001', '[MOCK DATA - not a real citation] Placeholder controlled trial',
   '[MOCK] Journal', 2024, 'human', 'rct', true, 'full_text', 'mock seed'),
  ('manual', 'MOCK-0002', '[MOCK DATA - not a real citation] Placeholder abstract-only record',
   '[MOCK] Journal', 2022, 'human', 'observational', false, 'abstract_only', 'mock seed'),
  ('manual', 'MOCK-0003', '[MOCK DATA - not a real citation] Placeholder rodent study',
   '[MOCK] Journal', 2021, 'animal', 'preclinical', false, 'abstract_only', 'mock seed')
on conflict (id_kind, external_id) do nothing;

-- One evidence item per source, each with a support location, because a claim
-- without one cannot be stored at all (see the check constraint).
insert into public.evidence_items (
  source_id, research_question_id, population, sample_size, intervention,
  comparator, outcome, measurement_method, result, uncertainty, safety, limitations,
  claim, support_kind, support_location
)
select s.id, rq.id,
       '[נתוני דמה] מבוגרים', 40, '[נתוני דמה] תמצית', '[נתוני דמה] פלצבו',
       'appetite', '[נתוני דמה] VAS', '[נתוני דמה] ללא הבדל מובהק',
       '[נתוני דמה] מדגם קטן', '[נתוני דמה] לא דווחו אירועים חריגים',
       '[נתוני דמה] מדגם קטן, משך קצר',
       '[נתוני דמה] לא נמצא הבדל מובהק בתיאבון',
       case when s.access_level = 'full_text' then 'full_text_location' else 'abstract_passage' end,
       case when s.access_level = 'full_text' then '[MOCK] p. 4, Results' else '[MOCK] abstract, sentence 3' end
from public.sources s
cross join lateral (
  select id from public.research_questions
  where normalized_question like '[נתוני דמה]%' limit 1
) rq
where s.external_id like 'MOCK-%'
on conflict do nothing;

-- A reusable review. Note what is NOT here: no owner, no request, no personal detail.
insert into public.reviews (research_question_id)
select id from public.research_questions where normalized_question like '[נתוני דמה]%' limit 1
on conflict do nothing;

insert into public.review_versions (review_id, version, body, literature_search_date, content_hash)
select r.id, 1,
       jsonb_build_object(
         'mock', true,
         'conclusion', '[נתוני דמה] אין מספיק ראיות מבני אדם כדי להעריך תועלת לשיפור תיאבון',
         'certainty', '[נתוני דמה] נמוכה',
         'certainty_explanation', '[נתוני דמה] מעט מחקרים, מדגמים קטנים, מדידה לא אחידה'
       ),
       current_date, 'mock-review-v1'
from public.reviews r
on conflict (review_id, version) do nothing;

do $done$
begin
  raise notice 'MOCK seed applied. Every row is labelled [נתוני דמה] / [MOCK].';
end;
$done$;
