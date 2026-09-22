"""The API layer's own authorization, tested without a database.

The service role bypasses RLS, so these tests exist to prove the API never asks
the database a question that is not already scoped to the caller. A fake client
records every query, and the assertions are about the filters that were sent.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import router as router_module
from app.auth.dependencies import current_user
from app.auth.jwt import AuthenticatedUser
from app.main import app
from app.services.supabase_client import get_supabase

USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000002"


class FakeClient:
    """Stands in for PostgREST and remembers what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}

    async def select(self, table, *, columns="*", filters=None, order=None, limit=None, offset=None):
        filters = filters or {}
        self.calls.append(("select", table, dict(filters)))
        rows = self.rows.get(table, [])
        for key, expression in filters.items():
            if expression.startswith("eq."):
                wanted = expression[3:]
                rows = [r for r in rows if str(r.get(key)) == wanted]
            elif expression == "is.null":
                rows = [r for r in rows if r.get(key) is None]
        return rows[: limit or len(rows)]

    async def insert(self, table, row, *, columns="*"):
        self.calls.append(("insert", table, dict(row)))
        stored = {"id": 1042, "created_at": "2026-09-17T10:00:00Z", **row}
        if table == "requests":
            # The database computes this one; mirror the mapping so the fake
            # returns the same shape PostgREST would.
            stored.setdefault("user_visible_status", "received")
        self.rows.setdefault(table, []).append(stored)
        return stored

    async def update(self, table, *, filters, values, columns="*"):
        self.calls.append(("update", table, dict(filters)))
        return []

    async def rpc(self, function, args):
        self.calls.append(("rpc", function, dict(args)))
        return None


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client_as_a(fake):
    app.dependency_overrides[get_supabase] = lambda: fake
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(USER_A, "a@example.test", None)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous():
    app.dependency_overrides.clear()
    return TestClient(app)


def test_every_request_endpoint_requires_a_token(anonymous):
    for method, path in [
        ("get", "/api/v1/requests"),
        ("get", "/api/v1/requests/1042"),
        ("get", "/api/v1/requests/1042/response"),
        ("get", "/api/v1/plants/identify?q=turmeric"),
    ]:
        response = getattr(anonymous, method)(path)
        assert response.status_code == 401, path


def test_listing_is_scoped_to_the_caller(client_as_a, fake):
    fake.rows["requests"] = []
    client_as_a.get("/api/v1/requests")
    selects = [c for c in fake.calls if c[0] == "select" and c[1] == "requests"]
    assert selects, "no query was made"
    for _, _, filters in selects:
        assert filters.get("owner_id") == f"eq.{USER_A}"


def test_another_users_request_is_not_found(client_as_a, fake):
    fake.rows["requests"] = [
        {
            "id": 1042,
            "owner_id": USER_B,
            "herb_input": "כורכום",
            "user_visible_status": "received",
            "identification_state": "resolved",
            "created_at": "2026-09-17T10:00:00Z",
        }
    ]
    response = client_as_a.get("/api/v1/requests/1042")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_owner_id_in_the_payload_is_ignored(client_as_a, fake):
    fake.rows["plant_aliases"] = []
    response = client_as_a.post(
        "/api/v1/requests",
        json={"herb_input": "כורכום", "owner_id": USER_B, "status": "published"},
    )
    assert response.status_code == 201
    inserts = [c for c in fake.calls if c[0] == "insert" and c[1] == "requests"]
    assert inserts[0][2]["owner_id"] == USER_A
    assert "status" not in inserts[0][2]


def test_the_response_endpoint_only_ever_asks_for_published(client_as_a, fake):
    fake.rows["requests"] = [
        {
            "id": 1042,
            "owner_id": USER_A,
            "herb_input": "כורכום",
            "user_visible_status": "response_available",
            "identification_state": "resolved",
            "created_at": "2026-09-17T10:00:00Z",
            "preparation_input": None,
            "cancer_type_input": None,
            "treatment_input": None,
            "question_input": None,
            "preparation_unknown": False,
            "cancer_type_unknown": False,
            "treatment_unknown": False,
            "closed_reason": None,
        }
    ]
    fake.rows["response_versions"] = [
        {
            "request_id": 1042,
            "version": 1,
            "body": {"conclusion": "x"},
            "published_at": "2026-09-17T11:00:00Z",
            "state": "draft",
        }
    ]
    response = client_as_a.get("/api/v1/requests/1042/response")
    # The only stored version is a draft, so there is nothing to return.
    assert response.status_code == 404
    selects = [c for c in fake.calls if c[1] == "response_versions"]
    assert selects and all(f.get("state") == "eq.published" for _, _, f in selects)


def test_a_draft_does_not_show_up_as_an_available_response(client_as_a, fake):
    fake.rows["requests"] = [
        {
            "id": 1042,
            "owner_id": USER_A,
            "herb_input": "כורכום",
            "user_visible_status": "under_review",
            "identification_state": "resolved",
            "created_at": "2026-09-17T10:00:00Z",
            "preparation_input": None,
            "cancer_type_input": None,
            "treatment_input": None,
            "question_input": None,
            "preparation_unknown": False,
            "cancer_type_unknown": False,
            "treatment_unknown": False,
            "closed_reason": None,
        }
    ]
    fake.rows["response_versions"] = [{"request_id": 1042, "id": 7, "state": "draft"}]
    detail = client_as_a.get("/api/v1/requests/1042").json()
    assert detail["has_response"] is False
    assert detail["status"] == "under_review"


def test_a_plant_that_was_not_offered_cannot_be_chosen(client_as_a, fake):
    fake.rows["plant_aliases"] = []
    response = client_as_a.post(
        "/api/v1/requests", json={"herb_input": "משהו", "chosen_plant_id": 99}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "plant_not_offered"


def test_an_ambiguous_name_is_stored_as_ambiguous_not_guessed(client_as_a, fake):
    # The same common name belongs to two different species - the case the
    # specification cares about. Neither one is picked.
    fake.rows["plant_aliases"] = [
        {"alias": "מרווה", "language": "he", "plant_id": 1, "plants": {"scientific_name": "Salvia officinalis"}},
        {"alias": "מרווה", "language": "he", "plant_id": 2, "plants": {"scientific_name": "Salvia fruticosa"}},
    ]
    response = client_as_a.post("/api/v1/requests", json={"herb_input": "מרווה"})
    assert response.status_code == 201
    assert response.json()["identification_state"] == "ambiguous"
    inserts = [c for c in fake.calls if c[0] == "insert" and c[1] == "requests"]
    assert inserts[0][2]["identified_plant_id"] is None


def test_an_exact_alias_wins_over_a_longer_partial_one(client_as_a, fake):
    # Typing "מרווה" when "מרווה משולשת" also exists is not ambiguity: one alias
    # is exactly what was typed. Treating it as ambiguous would ask the user a
    # question they already answered.
    fake.rows["plant_aliases"] = [
        {"alias": "מרווה", "language": "he", "plant_id": 1, "plants": {"scientific_name": "Salvia officinalis"}},
        {"alias": "מרווה משולשת", "language": "he", "plant_id": 2, "plants": {"scientific_name": "Salvia fruticosa"}},
    ]
    response = client_as_a.post("/api/v1/requests", json={"herb_input": "מרווה"})
    assert response.json()["identification_state"] == "resolved"


def test_an_unknown_name_goes_to_human_review_not_a_guess(client_as_a, fake):
    fake.rows["plant_aliases"] = [
        {"alias": "כורכום", "language": "he", "plant_id": 1, "plants": {"scientific_name": "Curcuma longa"}},
    ]
    response = client_as_a.post("/api/v1/requests", json={"herb_input": "צמח שלא קיים במאגר"})
    assert response.status_code == 201
    assert response.json()["identification_state"] == "pending"
    inserts = [c for c in fake.calls if c[0] == "insert" and c[1] == "requests"]
    assert inserts[0][2]["identified_plant_id"] is None


def test_the_audit_event_does_not_carry_the_question(client_as_a, fake):
    fake.rows["plant_aliases"] = []
    client_as_a.post(
        "/api/v1/requests",
        json={"herb_input": "כורכום", "question_input": "האם זה יעזור לאבא שלי?"},
    )
    audits = [c for c in fake.calls if c[0] == "insert" and c[1] == "audit_events"]
    assert audits, "no audit event was written"
    serialised = str(audits[0][2])
    assert "אבא" not in serialised and "כורכום" not in serialised


def test_a_rate_limited_insert_becomes_429_not_a_generic_400(client_as_a, fake, monkeypatch):
    """The limit is a database trigger, so the API's job is only to name it.

    Without this mapping the refusal arrived as the same 400 as a malformed
    payload, which tells the person to fix their input when there is nothing
    wrong with it.
    """
    from app.services.supabase_client import SupabaseError

    async def refuse(table, row, *, columns="*"):
        if table == "requests":
            raise SupabaseError(429, "PT429", "rate limit: 5 requests in the last hour")
        return {"id": 1}

    fake.rows["plant_aliases"] = []
    monkeypatch.setattr(fake, "insert", refuse)

    response = client_as_a.post("/api/v1/requests", json={"herb_input": "כורכום"})

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "too_many_requests"
    # The person is told what to do, and the raw SQLSTATE text is not echoed.
    assert "שעה" in detail["message"]
    assert "PT429" not in detail["message"] and "rate limit" not in detail["message"]
