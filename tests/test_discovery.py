"""Signup -> onboarding -> automatic Qloo-powered discovery of real Circles and events -> join / RSVP -> targeted refresh.
Qloo is faked deterministically in conftest (jazz -> tag "Blues", chess -> tag "Board Games"); the job queue runs synchronously."""
import json

from backend import circles, db, jobs
from backend.qloo_client import QlooError
from tests.test_circles import account, client, make_circle, profile
from tests.test_platform import event_body, iso, make_org


def onboard(alias, interests, **kw):
    h = account()
    r = client.post("/api/me", json=profile(alias, interests, **kw), headers=h)
    assert r.status_code == 200, r.text
    return h, r.json()


def published_event(h, oid, **kw):
    r = client.post(f"/api/orgs/{oid}/events", json=event_body(**kw), headers=h)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert client.post(f"/api/events/{eid}/publish", headers=h).status_code == 200
    return eid


def disc(h):
    return client.get("/api/agent/discovery", headers=h).json()


def drain():
    for _ in range(4):
        if not jobs.run_pending():
            break


def test_signup_to_personalised_discovery_journey(monkeypatch):
    # --- real data that already exists in the app
    host, hp = onboard("Host", [("Jazz", "teach")])
    cj = make_circle(host, hp, "Jazz").json()["id"]
    org_owner = account()
    org = make_org(org_owner)
    ev_jazz = published_event(org_owner, org["id"], title="Monsoon jazz evening", description="Live jazz trio and open jam.")
    ev_blues = published_event(org_owner, org["id"], title="Blues guitar basics", description="Learn twelve-bar blues.")
    ev_other = published_event(org_owner, org["id"], title="Street dog feeding walk")
    ev_full = published_event(org_owner, org["id"], title="Jazz piano masterclass", capacity=1)
    filler, _ = onboard("Filler", [("Tennis", "enjoy")])
    assert client.post(f"/api/events/{ev_full}/rsvp", json={"status": "going"}, headers=filler).status_code == 200
    drain()

    # --- 1-7: a brand-new user signs up and completes the short onboarding; discovery starts by itself
    h, d = onboard("Asha", [("Jazz", "enjoy")], availability=["weekend"])
    assert d["agent_run"]
    st = disc(h)["status"]
    assert st["state"] == "running" and st["stages"][0]["state"] == "done" and st["stages"][1]["state"] == "done"
    drain()
    res = disc(h)
    st, r = res["status"], res["result"]
    assert st["state"] == "ready"
    assert [s["key"] for s in st["stages"]] == ["account_created", "onboarding_completed", "profile_saved", "qloo_resolution",
                                               "cultural_insights", "circle_matching", "event_matching", "ranking", "recommendations_ready"]
    # real Circle, linked to its record, with join mode and reasons
    assert [c["id"] for c in r["circles"]] == [cj] and r["circles"][0]["join_mode"] == "direct" and r["circles"][0]["link"] == f"#/c/{cj}"
    # real events: declared match, Qloo-linked match (Blues came from Qloo Insights for "Jazz"), full / unrelated excluded
    ids = [e["id"] for e in r["events"]]
    assert ev_jazz in ids and ev_blues in ids and ev_full not in ids and ev_other not in ids
    blues = next(e for e in r["events"] if e["id"] == ev_blues)
    assert any(x["source"] == "qloo" and "Blues" in x["text"] for x in blues["reasons"])
    assert blues["source"] == "Culture Connect event" and blues["address"] and blues["owner"]["name"] == "Paws Pune"
    assert {(t["type"], t["id"]) for t in r["top"]} >= {("circle", cj), ("event", ev_jazz)}
    assert [x["name"] for x in r["discover_new"]] == ["Blues"] and "Jazz" in r["discover_new"][0]["because"]
    with db.read() as c:  # every recommendation is a persisted record
        assert all(c.execute("SELECT 1 FROM events WHERE id = ?", (e["id"],)).fetchone() for e in r["events"])
    notes = client.get("/api/notifications", headers=h).json()["items"]
    assert sum(n["title"].startswith("Your personalised recommendations") for n in notes) == 1

    # --- 9: persisted across "logout/login/refresh": a new session reads the same stored results without re-running
    runs_before = len(client.get("/api/agent/runs", headers=h).json())
    login = client.post("/api/auth/signin", json={"email": client.get("/api/auth/me", headers=h).json()["account"]["email"],
                                                  "password": "Corr3ct-Horse-Battery"}).json()["token"]
    again = disc({"Authorization": f"Bearer {login}"})
    assert again["result"]["run_id"] == r["run_id"] and len(client.get("/api/agent/runs", headers=h).json()) == runs_before

    # --- 8 + 11: join and RSVP through the normal flows; refreshed recommendations reflect it, no duplicates
    assert client.post(f"/api/circles/{cj}/join", headers=h).json()["status"] == "active"
    assert client.post(f"/api/circles/{cj}/join", headers=h).json()["already"] is True
    assert client.post(f"/api/events/{ev_jazz}/rsvp", json={"status": "going"}, headers=h).status_code == 200
    drain()
    r2 = disc(h)["result"]
    assert cj not in [c["id"] for c in r2["circles"]]  # already a member -> not recommended again
    assert next(e for e in r2["events"] if e["id"] == ev_jazz)["my_rsvp"] == "going"
    assert len({e["id"] for e in r2["events"]}) == len(r2["events"])
    assert sum(n["title"].startswith("Your personalised") for n in client.get("/api/notifications", headers=h).json()["items"]) == 1

    # --- dismiss / save feedback re-ranks without new Qloo calls
    assert client.post("/api/agent/feedback", json={"item_type": "event", "item_id": ev_blues, "action": "dismissed"}, headers=h).json()["ok"]
    assert client.post("/api/agent/feedback", json={"item_type": "interest", "item_id": "MADE-UP", "action": "saved"}, headers=h).status_code == 404
    assert client.post("/api/agent/feedback", json={"item_type": "interest", "item_id": "T:blues", "action": "saved"}, headers=h).json()["ok"]
    drain()
    r3 = disc(h)["result"]
    assert ev_blues not in [e["id"] for e in r3["events"]] and r3["discover_new"][0]["saved"] is True
    last = client.get("/api/agent/runs", headers=h).json()[0]
    assert last["trigger"].startswith("you ") and any(s["tool"] == "cultural_insights" and s["status"] == "skipped" for s in last["steps"])

    # --- 7 + 10: a newly published matching event and a cancellation trigger targeted refreshes
    ev_new = published_event(org_owner, org["id"], title="Jazz & poetry night", starts_at=iso(6, 19), ends_at=iso(6, 21), rsvp_deadline=iso(6, 9))
    drain()
    assert ev_new in [e["id"] for e in disc(h)["result"]["events"]]
    client.post(f"/api/events/{ev_new}/cancel", json={"reason": "Venue flooded"}, headers=org_owner)
    drain()
    assert ev_new not in [e["id"] for e in disc(h)["result"]["events"]]
    # interest change -> full refresh with Qloo resolution for the new interest
    body = profile("Asha", [("Jazz", "enjoy"), ("Chess", "learn")], availability=["weekend"])
    assert client.put("/api/me", json=body, headers=h).json()["agent_run"]
    drain()
    full = next(x for x in client.get("/api/agent/runs", headers=h).json() if x["kind"] == "discovery")
    assert full["trigger"] == "preferences changed" and full["status"] == "succeeded"
    assert any(s["tool"] == "cultural_insights" and s["status"] == "ok" for s in full["steps"])  # new Qloo call for the new interest
    assert any(x["name"] == "Board Games" for x in disc(h)["result"]["discover_new"])


def test_empty_results_and_qloo_outage_are_truthful(monkeypatch):
    h, d = onboard("Lone", [("Underwater basket weaving", "enjoy")], area="")
    drain()
    res = disc(h)
    assert res["status"]["state"] == "ready" and res["result"]["top"] == [] and res["result"]["events"] == []
    assert res["result"]["external_events"]["configured"] is False
    assert not [n for n in client.get("/api/notifications", headers=h).json()["items"] if n["kind"] == "agent"]  # nothing to announce

    # Qloo goes down: cached insights are used, the result is marked degraded and a retry is scheduled (not a fake success)
    def down(*a, **k):
        raise QlooError("Qloo HTTP 503", 503)
    monkeypatch.setattr(circles, "taste_profile", down)
    with db.tx() as c:
        c.execute("UPDATE user_taste SET retrieved_at = 0 WHERE user_id = ?", (d["user_id"],))  # force a new Qloo call
    client.post("/api/agent/discovery/refresh", headers=h)
    drain()
    r = disc(h)
    assert r["result"]["degraded"] is True and r["status"]["stages"][4]["state"] == "warning"
    with db.read() as c:
        retry = c.execute("SELECT * FROM agent_runs WHERE dedupe_key = ? AND status = 'queued'", (f"discovery-retry:{d['user_id']}",)).fetchone()
    assert retry and retry["next_run_at"] > jobs.now() + 60 and json.loads(retry["input"])["retry"] == 1


def test_private_full_and_invite_only_circles_are_never_recommended():
    a, ap = onboard("Ann", [("Chess", "teach")])
    make_circle(a, ap, "Chess", visibility="private")
    b, bp = onboard("Ben", [("Chess", "teach")], area="Baner, Pune")
    make_circle(b, bp, "Chess", capacity=3, min_size=2)
    drain()
    h, d = onboard("Cy", [("Chess", "learn")], area="Baner, Pune")
    drain()
    names = [c["name"] for c in disc(h)["result"]["circles"]]
    assert names == ["Chess Circle"]  # the public one only; the private one is never exposed
    assert disc(h)["result"]["circles"][0]["area"] == "Baner, Pune"
