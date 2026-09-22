"""The submission limit, tested where it actually has to hold.

`authenticated` holds a direct insert grant on `requests`, so the interesting
question is not whether FastAPI refuses - it is whether the database does when
somebody skips FastAPI entirely. Every insert here goes straight to PostgREST
with a real user's token, which is the bypass the limit exists to close.

    python supabase/tests/rate_limit.py

Never point this at Production.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"

# Mirrors private.enforce_request_rate_limit. If the migration changes, this
# fails loudly rather than quietly testing the wrong numbers.
PER_HOUR = 5
PER_DAY = 20

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

    users = {}
    for label in ("a", "b"):
        email = f"ratelimit-{label}-{suffix}@example.test"
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

    def submit(user: dict) -> int:
        status, _ = http(
            "POST", f"{rest}/requests?select=id", key=anon, token=user["token"],
            prefer="return=representation",
            body={"owner_id": user["id"], "herb_input": f"[rate test {suffix}] כורכום",
                  "preparation_input": "תה"},
        )
        return status

    print("the hourly window, posted straight to PostgREST")

    accepted = [submit(a) for _ in range(PER_HOUR)]
    check(f"the first {PER_HOUR} submissions are accepted",
          accepted == [201] * PER_HOUR, str(accepted))

    over = submit(a)
    check("the next one is refused with 429", over == 429, str(over))
    check("it stays refused", submit(a) == 429)

    # A shared counter would be a denial of service against everybody else.
    check("a different person is unaffected", submit(b) == 201)

    print("\nthe daily window")

    # Backdate rows past the hourly window so the daily one is what answers.
    # Service role, because only staff-side code may set created_at.
    now = dt.datetime.now(dt.timezone.utc)
    backdated = [
        {"owner_id": b["id"], "herb_input": f"[rate test {suffix}] backdated",
         "created_at": (now - dt.timedelta(hours=2 + (i % 20))).isoformat()}
        for i in range(PER_DAY - 2)
    ]
    status, _ = http("POST", f"{rest}/requests?select=id", key=service,
                     prefer="return=representation", body=backdated)
    if status >= 300:
        print(f"  could not seed backdated rows: {status}")
        return 2

    # b now has PER_DAY - 1 rows: one from a moment ago, the rest hours old.
    check(f"submission number {PER_DAY} is accepted", submit(b) == 201)
    check(f"submission number {PER_DAY + 1} is refused", submit(b) == 429)

    # The hourly window is nowhere near full for b, so this can only be the
    # daily limit answering.
    status, rows = http(
        "GET", f"{rest}/requests?select=id&owner_id=eq.{b['id']}"
               f"&created_at=gt.{(now - dt.timedelta(hours=1)).isoformat()}", key=service)
    check("and the hourly window was not the one that refused",
          len(rows or []) < PER_HOUR, f"{len(rows or [])} in the last hour")

    for user in users.values():
        http("DELETE", f"{rest}/requests?owner_id=eq.{user['id']}", key=service)
        http("DELETE", f"{auth_url}/admin/users/{user['id']}", key=service)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
