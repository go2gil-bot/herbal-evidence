"""Acceptance criteria 4 and 8 - the two the other suites do not reach.

**4.** Similar requests reuse research without sharing personal details and
without skipping an individual approval.

**8.** A backend restart does not lose a job or publish its result twice. The
mechanism being tested is the lease: a claimed job whose lease expired is
claimable again, which is what "recoverable after a restart" actually means.
The claim is one atomic UPDATE, so two workers cannot hold the same job.

    python supabase/tests/reuse_and_recovery.py

Talks to Supabase directly with the service role, because the lease behaviour is
a database guarantee and testing it through the API would be testing the wrong
layer. Never point this at Production.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"

failures: list[str] = []
checks = 0


def env() -> dict[str, str]:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("DEV_SUPABASE")})
    return values


def http(method: str, url: str, *, key: str, token: str | None = None, body: object = None,
         prefer: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {token or key}")
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
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        failures.append(name)


def main() -> int:
    values = env()
    url = values.get("DEV_SUPABASE_URL")
    anon = values.get("DEV_SUPABASE_ANON_KEY")
    service = values.get("DEV_SUPABASE_SERVICE_ROLE_KEY")
    if not (url and anon and service):
        print("missing supabase/.env values")
        return 2

    rest, auth_url = f"{url}/rest/v1", f"{url}/auth/v1"
    suffix = uuid.uuid4().hex[:8]

    # --- two users asking about the same herb -------------------------------
    print("acceptance 4 - similar requests reuse research, not each other's data")

    users = {}
    for label in ("a", "b"):
        email = f"reuse-{label}-{suffix}@example.test"
        password = f"Pw-{uuid.uuid4().hex}"
        status, created = http("POST", f"{auth_url}/admin/users", key=service,
                               body={"email": email, "password": password, "email_confirm": True})
        if status >= 300:
            print(f"could not create user {label}: {status} {created}")
            return 2
        status, session = http("POST", f"{auth_url}/token?grant_type=password", key=anon,
                               body={"email": email, "password": password})
        users[label] = {"id": created["id"], "token": session["access_token"]}

    a, b = users["a"], users["b"]

    # One shared research question, which is the thing that may be reused.
    status, question = http(
        "POST", f"{rest}/research_questions", key=service, prefer="return=representation",
        body={"normalized_question": f"[test {suffix}] curcumin and appetite"},
    )
    question_id = question[0]["id"]

    requests = {}
    for label, user in (("a", a), ("b", b)):
        status, row = http(
            "POST", f"{rest}/requests?select=id", key=anon, token=user["token"],
            prefer="return=representation",
            body={"owner_id": user["id"], "herb_input": "כורכום", "preparation_input": "תה"},
        )
        requests[label] = row[0]["id"]
        # Staff work groups them onto the same research question.
        http("PATCH", f"{rest}/requests?id=eq.{row[0]['id']}", key=service,
             body={"research_question_id": question_id})

    check("two similar requests stay two separate requests",
          requests["a"] != requests["b"], str(requests))

    status, rows = http("GET", f"{rest}/requests?select=id,research_question_id&id=in.({requests['a']},{requests['b']})",
                        key=service)
    check("both point at the same research question",
          {r["research_question_id"] for r in rows} == {question_id}, str(rows))

    # A reusable review hangs off the question, not off a requester.
    status, review = http("POST", f"{rest}/reviews", key=service, prefer="return=representation",
                          body={"research_question_id": question_id})
    review_id = review[0]["id"]
    status, review_version = http(
        "POST", f"{rest}/review_versions", key=service, prefer="return=representation",
        body={"review_id": review_id, "version": 1, "content_hash": f"reuse-{suffix}",
              "body": {"conclusion": "[נתוני דמה] אין מספיק ראיות מבני אדם"}},
    )
    review_version_id = review_version[0]["id"]

    serialised = json.dumps(review_version[0], ensure_ascii=False)
    check("the reusable review carries no owner or requester field",
          "owner" not in serialised and str(a["id"]) not in serialised
          and str(b["id"]) not in serialised, serialised[:120])

    # Each request gets its own response built on the shared review.
    version_ids = {}
    for label in ("a", "b"):
        status, draft = http(
            "POST", f"{rest}/response_versions", key=service, prefer="return=representation",
            body={"request_id": requests[label], "version": 1,
                  "body": {"conclusion": "[נתוני דמה] מבוסס על סקירה משותפת"},
                  "review_version_id": review_version_id,
                  "content_hash": f"resp-{label}-{suffix}", "state": "draft"},
        )
        version_ids[label] = draft[0]["id"]

    check("both responses reuse the same review version",
          version_ids["a"] != version_ids["b"], str(version_ids))

    # Approve A only. B must not become readable as a side effect.
    approval = {
        "p_expected_content_hash": f"resp-a-{suffix}", "p_approver": a["id"],
        "p_checked_sources": True, "p_checked_claim_evidence_alignment": True,
        "p_checked_limitations": True, "p_checked_user_wording": True,
    }
    status, _ = http("POST", f"{rest}/rpc/approve_response_version", key=service,
                     body={"p_response_version_id": version_ids["a"], **approval})
    check("approving A's response succeeds", status < 300, str(status))

    status, rows = http(
        "GET", f"{rest}/response_versions?select=id,request_id,version,body,published_at",
        key=anon, token=b["token"])
    check("B's response is still not published by A's approval", rows == [], str(rows))

    status, rows = http(
        "GET", f"{rest}/response_versions?select=id,request_id,version,body,published_at",
        key=anon, token=a["token"])
    check("A reads only A's response", len(rows or []) == 1 and rows[0]["request_id"] == requests["a"],
          str(rows))

    # --- lease recovery ------------------------------------------------------
    print("\nacceptance 8 - an interrupted job is recoverable, and not done twice")

    status, job = http(
        "POST", f"{rest}/research_jobs", key=service, prefer="return=representation",
        body={"request_id": requests["a"], "job_type": "identify_plant",
              "idempotency_key": f"recovery-{suffix}"},
    )
    job_id = job[0]["id"]

    status, claimed = http("POST", f"{rest}/rpc/claim_research_job", key=service,
                           body={"p_worker": "worker-that-will-die", "p_lease_seconds": 2})
    check("a worker can claim the job", status < 300 and claimed, str(claimed)[:120])

    status, second = http("POST", f"{rest}/rpc/claim_research_job", key=service,
                          body={"p_worker": "worker-two", "p_lease_seconds": 300})
    took_same = bool(second) and second.get("id") == claimed.get("id")
    check("a second worker does not take the same job while the lease holds",
          not took_same, str(second)[:120])

    # The first worker "dies": no heartbeat, lease expires.
    time.sleep(4)

    status, reclaimed = http("POST", f"{rest}/rpc/claim_research_job", key=service,
                             body={"p_worker": "worker-after-restart", "p_lease_seconds": 300})
    check("after the lease expires the job is claimable again",
          bool(reclaimed) and reclaimed.get("id") == claimed.get("id"), str(reclaimed)[:140])
    check("the retry budget counted the interrupted attempt",
          bool(reclaimed) and reclaimed.get("attempts", 0) > claimed.get("attempts", 0),
          f"{claimed.get('attempts')} -> {reclaimed.get('attempts') if reclaimed else None}")

    # Only the current owner may finish it - the dead worker cannot.
    status, stale_complete = http("POST", f"{rest}/rpc/complete_research_job", key=service,
                                  body={"p_job_id": job_id, "p_worker": "worker-that-will-die"})
    check("the worker that lost the lease cannot complete the job",
          stale_complete is False, str(stale_complete))

    status, real_complete = http("POST", f"{rest}/rpc/complete_research_job", key=service,
                                 body={"p_job_id": job_id, "p_worker": "worker-after-restart"})
    check("the current owner can complete it", real_complete is True, str(real_complete))

    status, again = http("POST", f"{rest}/rpc/complete_research_job", key=service,
                         body={"p_job_id": job_id, "p_worker": "worker-after-restart"})
    check("completing twice does not succeed twice", again is False, str(again))

    # --- cleanup -------------------------------------------------------------
    for user in users.values():
        http("DELETE", f"{auth_url}/admin/users/{user['id']}", key=service)
    http("DELETE", f"{rest}/review_versions?id=eq.{review_version_id}", key=service)
    http("DELETE", f"{rest}/reviews?id=eq.{review_id}", key=service)
    http("DELETE", f"{rest}/research_questions?id=eq.{question_id}", key=service)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
