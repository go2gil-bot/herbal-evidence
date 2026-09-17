"""/api/v1/pilot - comprehension measurement.

Two rules shape this module:

  * The participant never receives the answer key, before or after. Scoring
    happens here and only the number comes back.
  * A score is computed against the key as it stood at submission and stored, so
    editing a key later cannot silently rewrite what somebody was measured on.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser
from app.auth.roles import CurrentStaff, ensure_in_scope
from app.domain.pilot import (
    QUESTIONNAIRE_VERSION,
    QUESTIONS,
    AnswerKey,
    AssessmentSubmission,
    Question,
    score,
)
from app.services.supabase_client import SupabaseClient, SupabaseError, get_supabase

router = APIRouter(prefix="/api/v1", tags=["pilot"])
staff_router = APIRouter(prefix="/api/v1/staff", tags=["pilot"])

Client = Annotated[SupabaseClient, Depends(get_supabase)]


class Questionnaire(BaseModel):
    version: str
    questions: list[Question]


class AssessmentResult(BaseModel):
    phase: str
    score: int | None
    max_score: int | None
    # Deliberately no per-question feedback: telling a participant which answer
    # was wrong before the post phase would teach them the answer.
    message: str


@router.get("/pilot/questionnaire", response_model=Questionnaire)
def questionnaire(user: CurrentUser) -> Questionnaire:
    return Questionnaire(version=QUESTIONNAIRE_VERSION, questions=QUESTIONS)


@router.post("/pilot/assessments", response_model=AssessmentResult, status_code=201)
async def submit_assessment(
    user: CurrentUser, client: Client, payload: AssessmentSubmission
) -> AssessmentResult:
    try:
        payload.validate_shape()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_answers", "message": str(exc)},
        ) from exc

    # The participant must own the request this response belongs to. Answering
    # about someone else's response is not a thing.
    rows = await client.select(
        "response_versions",
        columns="id,request_id,state,requests(owner_id)",
        filters={"id": f"eq.{payload.response_version_id}"},
        limit=1,
    )
    if not rows or (rows[0].get("requests") or {}).get("owner_id") != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "לא נמצא"},
        )

    key_rows = await client.select(
        "pilot_answer_keys",
        columns="answers,questionnaire_version",
        filters={"response_version_id": f"eq.{payload.response_version_id}"},
        limit=1,
    )

    points: int | None = None
    total: int | None = None
    if key_rows and key_rows[0]["questionnaire_version"] == QUESTIONNAIRE_VERSION:
        points, total = score(payload.answers, key_rows[0]["answers"])

    profile = await client.select(
        "profiles", columns="participant_category", filters={"id": f"eq.{user.user_id}"}, limit=1
    )
    category = payload.participant_category or (
        profile[0]["participant_category"] if profile else None
    )
    if category not in ("patient", "caregiver"):
        category = None

    row = {
        "user_id": user.user_id,
        "response_version_id": payload.response_version_id,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "phase": payload.phase,
        "answers": payload.answers,
        "participant_category": category,
        "score": points,
        "max_score": total,
        "scored_against_key_at": "now()" if points is not None else None,
    }
    try:
        await client.insert("pilot_assessments", row, columns="id")
    except SupabaseError as exc:
        if exc.status_code == 409:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "already_answered", "message": "כבר ענית על השאלון בשלב הזה"},
            ) from exc
        raise

    return AssessmentResult(
        phase=payload.phase,
        score=points,
        max_score=total,
        message="תודה. התשובות נשמרו." if points is None else "תודה. התשובות נשמרו ונוקדו.",
    )


# ----------------------------------------------------------------- staff


@staff_router.post("/drafts/{version_id}/answer-key", status_code=201)
async def set_answer_key(
    staff: CurrentStaff, client: Client, version_id: int, payload: AnswerKey
) -> dict:
    try:
        payload.validate_shape()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_key", "message": str(exc)},
        ) from exc

    rows = await client.select(
        "response_versions", columns="id,request_id", filters={"id": f"eq.{version_id}"}, limit=1
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "לא נמצא"},
        )
    request_rows = await client.select(
        "requests", columns="id,assigned_researcher_id", filters={"id": f"eq.{rows[0]['request_id']}"}, limit=1
    )
    ensure_in_scope(staff, request_rows[0] if request_rows else {})

    existing = await client.select(
        "pilot_answer_keys", columns="response_version_id",
        filters={"response_version_id": f"eq.{version_id}"}, limit=1
    )
    values = {
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "answers": payload.answers,
        "approved_by": staff.user_id,
    }
    if existing:
        await client.update(
            "pilot_answer_keys",
            filters={"response_version_id": f"eq.{version_id}"},
            values=values,
            columns="response_version_id",
        )
    else:
        await client.insert(
            "pilot_answer_keys", {"response_version_id": version_id, **values},
            columns="response_version_id",
        )
    return {"response_version_id": version_id, "questionnaire_version": QUESTIONNAIRE_VERSION}


@staff_router.get("/pilot/results")
async def pilot_results(staff: CurrentStaff, client: Client) -> dict:
    """Patients and caregivers are reported separately, never pooled.

    Satisfaction is not measured here at all - the pilot's question is whether
    people understood, and a single mean across mixed groups would hide the only
    comparison that matters.
    """
    rows = await client.select(
        "pilot_assessments",
        columns="phase,participant_category,score,max_score,questionnaire_version",
        limit=1000,
    )

    groups: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        if row["score"] is None or not row["max_score"]:
            continue
        category = row["participant_category"] or "unspecified"
        groups.setdefault(category, {"pre": [], "post": []})
        groups[category][row["phase"]].append(row["score"] / row["max_score"])

    summary = {}
    for category, phases in groups.items():
        entry = {}
        for phase, values in phases.items():
            entry[phase] = {
                "n": len(values),
                "mean_proportion_correct": round(sum(values) / len(values), 3) if values else None,
            }
        summary[category] = entry

    return {
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "scored_assessments": sum(1 for r in rows if r["score"] is not None),
        "unscored_assessments": sum(1 for r in rows if r["score"] is None),
        "by_participant_category": summary,
        "note": (
            "Descriptive only. No sample size or success target has been agreed, "
            "so these numbers do not establish anything."
        ),
    }
