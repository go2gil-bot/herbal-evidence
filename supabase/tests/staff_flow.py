"""Acceptance checks 3, 5 and 8 against a running backend and the dev project.

Signs in as a real staff account and drives the API the way the review screen
does: create a draft, let it change underneath, then try to approve the version
that was read. Also enqueues a job whose provider is missing, to prove a blocked
integration stays a failure and never becomes a finding.

    python supabase/tests/staff_flow.py            # backend on :8000
    API=http://localhost:8000 python supabase/tests/staff_flow.py

Never point this at Production.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
import time
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


ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
API = os.environ.get("API", "http://localhost:8000")
EMAIL = os.environ.get("STAFF_EMAIL", "demo-dev@example.test")
PASSWORD = os.environ.get("STAFF_PASSWORD", "DemoDev-2026!")

failures: list[str] = []
checks = 0


def env() -> dict[str, str]:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def http(method: str, url: str, *, headers: dict, body: object = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
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
    supabase_url = values.get("DEV_SUPABASE_URL")
    anon = values.get("DEV_SUPABASE_ANON_KEY")
    if not (supabase_url and anon):
        print("missing supabase/.env values")
        return 2

    status, session = http(
        "POST",
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon, "Content-Type": "application/json"},
        body={"email": EMAIL, "password": PASSWORD},
    )
    if status >= 300:
        print(f"could not sign in as {EMAIL}: {status} {session}")
        return 2
    auth = {"Authorization": f"Bearer {session['access_token']}", "Content-Type": "application/json"}

    status, queue = http("GET", f"{API}/api/v1/staff/queue?assigned=any", headers=auth)
    if status != 200:
        print(f"no staff access for {EMAIL}: {status} {queue}")
        return 2

    # The script needs a request it OWNS, because the last checks read the
    # response through the requester endpoint - and that endpoint is scoped to
    # the owner, as it should be. So: submit one, then assign it to ourselves.
    # This account is therefore both a requester and staff, which is true on dev
    # and deliberately would not be true in production.
    status, submitted = http(
        "POST", f"{API}/api/v1/requests", headers=auth,
        body={"herb_input": "כורכום", "preparation_unknown": True},
    )
    if status != 201:
        print(f"could not submit a request: {status} {submitted}")
        return 2
    request_id = submitted["id"]

    claims = session["access_token"].split(".")[1]
    user_id = json.loads(base64.urlsafe_b64decode(claims + "=="))["sub"]

    status, assigned = http(
        "POST", f"{API}/api/v1/staff/requests/{request_id}/assign", headers=auth,
        body={"researcher_id": user_id},
    )
    if status != 200:
        print(f"could not assign the request (is this account an admin?): {status} {assigned}")
        return 2

    print(f"\nworking on request {request_id}\n")

    # --- acceptance 3: approval binds to the version that was read ----------
    print("acceptance 3 - a draft that moved cannot be approved")

    body = {
        "question": "[נתוני דמה] שאלה",
        "conclusion": "אין מספיק ראיות מבני אדם כדי להעריך תועלת לשיפור תיאבון בהקשר שנבדק.",
        "certainty": "נמוכה מאוד",
        "certainty_explanation": "[נתוני דמה] מעט מחקרים",
        "safety": "[נתוני דמה] אין מידע מספיק",
        "limitations": "[נתוני דמה] מדגמים קטנים",
        "preclinical": "[נתוני דמה] מכרסמים בלבד",
        "sources": [],
    }
    status, draft = http(
        "POST", f"{API}/api/v1/staff/requests/{request_id}/drafts", headers=auth,
        body={"body": body, "source_ids": []},
    )
    check("a draft can be created", status == 201, f"{status} {draft}")
    if status != 201:
        return 1
    version_id = draft["id"]
    hash_the_reviewer_read = draft["content_hash"]

    edited = dict(body, conclusion=body["conclusion"] + " (נערך)")
    status, saved = http(
        "PATCH", f"{API}/api/v1/staff/drafts/{version_id}", headers=auth,
        body={"body": edited, "source_ids": []},
    )
    check("saving changes the content hash", saved["content_hash"] != hash_the_reviewer_read,
          str(saved))

    all_checked = {
        "checked_sources": True,
        "checked_claim_evidence_alignment": True,
        "checked_limitations": True,
        "checked_user_wording": True,
    }

    status, result = http(
        "POST", f"{API}/api/v1/staff/drafts/{version_id}/approve", headers=auth,
        body={"expected_content_hash": hash_the_reviewer_read, **all_checked},
    )
    check("approving the version that was read, after it changed, is refused",
          status == 409 and result["detail"]["code"] == "draft_changed", f"{status} {result}")

    status, result = http(
        "POST", f"{API}/api/v1/staff/drafts/{version_id}/approve", headers=auth,
        body={
            "expected_content_hash": saved["content_hash"],
            **{**all_checked, "checked_limitations": False},
        },
    )
    check("approving with one confirmation missing is refused",
          status == 400 and result["detail"]["code"] == "checks_incomplete", f"{status} {result}")

    status, result = http(
        "POST", f"{API}/api/v1/staff/drafts/{version_id}/approve", headers=auth,
        body={"expected_content_hash": saved["content_hash"], **all_checked},
    )
    check("approving the current version with every confirmation succeeds",
          status == 200, f"{status} {result}")

    status, response = http("GET", f"{API}/api/v1/requests/{request_id}/response", headers=auth)
    check("the requester now reads the approved text",
          status == 200 and response["body"]["conclusion"].endswith("(נערך)"), f"{status} {response}")

    # --- acceptance 5: a missing provider is not a finding -------------------
    print("\nacceptance 5 - a blocked provider stays a failure")

    status, job = http(
        "POST", f"{API}/api/v1/staff/requests/{request_id}/jobs", headers=auth,
        body={"job_type": "draft"},
    )
    if status == 409:
        print("  (a draft job is already queued for this request; reusing it)")
    else:
        check("a draft job can be enqueued", status == 201, f"{status} {job}")

    blocked = None
    for _ in range(12):
        time.sleep(3)
        _, jobs = http("GET", f"{API}/api/v1/staff/jobs", headers=auth)
        for row in jobs["jobs"]:
            if row["job_type"] == "draft" and row["last_error"]:
                blocked = row
                break
        if blocked:
            break

    check("the blocked job records a structured failure",
          bool(blocked) and blocked["last_error"].get("kind") == "not_configured", str(blocked))
    check("the blocked job is not marked successful",
          bool(blocked) and blocked["state"] != "succeeded", str(blocked and blocked["state"]))

    status, detail = http("GET", f"{API}/api/v1/requests/{request_id}", headers=auth)
    check("the requester sees no fabricated answer from the failure",
          detail["status"] in {"under_review", "response_available"}, str(detail["status"]))

    # --- withdrawal ---------------------------------------------------------
    print("\nwithdrawal")
    status, result = http(
        "POST", f"{API}/api/v1/staff/responses/{version_id}/withdraw", headers=auth,
        body={"reason": "[נתוני דמה] נמשך בבדיקה אוטומטית"},
    )
    check("a published version can be withdrawn with a reason", status == 200, f"{status} {result}")

    status, _ = http("GET", f"{API}/api/v1/requests/{request_id}/response", headers=auth)
    check("withdrawn content stops being readable", status == 404, str(status))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
