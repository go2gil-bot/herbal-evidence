"""Acceptance checks 1-3 run against a live Supabase project.

These are not unit tests. They create two real users, then try - as those users,
through PostgREST, exactly as a browser would - to reach data that is not theirs.
A green run is the evidence that authorization is in the database, not in the UI.

Usage (reads supabase/.env, which is gitignored):

    python supabase/tests/rls_isolation.py

Never point this at Production.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

# This machine's bundled certifi roots are stale, so a freshly issued Railway
# certificate fails verification here while curl (which uses the OS store)
# accepts it. Prefer the operating system's trust store when truststore is
# available. Verification stays ON either way - disabling it would make every
# check below meaningless over TLS.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

import uuid

ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"

# Columns a requester is granted. Asking for anything else is a 403 by design.
REQ_COLS = "id,owner_id,herb_input,user_visible_status,identification_state,created_at"
RESP_COLS = "id,request_id,version,body,published_at"

failures: list[str] = []
checks = 0


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("DEV_SUPABASE")})
    return values


def request(
    method: str, url: str, *, token: str, apikey: str, body: object = None, prefer: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", apikey)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, raw


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)


def main() -> int:
    env = load_env()
    url = env.get("DEV_SUPABASE_URL")
    anon = env.get("DEV_SUPABASE_ANON_KEY")
    service = env.get("DEV_SUPABASE_SERVICE_ROLE_KEY")

    if not (url and anon and service):
        print("Missing DEV_SUPABASE_URL / ANON / SERVICE_ROLE key in supabase/.env")
        return 2

    rest = f"{url}/rest/v1"
    auth = f"{url}/auth/v1"
    suffix = uuid.uuid4().hex[:8]

    # --- two real users -----------------------------------------------------
    users = {}
    for label in ("a", "b"):
        email = f"rls-{label}-{suffix}@example.test"
        password = f"Pw-{uuid.uuid4().hex}"
        status, created = request(
            "POST",
            f"{auth}/admin/users",
            token=service,
            apikey=service,
            body={"email": email, "password": password, "email_confirm": True},
        )
        if status >= 300:
            print(f"could not create user {label}: {status} {created}")
            return 2
        status, session = request(
            "POST",
            f"{auth}/token?grant_type=password",
            token=anon,
            apikey=anon,
            body={"email": email, "password": password},
        )
        if status >= 300:
            print(f"could not sign in user {label}: {status} {session}")
            return 2
        users[label] = {"id": created["id"], "token": session["access_token"]}

    a, b = users["a"], users["b"]
    print(f"\nusers: A={a['id']}  B={b['id']}\n")

    # --- user A submits a request ------------------------------------------
    print("submission")
    status, created = request(
        "POST",
        f"{rest}/requests?select={REQ_COLS}",
        token=a["token"],
        apikey=anon,
        body={"owner_id": a["id"], "herb_input": "כורכום", "preparation_unknown": True},
        prefer="return=representation",
    )
    check("user A can submit a request", status == 201, f"{status} {created}")
    if status != 201:
        return 1
    request_id = created[0]["id"]

    check(
        "internal status is not readable by the requester",
        "status" not in created[0] and "assigned_researcher_id" not in created[0],
        f"returned keys: {sorted(created[0])}",
    )
    check(
        "requester sees the simple status instead",
        created[0].get("user_visible_status") == "received",
        str(created[0].get("user_visible_status")),
    )

    # --- acceptance 1: cross-user reads ------------------------------------
    print("\nacceptance 1 - user A cannot read user B's data")
    status, rows = request("GET", f"{rest}/requests?select={REQ_COLS}", token=b["token"], apikey=anon)
    check("user B's request list does not contain A's request", rows == [], f"{status} {rows}")

    status, rows = request(
        "GET", f"{rest}/requests?select={REQ_COLS}&id=eq.{request_id}", token=b["token"], apikey=anon
    )
    check("user B cannot fetch A's request by id", rows == [], f"{status} {rows}")

    status, rows = request("GET", f"{rest}/requests?select={REQ_COLS}", token=anon, apikey=anon)
    check("anonymous cannot list requests", status >= 400 or rows == [], f"{status} {rows}")

    # --- acceptance 2: drafts and privilege escalation ----------------------
    print("\nacceptance 2 - drafts are unreachable, payloads cannot escalate")

    status, draft = request(
        "POST",
        f"{rest}/response_versions",
        token=service,
        apikey=service,
        body={
            "request_id": request_id,
            "version": 1,
            "body": {"conclusion": "MOCK - development only"},
            "content_hash": "hash-v1",
            "state": "draft",
        },
        prefer="return=representation",
    )
    check("backend can create a draft", status == 201, f"{status} {draft}")
    draft_id = draft[0]["id"] if status == 201 else None

    status, rows = request("GET", f"{rest}/response_versions?select={RESP_COLS}", token=a["token"], apikey=anon)
    check("the owner cannot read their own draft", rows == [], f"{status} {rows}")

    status, rows = request(
        "GET", f"{rest}/response_versions?select={RESP_COLS}", token=b["token"], apikey=anon
    )
    check("another user cannot read the draft either", rows == [], f"{status} {rows}")

    status, result = request(
        "POST",
        f"{rest}/requests",
        token=a["token"],
        apikey=anon,
        body={
            "owner_id": a["id"],
            "herb_input": "escalation attempt",
            "status": "published",
            "assigned_researcher_id": a["id"],
        },
    )
    check("a payload cannot set status or assignee", status >= 400, f"{status} {result}")

    status, result = request(
        "POST",
        f"{rest}/user_roles",
        token=a["token"],
        apikey=anon,
        body={"user_id": a["id"], "role": "admin"},
    )
    check("a user cannot grant themselves a role", status >= 400, f"{status} {result}")

    status, result = request(
        "POST",
        f"{rest}/requests",
        token=a["token"],
        apikey=anon,
        body={"owner_id": b["id"], "herb_input": "on behalf of someone else"},
    )
    check("a user cannot submit a request as someone else", status >= 400, f"{status} {result}")

    for table in ("sources", "evidence_items", "reviews", "research_jobs", "audit_events"):
        status, rows = request("GET", f"{rest}/{table}?select=*", token=a["token"], apikey=anon)
        check(f"staff table {table} is unreadable", status >= 400 or rows == [], f"{status} {rows}")

    # --- acceptance 3: approval binds to one exact version ------------------
    print("\nacceptance 3 - approval binds to the exact reviewed version")

    status, result = request(
        "POST",
        f"{rest}/rpc/approve_response_version",
        token=service,
        apikey=service,
        body={
            "p_response_version_id": draft_id,
            "p_expected_content_hash": "hash-that-does-not-match",
            "p_approver": a["id"],
            "p_checked_sources": True,
            "p_checked_claim_evidence_alignment": True,
            "p_checked_limitations": True,
            "p_checked_user_wording": True,
        },
    )
    check(
        "approving a stale hash is refused",
        status >= 400 and "changed since it was reviewed" in json.dumps(result),
        f"{status} {result}",
    )

    status, result = request(
        "POST",
        f"{rest}/rpc/approve_response_version",
        token=service,
        apikey=service,
        body={
            "p_response_version_id": draft_id,
            "p_expected_content_hash": "hash-v1",
            "p_approver": a["id"],
            "p_checked_sources": True,
            "p_checked_claim_evidence_alignment": True,
            "p_checked_limitations": False,
            "p_checked_user_wording": True,
        },
    )
    check("approval without every check is refused", status >= 400, f"{status} {result}")

    status, result = request(
        "POST",
        f"{rest}/rpc/approve_response_version",
        token=service,
        apikey=service,
        body={
            "p_response_version_id": draft_id,
            "p_expected_content_hash": "hash-v1",
            "p_approver": a["id"],
            "p_checked_sources": True,
            "p_checked_claim_evidence_alignment": True,
            "p_checked_limitations": True,
            "p_checked_user_wording": True,
        },
    )
    check("a correctly checked approval succeeds", status < 300, f"{status} {result}")

    status, rows = request("GET", f"{rest}/response_versions?select={RESP_COLS}", token=a["token"], apikey=anon)
    check("after approval the owner can read the response", len(rows or []) == 1, f"{status} {rows}")

    status, rows = request("GET", f"{rest}/response_versions?select={RESP_COLS}", token=b["token"], apikey=anon)
    check("another user still cannot read it", rows == [], f"{status} {rows}")

    # --- withdrawal stops showing as approved -------------------------------
    print("\nwithdrawal")
    status, result = request(
        "POST",
        f"{rest}/rpc/withdraw_response_version",
        token=service,
        apikey=service,
        body={"p_response_version_id": draft_id, "p_actor": a["id"], "p_reason": "test withdrawal"},
    )
    check("a withdrawal with a reason succeeds", status < 300, f"{status} {result}")

    status, rows = request("GET", f"{rest}/response_versions?select={RESP_COLS}", token=a["token"], apikey=anon)
    check("withdrawn content stops being shown", rows == [], f"{status} {rows}")

    # --- cleanup ------------------------------------------------------------
    for user in users.values():
        request("DELETE", f"{auth}/admin/users/{user['id']}", token=service, apikey=service)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
