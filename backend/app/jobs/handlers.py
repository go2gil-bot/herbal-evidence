"""What each job type actually does.

Only `identify_plant` is implemented, and it does real work: it re-runs name
resolution against the catalogue. The three research job types depend on an AI
provider and on literature adapters that do not exist yet, so they raise
`NotConfigured`. That becomes a stored failure the staff can see.

They deliberately do NOT produce placeholder output. A mock draft that looks like
a finding is worse than no draft, because somebody eventually reads it.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from app.config import get_settings
from app.services import plant_identification
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger("herbal_evidence.jobs")


class NotConfigured(Exception):
    """A required provider is missing. Blocked, not failed-and-forget."""

    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


async def identify_plant(client: SupabaseClient, job: dict) -> dict:
    request_id = job["request_id"]
    rows = await client.select(
        "requests", columns="id,herb_input,identification_state", filters={"id": f"eq.{request_id}"}, limit=1
    )
    if not rows:
        raise RuntimeError(f"request {request_id} disappeared")

    result = await plant_identification.identify(client, rows[0]["herb_input"])

    values: dict = {"identification_state": result.outcome if result.outcome != "not_found" else "pending"}
    if result.outcome == "resolved":
        values["identified_plant_id"] = result.candidates[0].plant_id

    await client.update(
        "requests", filters={"id": f"eq.{request_id}"}, values=values, columns="id"
    )
    return {"outcome": result.outcome, "candidates": len(result.candidates)}


async def literature_search(client: SupabaseClient, job: dict) -> dict:
    settings = get_settings()
    if not settings.ncbi_api_key and settings.ai_provider == "none":
        raise NotConfigured("literature adapters are not implemented yet (phase 6)")
    raise NotConfigured("literature adapters are not implemented yet (phase 6)")


async def extract(client: SupabaseClient, job: dict) -> dict:
    raise NotConfigured("extraction requires an AI provider (phase 6)")


async def draft(client: SupabaseClient, job: dict) -> dict:
    settings = get_settings()
    if settings.ai_provider == "none" or not settings.ai_api_key:
        raise NotConfigured("no AI provider configured")
    raise NotConfigured("draft generation is not implemented yet (phase 6)")


HANDLERS: dict[str, Callable[[SupabaseClient, dict], Awaitable[dict]]] = {
    "identify_plant": identify_plant,
    "literature_search": literature_search,
    "extract": extract,
    "draft": draft,
}
