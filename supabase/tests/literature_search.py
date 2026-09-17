"""The literature and AI pipeline, end to end, against the live providers.

Enqueues a real search through the job queue and checks what landed: a
`search_runs` row per provider, sources labelled from curated metadata, and then
either a validated draft (when an AI provider is configured) or a recorded
`not_configured` failure with nothing invented (when it is not).

    python supabase/tests/literature_search.py

Hits PubMed, Europe PMC and the AI provider for real, so it is slow and it can
fail because a provider is down. That is the point - it tests the integration,
not a mock. Never point it at Production.
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

ALLOWED_CERTAINTY = {"גבוהה", "בינונית", "נמוכה", "נמוכה מאוד", "לא ניתן להעריך"}

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
        with urllib.request.urlopen(req, timeout=180) as response:
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


def report() -> int:
    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


def wait_for_job(auth: dict, job_id: int, *, seconds: int = 120) -> dict | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(4)
        _, data = http("GET", f"{API}/api/v1/staff/jobs", headers=auth)
        for job in data["jobs"]:
            if job["id"] != job_id:
                continue
            if job["state"] in {"succeeded", "failed", "dead"}:
                return job
            if job["state"] == "queued" and job["attempts"] > 0:
                return job  # failed once and is waiting to retry
    return None


def main() -> int:
    values = env()
    supabase_url, anon = values.get("DEV_SUPABASE_URL"), values.get("DEV_SUPABASE_ANON_KEY")
    if not (supabase_url and anon):
        print("missing supabase/.env values")
        return 2

    status, session = http(
        "POST", f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon, "Content-Type": "application/json"},
        body={"email": EMAIL, "password": PASSWORD},
    )
    if status >= 300:
        print(f"could not sign in: {status} {session}")
        return 2
    auth = {"Authorization": f"Bearer {session['access_token']}", "Content-Type": "application/json"}
    user_id = json.loads(base64.urlsafe_b64decode(session["access_token"].split(".")[1] + "=="))["sub"]

    status, submitted = http(
        "POST", f"{API}/api/v1/requests", headers=auth,
        body={"herb_input": "כורכום", "preparation_input": "תה"},
    )
    if status != 201:
        print(f"could not submit: {status} {submitted}")
        return 2
    request_id = submitted["id"]
    check("the herb resolved from the catalogue",
          submitted["identification_state"] == "resolved", str(submitted))

    http("POST", f"{API}/api/v1/staff/requests/{request_id}/assign", headers=auth,
         body={"researcher_id": user_id})

    print(f"\nrequest {request_id}\n")
    print("literature search")

    status, job = http(
        "POST", f"{API}/api/v1/staff/requests/{request_id}/jobs", headers=auth,
        body={"job_type": "literature_search"},
    )
    check("the search job is queued", status == 201, f"{status} {job}")
    if status != 201:
        return report()

    finished = wait_for_job(auth, job["id"])
    check("the search job finished",
          finished is not None and finished["state"] == "succeeded", str(finished))

    _, data = http("GET", f"{API}/api/v1/staff/jobs", headers=auth)
    runs = [r for r in data["search_runs"] if r["research_job_id"] == job["id"]]
    providers = {r["provider"] for r in runs}

    check("both providers recorded a run", providers == {"pubmed", "europepmc"}, str(providers))
    check("a successful run carries a result count",
          all(r["result_count"] is not None for r in runs if r["status"] == "succeeded"), str(runs))
    check("a failed run carries its error",
          all(r["error"] for r in runs if r["status"] == "failed"), str(runs))

    print("\nwhat was stored")
    _, sources = http("GET", f"{API}/api/v1/staff/sources?limit=100", headers=auth)
    items = sources["items"]
    known_source_ids = {str(s["id"]) for s in items}

    check("sources were stored", len(items) > 0, str(len(items)))
    check("records are labelled by evidence type",
          {i["evidence_type"] for i in items} <= {"human", "animal", "in_vitro", "review", "other"}, "")
    check("at least one label came from curated metadata",
          any(i["evidence_type"] in {"human", "animal", "review"} for i in items), "")
    check("access level is recorded per source",
          {i["access_level"] for i in items} <= {"full_text", "abstract_only", "not_accessed"}, "")
    check("identifiers are real, not invented",
          all(i["id_kind"] in {"pmid", "doi", "pmcid", "manual"} and i["external_id"] for i in items), "")

    indirect = [i for i in items if i["is_oncology"] is False]
    print(f"  ({len(indirect)} of {len(items)} records are indexed outside oncology - indirect evidence)")

    print("\nthe AI step")
    _, ready = http("GET", f"{API}/ready", headers=auth)
    configured = (
        ready["checks"].get("ai_api_key") == "set" and ready["checks"].get("ai_model") != "missing"
    )
    print(f"  provider configured: {configured}")

    status, draft_job = http(
        "POST", f"{API}/api/v1/staff/requests/{request_id}/jobs", headers=auth,
        body={"job_type": "draft"},
    )
    if status != 201:
        print(f"  (draft job not queued: {status} {draft_job})")
        return report()

    finished = wait_for_job(auth, draft_job["id"], seconds=240)

    if not configured:
        check("without a provider the job records not_configured",
              finished is not None
              and (finished.get("last_error") or {}).get("kind") == "not_configured",
              str(finished))
        _, detail = http("GET", f"{API}/api/v1/staff/requests/{request_id}", headers=auth)
        check("and nothing was invented", len(detail["versions"]) == 0, str(detail["versions"]))
        return report()

    check("the draft job succeeded",
          finished is not None and finished["state"] == "succeeded", str(finished))

    _, detail = http("GET", f"{API}/api/v1/staff/requests/{request_id}", headers=auth)
    versions = detail["versions"]
    check("a draft version exists", len(versions) == 1, str(versions))
    if not versions:
        return report()

    version = versions[0]
    check("the draft records which model produced it",
          all([version["ai_provider"], version["ai_model"], version["prompt_version"]]), str(version))
    check("it is a draft, not published", version["state"] == "draft", version["state"])

    _, draft = http("GET", f"{API}/api/v1/staff/drafts/{version['id']}", headers=auth)
    body = draft["body"]
    text = " ".join(str(value) for value in body.values())

    check("certainty is one of the allowed words", body["certainty"] in ALLOWED_CERTAINTY,
          body["certainty"])
    check("no numeric score anywhere", "/10" not in text and "מתוך 10" not in text, "")
    check("the rating is not called GRADE", "GRADE" not in text.upper(), "")
    check("PRISMA is not claimed", "PRISMA" not in text.upper(), "")

    cited = {claim["source_id"] for claim in body.get("claims", [])}
    check("every claim cites a source that exists", cited <= known_source_ids,
          f"cited {sorted(cited - known_source_ids)} which do not exist")
    check("every claim names where it is supported",
          all(claim.get("support_location") for claim in body.get("claims", [])), "")

    status_user, _ = http("GET", f"{API}/api/v1/requests/{request_id}/response", headers=auth)
    check("the requester cannot read the draft as a response", status_user == 404, str(status_user))

    print(f"\n  certainty:  {body['certainty']}")
    print(f"  conclusion: {body['conclusion'][:160]}")
    return report()


if __name__ == "__main__":
    sys.exit(main())
