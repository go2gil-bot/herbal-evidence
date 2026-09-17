"""Durable queue operations.

Every one of these is a database function, not application logic, because the
guarantees they carry - one worker per job, a lease that expires, a bounded retry
budget - have to hold across processes and across restarts.
"""

from __future__ import annotations

from typing import Any

from app.services.supabase_client import SupabaseClient

LEASE_SECONDS = 300


async def claim(client: SupabaseClient, worker: str) -> dict | None:
    """Take the next claimable job, or None.

    `for update skip locked` inside the function means a second replica moves on
    to the next row instead of waiting. A job whose lease expired is claimable
    again, which is how work survives a process that died mid-flight.
    """
    result = await client.rpc(
        "claim_research_job", {"p_worker": worker, "p_lease_seconds": LEASE_SECONDS}
    )
    if isinstance(result, list):
        result = result[0] if result else None
    return result if result and result.get("id") else None


async def heartbeat(client: SupabaseClient, job_id: int, worker: str) -> bool:
    return bool(
        await client.rpc(
            "heartbeat_research_job",
            {"p_job_id": job_id, "p_worker": worker, "p_lease_seconds": LEASE_SECONDS},
        )
    )


async def complete(client: SupabaseClient, job_id: int, worker: str) -> bool:
    return bool(
        await client.rpc("complete_research_job", {"p_job_id": job_id, "p_worker": worker})
    )


async def fail(client: SupabaseClient, job_id: int, error: dict[str, Any]) -> dict:
    """Record a structured failure.

    The error is stored on the job. It never becomes a conclusion, and the
    requester keeps seeing a waiting state.
    """
    result = await client.rpc(
        "fail_research_job", {"p_job_id": job_id, "p_error": error, "p_retry_after_seconds": 120}
    )
    if isinstance(result, list):
        result = result[0] if result else {}
    return result or {}
