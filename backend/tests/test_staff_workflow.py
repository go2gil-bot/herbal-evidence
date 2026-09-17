"""Staff workspace: scope, transitions, approval and the job queue."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import current_user
from app.auth.jwt import AuthenticatedUser
from app.domain.content_hash import content_hash
from app.domain.workflow import can_transition, requires_admin
from app.jobs import queue as job_queue
from app.jobs import worker as job_worker
from app.jobs.handlers import NotConfigured
from app.main import app
from app.services.supabase_client import SupabaseError, get_supabase

RESEARCHER = "11111111-0000-0000-0000-000000000001"
OTHER_RESEARCHER = "22222222-0000-0000-0000-000000000002"
ADMIN = "33333333-0000-0000-0000-000000000003"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.rows: dict[str, list[dict]] = {}
        self.rpc_error: SupabaseError | None = None
        self.rpc_calls: list[tuple[str, dict]] = []

    async def select(self, table, *, columns="*", filters=None, order=None, limit=None, offset=None):
        filters = filters or {}
        self.calls.append(("select", table, dict(filters)))
        rows = self.rows.get(table, [])
        for key, expression in filters.items():
            if expression.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == expression[3:]]
            elif expression == "is.null":
                rows = [r for r in rows if r.get(key) is None]
        return rows[: limit or len(rows)]

    async def insert(self, table, row, *, columns="*"):
        self.calls.append(("insert", table, dict(row)))
        stored = {"id": 500, "created_at": "2026-09-17T10:00:00Z", **row}
        self.rows.setdefault(table, []).append(stored)
        return stored

    async def update(self, table, *, filters, values, columns="*"):
        self.calls.append(("update", table, {**filters, **values}))
        return [{"id": 1, **values}]

    async def rpc(self, function, args):
        self.rpc_calls.append((function, dict(args)))
        if self.rpc_error:
            raise self.rpc_error
        return {"id": 9, "approved_by": args.get("p_approver")}


def staff_client(fake, user_id, roles):
    fake.rows["user_roles"] = [{"user_id": user_id, "role": role} for role in roles]
    app.dependency_overrides[get_supabase] = lambda: fake
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(user_id, None, None)
    return TestClient(app)


@pytest.fixture
def fake():
    yield FakeClient()
    app.dependency_overrides.clear()


def a_request(**overrides):
    row = {
        "id": 1042,
        "owner_id": "owner-1",
        "herb_input": "כורכום",
        "status": "researching",
        "identification_state": "resolved",
        "assigned_researcher_id": RESEARCHER,
        "research_question_id": None,
        "closed_reason": None,
        "created_at": "2026-09-17T10:00:00Z",
        "updated_at": "2026-09-17T10:00:00Z",
    }
    row.update(overrides)
    return row


# ------------------------------------------------------------------ scope


def test_a_user_with_no_role_is_not_staff(fake):
    client = staff_client(fake, "nobody", [])
    assert client.get("/api/v1/staff/queue").status_code == 403


def test_a_researcher_cannot_open_a_request_assigned_to_someone_else(fake):
    fake.rows["requests"] = [a_request(assigned_researcher_id=OTHER_RESEARCHER)]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    assert client.get("/api/v1/staff/requests/1042").status_code == 403


def test_an_admin_can_open_any_request(fake):
    fake.rows["requests"] = [a_request(assigned_researcher_id=OTHER_RESEARCHER)]
    client = staff_client(fake, ADMIN, ["admin"])
    assert client.get("/api/v1/staff/requests/1042").status_code == 200


def test_the_queue_is_scoped_to_a_researchers_assignments(fake):
    fake.rows["requests"] = []
    client = staff_client(fake, RESEARCHER, ["researcher"])
    client.get("/api/v1/staff/queue")
    selects = [c for c in fake.calls if c[0] == "select" and c[1] == "requests"]
    assert selects
    assert selects[0][2].get("assigned_researcher_id") == f"eq.{RESEARCHER}"


def test_only_an_admin_can_assign(fake):
    fake.rows["requests"] = [a_request()]
    researcher = staff_client(fake, RESEARCHER, ["researcher"])
    assert researcher.post(
        "/api/v1/staff/requests/1042/assign", json={"researcher_id": RESEARCHER}
    ).status_code == 403


# ------------------------------------------------------------- transitions


def test_nothing_transitions_into_published():
    for state in ["submitted", "researching", "draft_ready", "in_review", "revision_required"]:
        assert not can_transition(state, "published"), state


def test_reopening_a_published_request_is_admin_only():
    assert requires_admin("published", "in_review")
    assert not requires_admin("draft_ready", "in_review")


def test_setting_status_to_published_is_refused(fake):
    fake.rows["requests"] = [a_request(status="in_review")]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.post("/api/v1/staff/requests/1042/status", json={"status": "published"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "publish_requires_approval"


def test_an_impossible_transition_is_refused(fake):
    fake.rows["requests"] = [a_request(status="closed_out_of_scope")]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.post("/api/v1/staff/requests/1042/status", json={"status": "researching"})
    assert response.status_code == 409


def test_closing_a_request_requires_an_explanation(fake):
    fake.rows["requests"] = [a_request(status="submitted")]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.post(
        "/api/v1/staff/requests/1042/status", json={"status": "closed_out_of_scope"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "reason_required"


# ---------------------------------------------------------------- approval


def test_the_hash_ignores_key_order_but_not_content():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
    # Hebrew is hashed as itself, not as escape sequences.
    assert content_hash({"x": "מסקנה"}) == content_hash({"x": "מסקנה"})


def test_approval_with_a_missing_check_never_reaches_the_database(fake):
    fake.rows["response_versions"] = [{"id": 7, "request_id": 1042, "version": 1}]
    fake.rows["requests"] = [a_request()]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.post(
        "/api/v1/staff/drafts/7/approve",
        json={
            "expected_content_hash": "abc",
            "checked_sources": True,
            "checked_claim_evidence_alignment": True,
            "checked_limitations": False,
            "checked_user_wording": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "checks_incomplete"
    assert not fake.rpc_calls, "the database was called despite an incomplete confirmation"


def test_a_stale_draft_is_reported_as_needing_another_review(fake):
    fake.rows["response_versions"] = [{"id": 7, "request_id": 1042, "version": 1}]
    fake.rows["requests"] = [a_request()]
    fake.rpc_error = SupabaseError(409, "PT409", "draft changed since it was reviewed")
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.post(
        "/api/v1/staff/drafts/7/approve",
        json={
            "expected_content_hash": "stale",
            "checked_sources": True,
            "checked_claim_evidence_alignment": True,
            "checked_limitations": True,
            "checked_user_wording": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "draft_changed"


def test_approval_sends_the_hash_the_reviewer_saw(fake):
    fake.rows["response_versions"] = [{"id": 7, "request_id": 1042, "version": 1}]
    fake.rows["requests"] = [a_request()]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    client.post(
        "/api/v1/staff/drafts/7/approve",
        json={
            "expected_content_hash": "hash-seen-by-reviewer",
            "checked_sources": True,
            "checked_claim_evidence_alignment": True,
            "checked_limitations": True,
            "checked_user_wording": True,
        },
    )
    name, args = fake.rpc_calls[0]
    assert name == "approve_response_version"
    assert args["p_expected_content_hash"] == "hash-seen-by-reviewer"
    assert args["p_approver"] == RESEARCHER


def test_saving_a_draft_recomputes_the_hash(fake):
    fake.rows["response_versions"] = [{"id": 7, "request_id": 1042, "state": "draft"}]
    fake.rows["requests"] = [a_request()]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    body = {"conclusion": "טקסט חדש"}
    client.patch("/api/v1/staff/drafts/7", json={"body": body, "source_ids": []})
    updates = [c for c in fake.calls if c[0] == "update" and c[1] == "response_versions"]
    assert updates[0][2]["content_hash"] == content_hash(body)


def test_a_published_version_cannot_be_edited_as_a_draft(fake):
    fake.rows["response_versions"] = [{"id": 7, "request_id": 1042, "state": "published"}]
    fake.rows["requests"] = [a_request()]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    response = client.patch("/api/v1/staff/drafts/7", json={"body": {}, "source_ids": []})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_a_draft"


# --------------------------------------------------------------- job queue


def test_enqueueing_twice_for_the_same_state_uses_the_same_key(fake):
    fake.rows["requests"] = [a_request(status="submitted")]
    client = staff_client(fake, RESEARCHER, ["researcher"])
    client.post("/api/v1/staff/requests/1042/jobs", json={"job_type": "identify_plant"})
    client.post("/api/v1/staff/requests/1042/jobs", json={"job_type": "identify_plant"})
    keys = [c[2]["idempotency_key"] for c in fake.calls if c[0] == "insert" and c[1] == "research_jobs"]
    assert len(keys) == 2 and keys[0] == keys[1]


def test_a_blocked_provider_is_recorded_as_a_failure_not_a_result(fake):
    """The core rule: a missing provider must never look like a finding."""
    fake.rpc_results = {}
    claimed = {"id": 77, "request_id": 1042, "job_type": "draft", "attempts": 1}

    async def fake_claim(client, worker):
        return claimed

    failures = []

    async def fake_fail(client, job_id, error):
        failures.append((job_id, error))
        return {}

    completions = []

    async def fake_complete(client, job_id, worker):
        completions.append(job_id)
        return True

    async def blocked(client, job):
        raise NotConfigured("no AI provider configured")

    original = (job_queue.claim, job_queue.fail, job_queue.complete)
    job_queue.claim, job_queue.fail, job_queue.complete = fake_claim, fake_fail, fake_complete
    job_worker.HANDLERS["draft"] = blocked
    try:
        did_work = asyncio.run(job_worker.process_one(fake, "worker-1"))
    finally:
        job_queue.claim, job_queue.fail, job_queue.complete = original

    assert did_work is True
    assert completions == [], "a blocked job must not be marked successful"
    assert failures and failures[0][1]["kind"] == "not_configured"


def test_an_empty_queue_is_not_an_error(fake):
    async def nothing(client, worker):
        return None

    original = job_queue.claim
    job_queue.claim = nothing
    try:
        assert asyncio.run(job_worker.process_one(fake, "worker-1")) is False
    finally:
        job_queue.claim = original
