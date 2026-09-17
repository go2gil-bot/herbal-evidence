"""What each job type actually does.

`identify_plant` and `literature_search` are fully implemented and need no AI.
`extract` and `draft` need a provider; without one they raise `NotConfigured`,
which the worker stores as a structured failure.

None of them ever produces placeholder output. A mock draft that reads like a
finding is worse than no draft, because somebody eventually reads it.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from app.ai import provider as ai_provider
from app.ai.provider import DraftRequest
from app.config import get_settings
from app.domain.content_hash import content_hash
from app.research import pipeline
from app.services import plant_identification
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger("herbal_evidence.jobs")


class NotConfigured(Exception):
    """A required provider is missing. Blocked, not failed-and-forgotten."""

    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


async def _request_row(client: SupabaseClient, request_id: int) -> dict:
    rows = await client.select(
        "requests",
        columns="id,herb_input,preparation_input,cancer_type_input,treatment_input,"
        "question_input,identified_plant_id,identification_state,research_question_id,status",
        filters={"id": f"eq.{request_id}"},
        limit=1,
    )
    if not rows:
        raise RuntimeError(f"request {request_id} disappeared")
    return rows[0]


async def identify_plant(client: SupabaseClient, job: dict) -> dict:
    request_row = await _request_row(client, job["request_id"])
    result = await plant_identification.identify(client, request_row["herb_input"])

    values: dict = {
        "identification_state": result.outcome if result.outcome != "not_found" else "pending"
    }
    if result.outcome == "resolved":
        values["identified_plant_id"] = result.candidates[0].plant_id

    await client.update("requests", filters={"id": f"eq.{job['request_id']}"}, values=values, columns="id")
    return {"outcome": result.outcome, "candidates": len(result.candidates)}


async def literature_search(client: SupabaseClient, job: dict) -> dict:
    request_row = await _request_row(client, job["request_id"])
    outcome = await pipeline.run_literature_search(client, job, request_row)

    if request_row["status"] in {"queued", "submitted"}:
        await client.update(
            "requests", filters={"id": f"eq.{job['request_id']}"},
            values={"status": "researching"}, columns="id"
        )

    return {
        "query": outcome.query,
        "stored": outcome.stored,
        "succeeded": outcome.providers_succeeded,
        "failed": outcome.providers_failed,
        "overlap_note": outcome.overlap_note,
    }


async def extract(client: SupabaseClient, job: dict) -> dict:
    raise NotConfigured("structured extraction is not implemented yet (needs an AI provider)")


async def draft(client: SupabaseClient, job: dict) -> dict:
    try:
        return await _draft(client, job)
    except ai_provider.NotConfigured as exc:
        # Missing configuration is "blocked", not "crashed", wherever it is
        # discovered - get_provider() catches an absent key, generate_draft()
        # catches an absent model. Both must reach the worker as the same kind
        # of failure or the staff screen misreports why nothing happened.
        raise NotConfigured(exc.what) from exc


async def _draft(client: SupabaseClient, job: dict) -> dict:
    provider = ai_provider.get_provider()
    request_row = await _request_row(client, job["request_id"])

    sources = await client.select(
        "sources",
        columns="id,title,journal,publication_year,id_kind,external_id,evidence_type,"
        "study_design,is_oncology,access_level",
        order="id.desc",
        limit=25,
    )
    if not sources:
        raise NotConfigured("no sources retrieved yet - run a literature search first")

    scientific_name = None
    if request_row.get("identified_plant_id"):
        plants = await client.select(
            "plants", columns="scientific_name",
            filters={"id": f"eq.{request_row['identified_plant_id']}"}, limit=1
        )
        if plants:
            scientific_name = plants[0]["scientific_name"]

    # Only research material crosses the boundary: no owner, no email, no
    # request id, no account identifier of any kind.
    draft_request = DraftRequest(
        question=request_row.get("question_input") or "האם הצמח משפר תיאבון?",
        herb_scientific_name=scientific_name,
        preparation=request_row.get("preparation_input"),
        population=request_row.get("cancer_type_input"),
        treatment_context=request_row.get("treatment_input"),
        sources=[{**source, "id": str(source["id"])} for source in sources],
    )

    result = await provider.generate_draft(draft_request)

    existing = await client.select(
        "response_versions", columns="version",
        filters={"request_id": f"eq.{job['request_id']}"}, order="version.desc", limit=1,
    )
    next_version = (existing[0]["version"] + 1) if existing else 1

    created = await client.insert(
        "response_versions",
        {
            "request_id": job["request_id"],
            "version": next_version,
            "body": result.body,
            "source_ids": [source["id"] for source in sources],
            "content_hash": content_hash(result.body),
            "state": "draft",
            "ai_provider": result.provider,
            "ai_model": result.model,
            "prompt_version": result.prompt_version,
            "generated_at": "now()",
        },
        columns="id,version",
    )

    await client.update(
        "requests", filters={"id": f"eq.{job['request_id']}"},
        values={"status": "draft_ready"}, columns="id"
    )
    return {"response_version_id": created["id"], "version": created["version"], "model": result.model}


HANDLERS: dict[str, Callable[[SupabaseClient, dict], Awaitable[dict]]] = {
    "identify_plant": identify_plant,
    "literature_search": literature_search,
    "extract": extract,
    "draft": draft,
}
