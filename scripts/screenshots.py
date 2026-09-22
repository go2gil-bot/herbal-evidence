"""Regenerate docs/screenshots from the running dev site.

    backend/.venv/Scripts/python scripts/screenshots.py

Uses the Edge already installed on the machine (`channel="msedge"`), so nothing
downloads a browser. Sign-in happens through `admin/generate_link`, which
returns the link instead of emailing it - the tokens never leave this process,
and the mock accounts they belong to hold nothing real.

Points at **dev on purpose**. Production is verifiably empty (acceptance
criterion 12) and screenshots of empty lists would show nothing; dev carries
the mock data, and its banner says so in every image.
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

REPO = pathlib.Path(__file__).resolve().parents[1]
ENV_PATH = REPO / "supabase" / ".env"
OUT = REPO / "docs" / "screenshots"
SITE = "https://frontend-dev-62e0.up.railway.app"

# Mock accounts in the dev project. The first owns a published response, the
# second holds the researcher and admin roles.
REQUESTER = "reuse-a-9a4ee62b@example.test"
STAFF = "demo-dev@example.test"

DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 375, "height": 812}

# Elements worth a shot of their own, because the page around them is long
# enough that capping the top would cut exactly the part that matters.
ELEMENTS = {
    "07b-four-confirmations.png": ".approve-box",
}

# (file name, path, viewport, who is signed in)
SHOTS = [
    ("01-landing.png", "/index.html", DESKTOP, None),
    ("02-sign-in.png", "/auth.html", DESKTOP, None),
    ("03-new-request.png", "/new-request.html", DESKTOP, "requester"),
    ("04-my-requests.png", "/dashboard.html", DESKTOP, "requester"),
    ("05-published-response.png", "/request.html?id=1017", DESKTOP, "requester"),
    ("06-researcher-queue.png", "/staff.html", DESKTOP, "staff"),
    ("07-review-and-approve.png", "/review.html?version=15", DESKTOP, "staff"),
    ("07b-four-confirmations.png", "/review.html?version=15", DESKTOP, "staff"),
    ("08-mobile-landing.png", "/index.html", PHONE, None),
    ("09-mobile-new-request.png", "/new-request.html", PHONE, "requester"),
]


def env() -> dict[str, str]:
    values = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def sign_in_link(url: str, service_key: str, email: str) -> str:
    body = {"type": "magiclink", "email": email, "redirect_to": f"{SITE}/auth.html"}
    request = urllib.request.Request(
        f"{url}/auth/v1/admin/generate_link", data=json.dumps(body).encode(), method="POST"
    )
    request.add_header("apikey", service_key)
    request.add_header("Authorization", f"Bearer {service_key}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["action_link"]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright  (the Edge on this machine is used, nothing downloads)")
        return 2

    values = env()
    url = values.get("DEV_SUPABASE_URL")
    service = values.get("DEV_SUPABASE_SERVICE_ROLE_KEY")
    if not (url and service):
        print("missing supabase/.env values")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    accounts = {"requester": REQUESTER, "staff": STAFF}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        try:
            # One context per (role, viewport). A magic link is single use, so
            # signing in once per shot burns the link and every shot after the
            # first silently captures the sign-in page instead - which is what
            # happened the first time this ran, and is invisible in the output
            # unless you compare file sizes.
            for key in dict.fromkeys((who, tuple(sorted(vp.items()))) for _, _, vp, who in SHOTS):
                who, viewport_items = key
                viewport = dict(viewport_items)
                context = browser.new_context(viewport=viewport, locale="he-IL")
                page = context.new_page()

                if who:
                    # Following the link is what signs the session in, exactly as
                    # it does for a person clicking one in their inbox.
                    page.goto(sign_in_link(url, service, accounts[who]), wait_until="networkidle")
                    session = page.evaluate("localStorage.getItem('he.session')")
                    if not session:
                        print(f"  sign-in failed for {who}; refusing to save a login page")
                        return 1

                for name, path, shot_viewport, shot_who in SHOTS:
                    if shot_who != who or shot_viewport != viewport:
                        continue
                    page.goto(SITE + path, wait_until="networkidle")
                    # Give the page its data before capturing an empty shell.
                    page.wait_for_timeout(1500)

                    selector = ELEMENTS.get(name)
                    if selector:
                        element = page.query_selector(selector)
                        if element is None:
                            print(f"  {selector} not found for {name}")
                            return 1
                        element.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                        element.screenshot(path=str(OUT / name))
                        print(f"  {name}  ({selector})")
                        continue

                    # Full page, but capped. The review editor lists every source
                    # behind the draft and runs to ~12,000px; unclipped it is a
                    # ribbon of citations with the four confirmations lost at the
                    # bottom, which is the opposite of what it should show.
                    height = page.evaluate("document.documentElement.scrollHeight")
                    cap = viewport["height"] * 3
                    if height > cap:
                        page.screenshot(
                            path=str(OUT / name),
                            clip={"x": 0, "y": 0, "width": viewport["width"], "height": cap},
                        )
                    else:
                        page.screenshot(path=str(OUT / name), full_page=True)
                    print(f"  {name}  ({height}px{' capped' if height > cap else ''})")

                context.close()
        finally:
            browser.close()

    print(f"\n{len(SHOTS)} screenshots in {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
