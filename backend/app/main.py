"""Herbal Evidence API.

Phase 4: the requester-facing journey is live under /api/v1. The research
workflow, the staff workspace and the job queue arrive in later phases.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.v1.router import router as v1_router
from app.api.v1.pilot import router as pilot_router, staff_router as pilot_staff_router
from app.api.v1.staff import router as staff_router
from app.config import get_settings
from app.jobs import worker as job_worker

settings = get_settings()

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("herbal_evidence")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the job consumer for as long as the service is up.

    The queue is durable in Postgres, so a shutdown here loses nothing: whatever
    was in flight has a lease that expires and is picked up again.
    """
    stop = asyncio.Event()
    task = asyncio.create_task(job_worker.run_forever(stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
    title="Herbal Evidence API",
    version="0.1.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
else:
    logger.warning(
        "No CORS origins configured; browser calls from the frontend will be rejected."
    )


class Health(BaseModel):
    status: str
    app_env: str
    version: str


class Ready(BaseModel):
    ready: bool
    checks: dict[str, str]


app.include_router(v1_router)
app.include_router(staff_router)
app.include_router(pilot_router)
app.include_router(pilot_staff_router)


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Liveness. Says nothing about dependencies and exposes no secrets."""
    return Health(status="ok", app_env=settings.app_env, version=app.version)


@app.get("/ready", response_model=Ready, tags=["ops"])
def ready() -> Ready:
    """Readiness. Reports whether configuration is present, never its values."""
    checks = {
        "supabase_url": "set" if settings.supabase_url else "missing",
        "supabase_secret_key": "set" if settings.supabase_secret_key else "missing",
        "cors_origins": "set" if settings.allowed_origins else "missing",
        "ai_provider": settings.ai_provider,
        # Presence only. A key is never echoed, not even partially.
        "ai_api_key": "set" if settings.ai_api_key else "missing",
        "ai_model": settings.ai_model or "missing",
    }
    # Phase 1 has no database yet, so readiness is configuration-only.
    return Ready(ready=True, checks=checks)
