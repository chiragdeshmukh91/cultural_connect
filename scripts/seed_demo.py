"""Create the two dedicated demo accounts used in the judge-testing guide, through the app's own public API.

    python scripts/seed_demo.py --base https://YOUR-APP-URL --password "<a strong demo password>"

What it creates (all through normal API calls, so every rule, permission and Qloo check applies):
  * Chirag (organiser / Circle host): profile + organisation "The Culture Collective" + public Circle
    "Pune Culture Explorers" + three published demo activities.
  * Sanika (member): profile with cultural interests; she does NOT join or RSVP, so judges can do that live.

Honesty rules this script follows:
  * Interest signals are only IDs that the live Qloo API returns for each label (/api/interests/resolve);
    the server re-verifies them. If Qloo is unreachable the script stops instead of saving fake IDs.
  * The demo activities are clearly marked as demo activities. No venue or address is invented:
    the location is "to be confirmed" and the description says so.
  * Credentials are never written to disk or printed; pass them on the command line or via env vars.
Re-running is safe: existing accounts are signed in instead of re-created and existing records are reused.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

import requests

CHIRAG = {"alias": "Chirag", "area": "Pune", "interests": [("Jazz", "teach"), ("Poetry", "discuss"), ("Street food", "enjoy")]}
SANIKA = {"alias": "Sanika", "area": "Pune", "interests": [("Jazz", "enjoy"), ("Poetry", "learn"), ("Books", "enjoy"), ("Photography", "enjoy")]}
ORG = {"name": "The Culture Collective", "category": "Arts & culture", "service_area": "Pune",
       "description": "Demo organisation created for Qloo Agentic Hackathon judging: music, poetry and food-culture meetups in Pune."}
CIRCLE = {"name": "Pune Culture Explorers", "purpose": "Live music, poetry and food culture with people nearby (demo Circle for judging).",
          "topic": "Jazz"}
ACTIVITIES = [  # (title, category, days from now, start hour, description)
    ("Jazz & Coffee Evening", "Music", 7, 18, "An informal evening of jazz listening and conversation."),
    ("Poetry & Open Mic", "Arts & culture", 10, 17, "Read a poem you love or one you wrote; listeners welcome."),
    ("Pune Food & Culture Walk", "Food", 14, 8, "A morning walk to talk about the food and stories of the city."),
]
DEMO_NOTE = ("\n\nDemo activity created for hackathon judging. Venue to be confirmed by the organiser; "
             "no real booking exists.")


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.h: dict = {}

    def call(self, method: str, path: str, body=None, ok=(200,)):
        r = requests.request(method, self.base + path, json=body, headers=self.h, timeout=90)
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def login(self, email: str, pw: str):
        r = requests.post(self.base + "/api/auth/signup", json={"email": email, "password": pw}, timeout=60)
        if r.status_code != 200:
            r = requests.post(self.base + "/api/auth/signin", json={"email": email, "password": pw}, timeout=60)
        if r.status_code != 200:
            raise SystemExit(f"Could not sign up or sign in {email}: HTTP {r.status_code} {r.text[:200]}")
        self.h = {"Authorization": "Bearer " + r.json()["token"]}


def resolve(api: Api, label: str) -> list[dict]:
    """IDs that live Qloo returned for this label (the server's own suggestions); empty if Qloo found nothing."""
    out = api.call("POST", "/api/interests/resolve", {"label": label})
    if out.get("warnings") and not out.get("candidates"):
        raise SystemExit(f"Qloo did not answer for '{label}': {out['warnings']}. Check QLOO_API_KEY on the server.")
    by_id = {c["id"]: c for c in out.get("candidates", [])}
    return [{"id": i, "kind": by_id[i]["kind"]} for i in out.get("suggested_ids", []) if i in by_id][:4]


def ensure_profile(api: Api, person: dict) -> dict:
    body = {"alias": person["alias"], "area": person["area"], "adult_confirmed": True, "discoverable": True,
            "share_interests": True, "show_area": True, "availability": ["weekday_evening", "weekend"],
            "timezone": "Asia/Kolkata",
            "interests": [{"label": l, "intent": i, "signals": resolve(api, l)} for l, i in person["interests"]]}
    existing = requests.get(api.base + "/api/me", headers=api.h, timeout=30)
    method = "PUT" if existing.status_code == 200 else "POST"
    return api.call(method, "/api/me", body)


def iso(days: int, hour: int) -> str:
    d = (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return d.isoformat(timespec="minutes")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.getenv("DEMO_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--chirag-email", default=os.getenv("DEMO_CHIRAG_EMAIL", "chirag.demo@cultureconnect.example"))
    ap.add_argument("--sanika-email", default=os.getenv("DEMO_SANIKA_EMAIL", "sanika.demo@cultureconnect.example"))
    ap.add_argument("--password", default=os.getenv("DEMO_PASSWORD"), help="shared password for both demo accounts")
    a = ap.parse_args()
    if not a.password:
        sys.exit("Pass --password or set DEMO_PASSWORD (min. 10 characters, not a dictionary word).")

    host = Api(a.base)
    host.login(a.chirag_email, a.password)
    prof = ensure_profile(host, CHIRAG)
    print("Chirag profile saved:", [(i["label"], len(i["signals"])) for i in prof["profile"]["interests"]], "Qloo signals per interest")

    me = host.call("GET", "/api/auth/me")
    org = next((o for o in me.get("orgs", []) if o.get("name") == ORG["name"]), None)
    if not org:
        org = host.call("POST", "/api/orgs", ORG)
    print("Organisation:", org.get("name"), org.get("id"))

    mine = host.call("GET", "/api/me/circles")
    rows = mine if isinstance(mine, list) else mine.get("circles", mine.get("items", []))
    circle = next((c for c in rows if c.get("name") == CIRCLE["name"]), None)
    if not circle:
        iid = next(i["id"] for i in prof["profile"]["interests"] if i["label"] == CIRCLE["topic"])
        circle = host.call("POST", "/api/circles", {"interest_id": iid, "name": CIRCLE["name"], "purpose": CIRCLE["purpose"],
                                                    "meeting_mode": "in_person", "area": "Pune", "capacity": 20, "min_size": 3,
                                                    "visibility": "public"})
    print("Circle:", circle.get("name"), circle.get("id"))

    existing = {e["title"] for e in host.call("GET", "/api/events")}
    for title, cat, days, hour, desc in ACTIVITIES:
        if title in existing:
            print("Activity exists:", title)
            continue
        ev = host.call("POST", f"/api/orgs/{org['id']}/events", {
            "title": title, "description": desc + DEMO_NOTE, "category": cat, "starts_at": iso(days, hour),
            "ends_at": iso(days, hour + 2), "timezone": "Asia/Kolkata", "location_status": "tbc", "capacity": 20,
            "rsvp_deadline": iso(days - 1, 20), "cost_note": "Free (demo)"})
        host.call("POST", f"/api/events/{ev['id']}/publish")
        print("Published demo activity:", title)

    member = Api(a.base)
    member.login(a.sanika_email, a.password)
    sp = ensure_profile(member, SANIKA)
    print("Sanika profile saved:", [(i["label"], len(i["signals"])) for i in sp["profile"]["interests"]], "Qloo signals per interest")
    print("Done. Sign in as Sanika and open Discover; personalised discovery runs in the background.")


if __name__ == "__main__":
    main()
