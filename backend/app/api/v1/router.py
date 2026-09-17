"""/api/v1 - the requester-facing surface.

Every handler here authorizes explicitly. The service role bypasses RLS, so
"filter by the caller's id" is a rule this layer must apply, not one the database
applies for it. Where a filter is the authorization check, it is marked.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import CurrentUser
from app.domain.schemas import (
    ApprovedResponse,
    ClarificationAnswer,
    ClarificationOut,
    IdentificationResult,
    Page,
    RequestCreate,
    RequestDetail,
    RequestSummary,
)
from app.services import plant_identification
from app.services.supabase_client import SupabaseClient, SupabaseError, get_supabase

router = APIRouter(prefix="/api/v1")

Client = Annotated[SupabaseClient, Depends(get_supabase)]

# Columns the requester is allowed to receive. Mirrors the column grants.
REQUEST_COLUMNS = (
    "id,owner_id,herb_input,preparation_input,cancer_type_input,treatment_input,"
    "question_input,preparation_unknown,cancer_type_unknown,treatment_unknown,"
    "identification_state,user_visible_status,closed_reason,created_at,"
    "plants(scientific_name)"
)

NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "לא נמצא"}
)


def _summary(row: dict) -> RequestSummary:
    return RequestSummary(
        id=row["id"],
        herb_input=row["herb_input"],
        status=row["user_visible_status"],
        identification_state=row["identification_state"],
        created_at=row["created_at"],
    )


async def _owned_request(client: SupabaseClient, request_id: int, user_id: str) -> dict:
    """Fetch a request, or 404. Ownership is the authorization check."""
    rows = await client.select(
        "requests",
        columns=REQUEST_COLUMNS,
        # Both filters matter: the second one is what makes this authorized.
        filters={"id": f"eq.{request_id}", "owner_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        # Deliberately 404, not 403: whether someone else's request exists is
        # not information this caller is entitled to.
        raise NOT_FOUND
    return rows[0]


@router.get("/plants/identify", response_model=IdentificationResult, tags=["requests"])
async def identify_plant(
    user: CurrentUser,
    client: Client,
    q: Annotated[str, Query(min_length=1, max_length=200)],
) -> IdentificationResult:
    return await plant_identification.identify(client, q)


@router.post(
    "/requests", response_model=RequestSummary, status_code=status.HTTP_201_CREATED, tags=["requests"]
)
async def create_request(user: CurrentUser, client: Client, payload: RequestCreate) -> RequestSummary:
    identification = await plant_identification.identify(client, payload.herb_input)

    plant_id: int | None = None
    state = "pending"

    if payload.chosen_plant_id is not None:
        # Only a plant that was actually offered may be chosen.
        offered = {c.plant_id for c in identification.candidates}
        if payload.chosen_plant_id not in offered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "plant_not_offered", "message": "הצמח שנבחר אינו אחת האפשרויות"},
            )
        plant_id = payload.chosen_plant_id
        state = "resolved"
    elif identification.outcome == "resolved":
        plant_id = identification.candidates[0].plant_id
        state = "resolved"
    elif identification.outcome == "ambiguous":
        # Stored as ambiguous rather than picking one. A human resolves it.
        state = "ambiguous"
    else:
        state = "pending"

    row = {
        # Never trusted from the payload.
        "owner_id": user.user_id,
        "herb_input": payload.herb_input.strip(),
        "preparation_input": payload.preparation_input,
        "cancer_type_input": payload.cancer_type_input,
        "treatment_input": payload.treatment_input,
        "question_input": payload.question_input,
        "preparation_unknown": payload.preparation_unknown,
        "cancer_type_unknown": payload.cancer_type_unknown,
        "treatment_unknown": payload.treatment_unknown,
        "identified_plant_id": plant_id,
        "identification_state": state,
    }

    try:
        created = await client.insert("requests", row, columns=REQUEST_COLUMNS)
    except SupabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "request_rejected", "message": "לא ניתן היה לשמור את הבקשה"},
        ) from exc

    await client.insert(
        "audit_events",
        {
            "actor_id": user.user_id,
            "action": "request.created",
            "entity_type": "request",
            "entity_id": str(created["id"]),
            # Identifiers only. The herb and the question stay out of the log.
            "metadata": {"identification_state": state},
        },
    )
    return _summary(created)


@router.get("/requests", response_model=Page, tags=["requests"])
async def list_requests(
    user: CurrentUser,
    client: Client,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page:
    rows = await client.select(
        "requests",
        columns=REQUEST_COLUMNS,
        filters={"owner_id": f"eq.{user.user_id}"},  # authorization
        order="created_at.desc",
        limit=limit,
        offset=offset,
    )
    total_rows = await client.select(
        "requests", columns="id", filters={"owner_id": f"eq.{user.user_id}"}
    )
    return Page(
        items=[_summary(row) for row in rows],
        total=len(total_rows),
        limit=limit,
        offset=offset,
    )


@router.get("/requests/{request_id}", response_model=RequestDetail, tags=["requests"])
async def get_request(user: CurrentUser, client: Client, request_id: int) -> RequestDetail:
    row = await _owned_request(client, request_id, user.user_id)

    clarifications = await client.select(
        "request_clarifications",
        columns="id,question,answer,asked_at,answered_at",
        filters={"request_id": f"eq.{request_id}"},
        order="asked_at.asc",
    )

    # Existence of a PUBLISHED version only. A draft must not be detectable.
    published = await client.select(
        "response_versions",
        columns="id",
        filters={"request_id": f"eq.{request_id}", "state": "eq.published"},
        limit=1,
    )

    plant = (row.get("plants") or {}).get("scientific_name")
    return RequestDetail(
        **_summary(row).model_dump(),
        preparation_input=row["preparation_input"],
        cancer_type_input=row["cancer_type_input"],
        treatment_input=row["treatment_input"],
        question_input=row["question_input"],
        preparation_unknown=row["preparation_unknown"],
        cancer_type_unknown=row["cancer_type_unknown"],
        treatment_unknown=row["treatment_unknown"],
        identified_plant=plant,
        closed_reason=row["closed_reason"],
        clarifications=[ClarificationOut(**c) for c in clarifications],
        has_response=bool(published),
    )


@router.post(
    "/requests/{request_id}/clarifications/{clarification_id}",
    response_model=ClarificationOut,
    tags=["requests"],
)
async def answer_clarification(
    user: CurrentUser,
    client: Client,
    request_id: int,
    clarification_id: int,
    payload: ClarificationAnswer,
) -> ClarificationOut:
    await _owned_request(client, request_id, user.user_id)

    updated = await client.update(
        "request_clarifications",
        filters={
            "id": f"eq.{clarification_id}",
            "request_id": f"eq.{request_id}",
            # Answer once. A second answer would rewrite the record.
            "answer": "is.null",
        },
        values={"answer": payload.answer.strip()},
        columns="id,question,answer,asked_at,answered_at",
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "already_answered", "message": "ההבהרה כבר נענתה"},
        )
    return ClarificationOut(**updated[0])


@router.get(
    "/requests/{request_id}/response", response_model=ApprovedResponse, tags=["requests"]
)
async def get_approved_response(
    user: CurrentUser, client: Client, request_id: int
) -> ApprovedResponse:
    await _owned_request(client, request_id, user.user_id)

    rows = await client.select(
        "response_versions",
        columns="id,request_id,version,body,published_at",
        # 'published' is not a convenience filter, it is the rule: a draft, a
        # superseded version and a withdrawn version are all unreachable here.
        filters={"request_id": f"eq.{request_id}", "state": "eq.published"},
        limit=1,
    )
    if not rows:
        raise NOT_FOUND
    row = rows[0]
    return ApprovedResponse(version_id=row.pop("id"), **row)
