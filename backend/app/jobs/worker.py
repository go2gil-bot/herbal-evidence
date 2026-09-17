"""The job consumer, running inside the backend process.

One asyncio task polls for claimable work. While a job runs, a second task keeps
its lease alive; if this process dies, the lease expires and another worker picks
the job up. That is what "an unfinished job is recoverable after a restart" means
here - no job is lost, and none is processed twice, because the claim is a single
atomic UPDATE.

Capacity: one job at a time per process. That is enough for the pilot and is
documented as a limit rather than hidden. Adding replicas is safe (SKIP LOCKED),
but throughput per replica stays one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid

from app.config import get_settings
from app.jobs import queue
from app.jobs.handlers import HANDLERS, NotConfigured
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger("herbal_evidence.worker")

IDLE_SLEEP_SECONDS = 5.0
HEARTBEAT_SECONDS = 60.0


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


async def _keep_lease(client: SupabaseClient, job_id: int, worker: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            alive = await queue.heartbeat(client, job_id, worker)
            if not alive:
                # Someone else owns it now; stop pretending we do.
                logger.warning("lost lease on job %s", job_id)
                return
        except Exception:
            logger.exception("heartbeat failed for job %s", job_id)


async def process_one(client: SupabaseClient, worker: str) -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    job = await queue.claim(client, worker)
    if not job:
        return False

    job_id = job["id"]
    logger.info("claimed job %s (%s) attempt %s", job_id, job["job_type"], job["attempts"])

    lease = asyncio.create_task(_keep_lease(client, job_id, worker))
    try:
        handler = HANDLERS.get(job["job_type"])
        if handler is None:
            await queue.fail(client, job_id, {"kind": "unknown_job_type", "job_type": job["job_type"]})
            return True

        try:
            result = await handler(client, job)
        except NotConfigured as exc:
            # A blocked integration, recorded as exactly that. Staff see it; the
            # requester keeps seeing a waiting state and never a fabricated answer.
            await queue.fail(client, job_id, {"kind": "not_configured", "detail": exc.what})
            logger.info("job %s blocked: %s", job_id, exc.what)
            return True
        except Exception as exc:
            await queue.fail(
                client, job_id, {"kind": "handler_error", "type": type(exc).__name__, "detail": str(exc)[:500]}
            )
            logger.exception("job %s failed", job_id)
            return True

        await queue.complete(client, job_id, worker)
        logger.info("job %s done: %s", job_id, result)
        return True
    finally:
        lease.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lease


async def run_forever(stop: asyncio.Event) -> None:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_secret_key):
        logger.warning("worker not started: Supabase is not configured")
        return

    client = SupabaseClient(settings)
    worker = worker_name()
    logger.info("job worker %s started", worker)

    while not stop.is_set():
        try:
            did_work = await process_one(client, worker)
        except Exception:
            # The loop itself must not die on a transient database error.
            logger.exception("worker loop error")
            did_work = False

        if not did_work:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SLEEP_SECONDS)

    logger.info("job worker %s stopped", worker)
