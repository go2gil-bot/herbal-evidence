"""Run a literature search and store what happened.

The shape of this module is set by one rule: **a failed search is not a finding
of no evidence.** So every provider call writes its own `search_runs` row saying
whether it succeeded, and the job only succeeds if at least one provider did. If
both fail, the job fails and the requester keeps waiting - nobody is told that
nothing was found.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.research import dedupe, europepmc, pubmed, query as query_builder
from app.research.http import FetchFailed, FetchRefused
from app.research.models import RetrievedSource
from app.services.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger("herbal_evidence.research.pipeline")

PROVIDERS = {
    "europepmc": europepmc.search,
    "pubmed": pubmed.search,
}


@dataclass
class SearchOutcome:
    query: str
    stored: int
    providers_succeeded: list[str]
    providers_failed: list[str]
    overlap_note: str | None


async def _plant_terms(client: SupabaseClient, request_row: dict) -> list[str]:
    scientific = None
    aliases: list[str] = []
    plant_id = request_row.get("identified_plant_id")

    if plant_id:
        plants = await client.select(
            "plants", columns="scientific_name", filters={"id": f"eq.{plant_id}"}, limit=1
        )
        if plants:
            scientific = plants[0]["scientific_name"]
        alias_rows = await client.select(
            "plant_aliases", columns="alias", filters={"plant_id": f"eq.{plant_id}"}
        )
        aliases = [row["alias"] for row in alias_rows]

    return query_builder.terms_for_plant(scientific, aliases, request_row["herb_input"])


async def _record_run(
    client: SupabaseClient, job_id: int, provider: str, text: str, *,
    status: str, result_count: int | None = None, error: dict | None = None,
) -> None:
    await client.insert(
        "search_runs",
        {
            "research_job_id": job_id,
            "provider": provider,
            "query": text,
            "status": status,
            "result_count": result_count,
            "error": error,
        },
    )


async def _store(client: SupabaseClient, sources: list[RetrievedSource]) -> int:
    stored = 0
    for source in sources:
        row = source.to_row()
        existing = await client.select(
            "sources",
            columns="id",
            filters={"id_kind": f"eq.{row['id_kind']}", "external_id": f"eq.{row['external_id']}"},
            limit=1,
        )
        if existing:
            continue
        try:
            await client.insert("sources", row, columns="id")
            stored += 1
        except SupabaseError:
            # A concurrent job inserted the same record; the unique constraint
            # did its job and there is nothing to fix.
            logger.info("source already present: %s %s", row["id_kind"], row["external_id"])
    return stored


async def run_literature_search(
    client: SupabaseClient, job: dict, request_row: dict, *, limit: int = 25
) -> SearchOutcome:
    terms = await _plant_terms(client, request_row)
    if not terms:
        raise ValueError(
            "no searchable name for this herb - the request needs human identification first"
        )

    text = query_builder.build(herb_terms=terms)
    job_id = job["id"]

    collected: list[RetrievedSource] = []
    succeeded: list[str] = []
    failed: list[str] = []

    for provider, search in PROVIDERS.items():
        try:
            results = await search(text, limit=limit)
        except (FetchFailed, FetchRefused, ValueError) as exc:
            # Stored as a failure with its reason. Zero results and a failed
            # request are different rows, and the constraint enforces it.
            await _record_run(
                client, job_id, provider, text,
                status="failed",
                error={"kind": type(exc).__name__, "detail": str(exc)[:400]},
            )
            failed.append(provider)
            logger.warning("%s search failed: %s", provider, exc)
            continue

        await _record_run(client, job_id, provider, text, status="succeeded", result_count=len(results))
        succeeded.append(provider)
        collected.extend(results)

    if not succeeded:
        # Every provider failed. This is a failure, full stop - the request is
        # not told that no evidence exists.
        raise FetchFailed(f"every provider failed: {', '.join(failed)}")

    merged = dedupe.deduplicate(collected)
    stored = await _store(client, merged)

    return SearchOutcome(
        query=text,
        stored=stored,
        providers_succeeded=succeeded,
        providers_failed=failed,
        overlap_note=dedupe.overlap_note(merged),
    )
