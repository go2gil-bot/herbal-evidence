"""/api/v1/staff - the researcher and administrator surface.

Two rules run through every handler:

  * Scope is checked on the way in. A researcher works on what is assigned to
    them; an admin manages the queue. `ensure_in_scope` is the check, and it is
    called before anything is read or written.
  * Nothing here can publish by setting a field. Publication happens only inside
    the approval transaction, which binds to one exact content hash.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth.roles import CurrentAdmin, CurrentStaff, StaffMember, ensure_in_scope, scope_filter
from app.domain.content_hash import content_hash
from app.domain.workflow import can_transition, requires_admin
from app.services.supabase_client import SupabaseClient, SupabaseError, get_supabase

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])

Client = Annotated[SupabaseClient, Depends(get_supabase)]

STAFF_REQUEST_COLUMNS = (
    "id,owner_id,herb_input,preparation_input,cancer_type_input,treatment_input,"
    "question_input,preparation_unknown,cancer_type_unknown,treatment_unknown,"
    "identified_plant_id,identification_state,research_question_id,status,"
    "assigned_researcher_id,closed_reason,created_at,updated_at,plants(scientific_name)"
)

NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "לא נמצא"}
)


def conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message})


async def _load_request(client: SupabaseClient, request_id: int, staff: StaffMember) -> dict:
    rows = await client.select(
        "requests", columns=STAFF_REQUEST_COLUMNS, filters={"id": f"eq.{request_id}"}, limit=1
    )
    if not rows:
        raise NOT_FOUND
    ensure_in_scope(staff, rows[0])
    return rows[0]


async def _audit(client: SupabaseClient, actor: str, action: str, entity: str, entity_id: Any, **meta):
    # Identifiers and outcomes only - never the question, the treatment or the draft.
    await client.insert(
        "audit_events",
        {
            "actor_id": actor,
            "action": action,
            "entity_type": entity,
            "entity_id": str(entity_id),
            "metadata": meta or None,
        },
    )


# ----------------------------------------------------------------- queue


class QueueItem(BaseModel):
    id: int
    herb_input: str
    preparation_input: str | None
    status: str
    identification_state: str
    assigned_researcher_id: str | None
    created_at: str
    age_days: int


@router.get("/queue")
async def queue(
    staff: CurrentStaff,
    client: Client,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    assigned: Annotated[Literal["me", "unassigned", "any"], Query()] = "any",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    filters = scope_filter(staff)  # authorization, not convenience
    if status_filter:
        filters["status"] = f"eq.{status_filter}"
    if search:
        # PostgREST pattern syntax; `*` is the wildcard.
        filters["herb_input"] = f"ilike.*{search}*"
    if assigned == "me":
        filters["assigned_researcher_id"] = f"eq.{staff.user_id}"
    elif assigned == "unassigned":
        if staff.is_admin:
            filters["assigned_researcher_id"] = "is.null"
        else:
            # A researcher's scope is already their own assignments; asking for
            # unassigned work would be empty by definition.
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

    rows = await client.select(
        "requests",
        columns="id,herb_input,preparation_input,status,identification_state,assigned_researcher_id,created_at",
        filters=filters,
        order="created_at.asc",
        limit=limit,
        offset=offset,
    )

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        items.append({**row, "age_days": (now - created).days})

    return {"items": items, "total": len(items), "limit": limit, "offset": offset}


@router.get("/requests/{request_id}")
async def request_detail(staff: CurrentStaff, client: Client, request_id: int) -> dict:
    row = await _load_request(client, request_id, staff)

    clarifications = await client.select(
        "request_clarifications",
        columns="id,question,answer,asked_at,answered_at,asked_by",
        filters={"request_id": f"eq.{request_id}"},
        order="asked_at.asc",
    )
    versions = await client.select(
        "response_versions",
        columns="id,version,state,content_hash,published_at,withdrawn_reason,created_at,ai_provider,ai_model,prompt_version",
        filters={"request_id": f"eq.{request_id}"},
        order="version.desc",
    )
    jobs = await client.select(
        "research_jobs",
        columns="id,job_type,state,attempts,max_attempts,run_after,last_error,updated_at",
        filters={"request_id": f"eq.{request_id}"},
        order="id.desc",
    )

    related: list[dict] = []
    if row.get("research_question_id"):
        related = await client.select(
            "review_versions",
            columns="id,review_id,version,literature_search_date,approved_at,reviews(research_question_id)",
            filters={"reviews.research_question_id": f"eq.{row['research_question_id']}"},
            limit=10,
        )

    return {
        "request": row,
        "clarifications": clarifications,
        "versions": versions,
        "jobs": jobs,
        "related_reviews": related,
    }


class AssignBody(BaseModel):
    researcher_id: str | None


@router.post("/requests/{request_id}/assign")
async def assign(admin: CurrentAdmin, client: Client, request_id: int, payload: AssignBody) -> dict:
    rows = await client.select("requests", columns="id", filters={"id": f"eq.{request_id}"}, limit=1)
    if not rows:
        raise NOT_FOUND

    if payload.researcher_id:
        roles = await client.select(
            "user_roles",
            columns="role",
            filters={"user_id": f"eq.{payload.researcher_id}", "role": "eq.researcher"},
        )
        if not roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "not_a_researcher", "message": "המשתמש אינו חוקר"},
            )

    updated = await client.update(
        "requests",
        filters={"id": f"eq.{request_id}"},
        values={"assigned_researcher_id": payload.researcher_id},
        columns="id,assigned_researcher_id,status",
    )
    await _audit(client, admin.user_id, "request.assigned", "request", request_id)
    return updated[0]


class StatusBody(BaseModel):
    status: str
    closed_reason: str | None = None


@router.post("/requests/{request_id}/status")
async def set_status(
    staff: CurrentStaff, client: Client, request_id: int, payload: StatusBody
) -> dict:
    row = await _load_request(client, request_id, staff)
    current = row["status"]

    if payload.status == "published":
        raise conflict("publish_requires_approval", "פרסום מתבצע רק דרך אישור גרסה")

    if not can_transition(current, payload.status):
        raise conflict("invalid_transition", f"לא ניתן לעבור מ-{current} ל-{payload.status}")

    if requires_admin(current, payload.status) and not staff.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "המעבר הזה שמור למנהל"},
        )

    values: dict[str, Any] = {"status": payload.status}
    if payload.status == "closed_out_of_scope":
        if not (payload.closed_reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "reason_required", "message": "סגירה מחייבת הסבר למשתמש"},
            )
        values["closed_reason"] = payload.closed_reason.strip()

    updated = await client.update(
        "requests", filters={"id": f"eq.{request_id}"}, values=values, columns="id,status"
    )
    await _audit(client, staff.user_id, "request.status_changed", "request", request_id,
                 **{"from": current, "to": payload.status})
    return updated[0]


class ClarificationBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.post("/requests/{request_id}/clarifications", status_code=status.HTTP_201_CREATED)
async def ask_clarification(
    staff: CurrentStaff, client: Client, request_id: int, payload: ClarificationBody
) -> dict:
    row = await _load_request(client, request_id, staff)
    created = await client.insert(
        "request_clarifications",
        {"request_id": request_id, "asked_by": staff.user_id, "question": payload.question.strip()},
        columns="id,question,answer,asked_at,answered_at",
    )
    if can_transition(row["status"], "needs_clarification"):
        await client.update(
            "requests", filters={"id": f"eq.{request_id}"},
            values={"status": "needs_clarification"}, columns="id"
        )
    await _audit(client, staff.user_id, "clarification.asked", "request", request_id)
    return created


# ----------------------------------------------------------------- drafts


class DraftBody(BaseModel):
    body: dict
    review_version_id: int | None = None
    source_ids: list[int] = Field(default_factory=list)


@router.post("/requests/{request_id}/drafts", status_code=status.HTTP_201_CREATED)
async def create_draft(
    staff: CurrentStaff, client: Client, request_id: int, payload: DraftBody
) -> dict:
    await _load_request(client, request_id, staff)

    existing = await client.select(
        "response_versions", columns="version", filters={"request_id": f"eq.{request_id}"},
        order="version.desc", limit=1,
    )
    next_version = (existing[0]["version"] + 1) if existing else 1

    created = await client.insert(
        "response_versions",
        {
            "request_id": request_id,
            "version": next_version,
            "body": payload.body,
            "review_version_id": payload.review_version_id,
            "source_ids": payload.source_ids,
            "content_hash": content_hash(payload.body),
            "state": "draft",
        },
        columns="id,request_id,version,state,content_hash,created_at",
    )
    await _audit(client, staff.user_id, "draft.created", "response_version", created["id"],
                 request_id=request_id, version=next_version)
    return created


@router.get("/drafts/{version_id}")
async def get_draft(staff: CurrentStaff, client: Client, version_id: int) -> dict:
    rows = await client.select(
        "response_versions",
        columns="id,request_id,version,state,body,source_ids,review_version_id,content_hash,ai_provider,ai_model,prompt_version,generated_at",
        filters={"id": f"eq.{version_id}"},
        limit=1,
    )
    if not rows:
        raise NOT_FOUND
    await _load_request(client, rows[0]["request_id"], staff)  # scope check
    return rows[0]


@router.patch("/drafts/{version_id}")
async def save_draft(
    staff: CurrentStaff, client: Client, version_id: int, payload: DraftBody
) -> dict:
    rows = await client.select(
        "response_versions", columns="id,request_id,state", filters={"id": f"eq.{version_id}"}, limit=1
    )
    if not rows:
        raise NOT_FOUND
    await _load_request(client, rows[0]["request_id"], staff)

    if rows[0]["state"] != "draft":
        raise conflict("not_a_draft", "רק טיוטה ניתנת לעריכה")

    updated = await client.update(
        "response_versions",
        filters={"id": f"eq.{version_id}", "state": "eq.draft"},
        values={
            "body": payload.body,
            "content_hash": content_hash(payload.body),
            "review_version_id": payload.review_version_id,
            "source_ids": payload.source_ids,
        },
        columns="id,version,state,content_hash",
    )
    if not updated:
        raise conflict("not_a_draft", "הגרסה כבר אינה טיוטה")
    return updated[0]


class ApprovalBody(BaseModel):
    """Every check is explicit. The database refuses the row otherwise."""

    expected_content_hash: str
    checked_sources: bool
    checked_claim_evidence_alignment: bool
    checked_limitations: bool
    checked_user_wording: bool


@router.post("/drafts/{version_id}/approve")
async def approve(
    staff: CurrentStaff, client: Client, version_id: int, payload: ApprovalBody
) -> dict:
    rows = await client.select(
        "response_versions", columns="id,request_id,version", filters={"id": f"eq.{version_id}"}, limit=1
    )
    if not rows:
        raise NOT_FOUND
    await _load_request(client, rows[0]["request_id"], staff)

    if not all(
        [
            payload.checked_sources,
            payload.checked_claim_evidence_alignment,
            payload.checked_limitations,
            payload.checked_user_wording,
        ]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "checks_incomplete", "message": "יש לאשר את כל ארבע הבדיקות"},
        )

    try:
        result = await client.rpc(
            "approve_response_version",
            {
                "p_response_version_id": version_id,
                "p_expected_content_hash": payload.expected_content_hash,
                "p_approver": staff.user_id,
                "p_checked_sources": payload.checked_sources,
                "p_checked_claim_evidence_alignment": payload.checked_claim_evidence_alignment,
                "p_checked_limitations": payload.checked_limitations,
                "p_checked_user_wording": payload.checked_user_wording,
            },
        )
    except SupabaseError as exc:
        if exc.status_code == 409:
            # The draft moved while it was being reviewed. Not retryable here:
            # somebody has to read the new text.
            raise conflict("draft_changed", "הטיוטה השתנתה מאז הבדיקה. נדרשת בדיקה נוספת") from exc
        raise
    return {"approved": True, "approval": result}


class WithdrawBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/responses/{version_id}/withdraw")
async def withdraw(
    staff: CurrentStaff, client: Client, version_id: int, payload: WithdrawBody
) -> dict:
    rows = await client.select(
        "response_versions", columns="id,request_id", filters={"id": f"eq.{version_id}"}, limit=1
    )
    if not rows:
        raise NOT_FOUND
    await _load_request(client, rows[0]["request_id"], staff)

    try:
        await client.rpc(
            "withdraw_response_version",
            {"p_response_version_id": version_id, "p_actor": staff.user_id, "p_reason": payload.reason},
        )
    except SupabaseError as exc:
        if exc.status_code == 409:
            raise conflict("not_published", "הגרסה אינה מפורסמת") from exc
        raise
    return {"withdrawn": True}


# ----------------------------------------------------------------- sources


class SourceBody(BaseModel):
    id_kind: Literal["pmid", "doi", "pmcid", "url", "manual"]
    external_id: str
    title: str
    journal: str | None = None
    publication_year: int | None = None
    url: str | None = None
    evidence_type: Literal["human", "animal", "in_vitro", "review", "other"]
    study_design: str | None = None
    is_oncology: bool | None = None
    access_level: Literal["full_text", "abstract_only", "not_accessed"]
    file_provenance: str | None = None


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(staff: CurrentStaff, client: Client, payload: SourceBody) -> dict:
    try:
        created = await client.insert("sources", payload.model_dump(), columns="*")
    except SupabaseError as exc:
        if exc.status_code == 409:
            raise conflict("duplicate_source", "המקור כבר קיים") from exc
        raise
    await _audit(client, staff.user_id, "source.added", "source", created["id"])
    return created


@router.get("/sources")
async def list_sources(
    staff: CurrentStaff,
    client: Client,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    filters = {"title": f"ilike.*{search}*"} if search else {}
    rows = await client.select("sources", columns="*", filters=filters, order="id.desc", limit=limit)
    return {"items": rows}


class EvidenceBody(BaseModel):
    source_id: int
    research_question_id: int | None = None
    population: str | None = None
    sample_size: int | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    measurement_method: str | None = None
    result: str | None = None
    uncertainty: str | None = None
    safety: str | None = None
    limitations: str | None = None
    claim: str | None = None
    support_kind: Literal["full_text_location", "abstract_passage"] | None = None
    support_location: str | None = None


@router.post("/evidence", status_code=status.HTTP_201_CREATED)
async def add_evidence(staff: CurrentStaff, client: Client, payload: EvidenceBody) -> dict:
    try:
        created = await client.insert("evidence_items", payload.model_dump(), columns="*")
    except SupabaseError as exc:
        # The database refuses a claim with no supporting location; surface that
        # as an explanation rather than a generic failure.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "claim_needs_support",
                "message": "טענה מחייבת מקור ומיקום תומך (עמוד/סעיף או קטע מזוהה בתקציר)",
            },
        ) from exc
    return created


# ----------------------------------------------------------------- reviews


@router.get("/reviews")
async def review_repository(
    staff: CurrentStaff,
    client: Client,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    rows = await client.select(
        "review_versions",
        columns="id,review_id,version,literature_search_date,approved_by,approved_at,source_ids,created_at,"
        "reviews(research_question_id,research_questions(normalized_question,preparation,population))",
        order="created_at.desc",
        limit=limit,
    )
    return {"items": rows}


# ----------------------------------------------------------------- jobs


class JobBody(BaseModel):
    job_type: Literal["identify_plant", "literature_search", "extract", "draft"]


@router.post("/requests/{request_id}/jobs", status_code=status.HTTP_201_CREATED)
async def enqueue_job(
    staff: CurrentStaff, client: Client, request_id: int, payload: JobBody
) -> dict:
    row = await _load_request(client, request_id, staff)

    # Idempotency: the same work for the same request in the same state is one
    # job, even if the button is pressed twice.
    key = f"{request_id}:{payload.job_type}:{row['updated_at']}"
    try:
        created = await client.insert(
            "research_jobs",
            {"request_id": request_id, "job_type": payload.job_type, "idempotency_key": key},
            columns="id,job_type,state,run_after",
        )
    except SupabaseError as exc:
        if exc.status_code == 409:
            raise conflict("already_queued", "העבודה כבר בתור") from exc
        raise

    if can_transition(row["status"], "queued"):
        await client.update(
            "requests", filters={"id": f"eq.{request_id}"}, values={"status": "queued"}, columns="id"
        )
    await _audit(client, staff.user_id, "job.enqueued", "research_job", created["id"],
                 request_id=request_id, job_type=payload.job_type)
    return created


@router.get("/jobs")
async def list_jobs(
    staff: CurrentStaff,
    client: Client,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    filters = {"state": f"eq.{state}"} if state else {}
    rows = await client.select(
        "research_jobs",
        columns="id,request_id,job_type,state,attempts,max_attempts,run_after,locked_by,"
        "lease_expires_at,heartbeat_at,last_error,created_at,updated_at",
        filters=filters,
        order="updated_at.desc",
        limit=limit,
    )
    runs = await client.select(
        "search_runs",
        columns="id,research_job_id,provider,query,status,result_count,error,ran_at",
        order="ran_at.desc",
        limit=limit,
    )
    return {"jobs": rows, "search_runs": runs}


@router.post("/jobs/{job_id}/retry")
async def retry_job(staff: CurrentStaff, client: Client, job_id: int) -> dict:
    rows = await client.select(
        "research_jobs", columns="id,request_id,state,attempts", filters={"id": f"eq.{job_id}"}, limit=1
    )
    if not rows:
        raise NOT_FOUND
    await _load_request(client, rows[0]["request_id"], staff)

    if rows[0]["state"] not in {"failed", "dead"}:
        raise conflict("not_failed", "רק עבודה שנכשלה ניתנת להרצה מחדש")

    updated = await client.update(
        "research_jobs",
        filters={"id": f"eq.{job_id}"},
        # Attempts reset: a human decided to try again, which is not the same as
        # the automatic retry budget running out.
        values={"state": "queued", "attempts": 0, "run_after": "now()", "last_error": None},
        columns="id,state,attempts",
    )
    await _audit(client, staff.user_id, "job.retried", "research_job", job_id)
    return updated[0]


# ----------------------------------------------------------------- staff


@router.get("/members")
async def list_members(admin: CurrentAdmin, client: Client) -> dict:
    rows = await client.select("user_roles", columns="user_id,role,granted_at,granted_by")
    return {"items": rows}


class RoleBody(BaseModel):
    user_id: str
    role: Literal["researcher", "admin"]


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def grant_role(admin: CurrentAdmin, client: Client, payload: RoleBody) -> dict:
    created = await client.insert(
        "user_roles",
        {"user_id": payload.user_id, "role": payload.role, "granted_by": admin.user_id},
        columns="user_id,role,granted_at",
    )
    await _audit(client, admin.user_id, "role.granted", "user", payload.user_id, role=payload.role)
    return created
