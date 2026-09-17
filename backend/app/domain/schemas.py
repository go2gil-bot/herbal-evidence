"""Response schemas.

These are the shapes the browser is allowed to receive. Internal status, assigned
researcher, draft bodies and AI provenance appear nowhere in this file - that is
deliberate, and it is the second line of defence after the column grants.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

UserVisibleStatus = Literal[
    "received", "clarification_needed", "under_review", "response_available", "closed"
]

IdentificationState = Literal["pending", "resolved", "ambiguous", "multi_ingredient", "out_of_scope"]


class ErrorBody(BaseModel):
    code: str
    message: str


class PlantCandidate(BaseModel):
    plant_id: int
    scientific_name: str
    matched_alias: str
    language: str
    # Every alias we know, so the user can tell two similar plants apart.
    aliases: list[str] = Field(default_factory=list)


class IdentificationResult(BaseModel):
    """What the identifier found. It never invents a match."""

    outcome: Literal["resolved", "ambiguous", "not_found"]
    query: str
    candidates: list[PlantCandidate] = Field(default_factory=list)


class RequestCreate(BaseModel):
    herb_input: str = Field(min_length=1, max_length=200)
    preparation_input: str | None = Field(default=None, max_length=200)
    cancer_type_input: str | None = Field(default=None, max_length=200)
    treatment_input: str | None = Field(default=None, max_length=200)
    question_input: str | None = Field(default=None, max_length=1000)
    preparation_unknown: bool = False
    cancer_type_unknown: bool = False
    treatment_unknown: bool = False
    # Set only when the user picked one of the offered candidates.
    chosen_plant_id: int | None = None


class RequestSummary(BaseModel):
    id: int
    herb_input: str
    status: UserVisibleStatus
    identification_state: IdentificationState
    created_at: datetime


class ClarificationOut(BaseModel):
    id: int
    question: str
    answer: str | None
    asked_at: datetime
    answered_at: datetime | None


class RequestDetail(RequestSummary):
    preparation_input: str | None
    cancer_type_input: str | None
    treatment_input: str | None
    question_input: str | None
    preparation_unknown: bool
    cancer_type_unknown: bool
    treatment_unknown: bool
    identified_plant: str | None
    closed_reason: str | None
    clarifications: list[ClarificationOut] = Field(default_factory=list)
    # True only once an approved version exists. Never hints at a draft.
    has_response: bool = False


class ClarificationAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class ApprovedResponse(BaseModel):
    """An approved, published response. A draft can never be serialised here."""

    # The pilot questionnaire is answered about one exact version, so the reader
    # needs its id. Scoping still applies: only the owner ever reaches this.
    version_id: int
    request_id: int
    version: int
    published_at: datetime
    body: dict


class Page(BaseModel):
    items: list[RequestSummary]
    total: int
    limit: int
    offset: int
