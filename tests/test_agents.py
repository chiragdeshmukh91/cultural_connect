"""Autonomous workflow: onboarding -> Qloo discovery -> Circle formation -> event planning -> votes -> approval -> RSVP
-> reminders -> completion -> feedback. Qloo is faked deterministically (conftest); the job queue runs synchronously."""
import json
from datetime import datetime, timedelta

from backend import agents, circles, db, jobs, planner
from backend.qloo_client import QlooError
from tests.conftest import fake_anchors
from tests.test_circles import account, client, make_circle, profile


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def onboard(alias, interests, resolved=True, **kw):
    h = account()
    body = profile(alias, interests, **kw)
    if not resolved:
        for it in body["interests"]:
            it["signals"] = []
    r = client.post("/api/me", json=body, headers=h)
    assert r.status_code == 200, r.text
    return h, r.json()


def runs(kind=None, status=None):
    q, a = "SELECT * FROM agent_runs WHERE 1=1", []
    if kind:
        q, a = q + " AND kind = ?", a + [kind]
    if status:
        q, a = q + " AND status = ?", a + [status]
    with db.read() as c:
        return c.execute(q + " ORDER BY created_at", a).fetchall()


def notes(uid, kind=None):
    with db.read() as c:
        q = "SELECT * FROM notifications WHERE user_id = ?" + (" AND kind = ?" if kind else "")
        return c.execute(q, (uid, kind) if kind else (uid,)).fetchall()


def test_onboarding_triggers_real_qloo_discovery_without_manual_search():
    h, d = onboard("Asha", [("Jazz", "enjoy")], resolved=False)
    assert d["agent_run"]  # queued by onboarding itself
    assert jobs.run_pending() >= 1
    r = runs("discovery")[0]
    assert r["status"] == "succeeded", r["error"]
    me = client.get("/api/me", headers=h).json()
    sig = me["interests"][0]["signals"]
    assert [s["id"] for s in sig] == ["T:jazz"] and "auto-resolved by discovery agent" in sig[0]["source"]
    res = client.get("/api/agent/discovery", headers=h).json()["result"]
    assert [t["name"] for t in res["discover_new"]] == ["Blues"]  # came from the (faked) Qloo Insights response
    run = client.get(f"/api/agent/runs/{r['id']}", headers=h).json()
    tools = [s["tool"] for s in run["steps"]]
    assert tools[:3] == ["profile_saved", "qloo_resolution", "cultural_insights"]
    assert any(src["type"] == "qloo" for s in run["steps"] for src in s["sources"])
    # no notification here: nothing matched yet (notifications only announce new, real recommendations)


def test_qloo_insights_change_which_circle_is_recommended():
    h1, p1 = onboard("Host", [("Board Games", "enjoy")])
    assert make_circle(h1, p1, "Board Games").status_code == 200
    jobs.run_pending()
    h2, p2 = onboard("Ravi", [("Chess", "learn")])  # fake Qloo Insights: chess -> tag "Board Games"
    jobs.run_pending()
    recs = client.get("/api/agent/discovery", headers=h2).json()["result"]["recommendations"]
    assert recs and recs[0]["name"] == "Board Games Circle"
    assert any(x["source"] == "qloo" for x in recs[0]["reasons"])


def test_full_autonomous_flow_with_dedupe(monkeypatch):
    av = {"availability": ["weekend"]}
    hs = [onboard(n, [("Pottery", "learn" if n != "Cy" else "teach")], **av) for n in ("Ann", "Ben", "Cy")]
    for _ in range(2):
        jobs.run_pending()
    with db.read() as c:
        props = c.execute("SELECT * FROM circle_proposals").fetchall()
    assert len(props) == 1 and props[0]["status"] == "open"
    invites = client.get("/api/agent/invites", headers=hs[0][0]).json()
    assert invites[0]["my_status"] == "invited" and invites[0]["counts"]["eligible"] == 3
    assert "user_id" not in json.dumps(invites)  # no other member's identity is exposed

    # repeated triggers: no duplicate proposal, no duplicate invitation
    for h, d in hs:
        agents.on_profile_saved(d["user_id"], "test retrigger", force=True)
    jobs.run_pending()
    jobs.run_pending()
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM circle_proposals").fetchone()[0] == 1
    for h, d in hs:
        assert len([n for n in notes(d["user_id"]) if n["title"].startswith("You're invited")]) == 1

    # nobody is enrolled without accepting; the Circle forms when enough people accept
    for i, (h, d) in enumerate(hs):
        v = client.post(f"/api/agent/invites/{props[0]['id']}/accept", headers=h).json()
    assert v["status"] == "formed" and v["circle_id"]
    cid = v["circle_id"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (cid,)).fetchone()[0] == 3
    assert runs("event_planning")  # Circle activation triggered planning automatically
    jobs.run_pending()
    pr = runs("event_planning")[0]
    assert pr["status"] == "succeeded", pr["error"]
    ev = client.get(f"/api/circles/{cid}/events", headers=hs[0][0]).json()[0]
    assert ev["source"] == "agent" and ev["status"] == "proposed" and len(ev["time_options"]) == 3
    # scheduling used stated availability: every option is on a weekend
    assert all(datetime.fromisoformat(t).weekday() >= 5 for t in ev["time_options"])
    assert all(any("3 of 3" in k["note"] for k in con["checks"] if k["check"].startswith("Time option")) for con in ev["plan"]["concepts"])
    assert "Meeting place not resolved" in ev["plan"]["concepts"][0]["unresolved_questions"][0]  # fake Qloo returned no venues
    # a second trigger cannot create a duplicate draft
    assert agents.on_membership_changed(cid, "again", force=True) is None

    # votes persist; when everyone has voted, the coordinator tallies and asks the host to approve (policy: host)
    for h, d in hs:
        client.post(f"/api/circle-events/{ev['id']}/vote", json={"kind": "activity", "choice": 0}, headers=h)
        client.post(f"/api/circle-events/{ev['id']}/vote", json={"kind": "time", "choice": 1}, headers=h)
    jobs.run_pending()
    co = runs("coordinate_proposal")[0]
    assert co["status"] == "succeeded", co["error"]
    host = [x for x in hs if client.get("/api/agent/approvals", headers=x[0]).json()[0]["can_approve"]]
    assert len(host) == 1
    appr = client.get("/api/agent/approvals", headers=host[0][0]).json()[0]
    assert appr["selection"]["time_index"] == 1 and appr["stage"] == "awaiting_approval"
    other = next(x for x in hs if x is not host[0])
    assert client.post(f"/api/agent/approvals/{ev['id']}/approve", json={}, headers=other[0]).status_code == 403
    done = client.post(f"/api/agent/approvals/{ev['id']}/approve", json={"timezone": "UTC"}, headers=host[0][0]).json()
    assert done["status"] == "confirmed" and done["event_id"]
    eid = done["event_id"]
    for h, d in hs:
        assert client.post(f"/api/events/{eid}/rsvp", json={"status": "going"}, headers=h).status_code == 200
    assert client.get(f"/api/events/{eid}", headers=hs[0][0]).json()["going"] == 3

    # reminders and completion run once, however often the sweep runs
    start = datetime.utcnow() + timedelta(hours=5)  # the event was approved in UTC
    with db.tx() as c:
        c.execute("UPDATE events SET starts_at = ?, ends_at = ? WHERE id = ?",
                  (start.isoformat(timespec="minutes"), (start + timedelta(hours=1)).isoformat(timespec="minutes"), eid))
    assert agents.sweep()["remind24"] == 1 and agents.sweep()["remind24"] == 0
    jobs.run_pending()
    assert all(len(notes(d["user_id"], "event_reminder")) == 1 for h, d in hs)
    past = datetime.utcnow() - timedelta(hours=3)
    with db.tx() as c:
        c.execute("UPDATE events SET starts_at = ?, ends_at = ? WHERE id = ?",
                  (past.isoformat(timespec="minutes"), (past + timedelta(hours=1)).isoformat(timespec="minutes"), eid))
    assert agents.sweep()["complete"] == 1
    jobs.run_pending()
    assert client.get(f"/api/events/{eid}", headers=hs[0][0]).json()["status"] == "completed"
    assert all(len(notes(d["user_id"], "feedback")) == 1 for h, d in hs)
    # feedback becomes a planning input: two low ratings exclude that format next time
    for h, d in hs[:2]:
        assert client.post(f"/api/events/{eid}/feedback", json={"rating": 1, "comment": "not for us"}, headers=h).status_code == 200
    with db.read() as c:
        fb = agents._feedback_inputs(c, cid)
    assert fb["excluded_formats"]


def test_venue_validation_and_qloo_failure_never_fabricate(monkeypatch):
    def anchors_with_places(members, location, discovery_types=None, take=5):
        out = fake_anchors(members, location)
        out["venues"] = [
            {"kind": "entity", "id": "V1", "name": "Real Clay Studio", "type": "urn:entity:place", "address": "5 Lane, Kothrud, Pune",
             "lat": 18.5, "lon": 73.8, "hours": {"Saturday": [{"opens": "T10:00", "closes": "T20:00"}]}, "is_closed": False},
            {"kind": "entity", "id": "V2", "name": "No Pin Cafe", "type": "urn:entity:place", "address": "Somewhere Rd", "lat": None, "lon": None},
            {"kind": "entity", "id": "V3", "name": "Gone Gallery", "type": "urn:entity:place", "address": "1 Old St", "lat": 1.0, "lon": 1.0, "is_closed": True},
        ]
        return out
    monkeypatch.setattr(planner, "group_anchors", anchors_with_places)
    hs = [onboard(n, [("Clay", "enjoy")], availability=["weekend"]) for n in ("Ann", "Ben", "Cy")]
    jobs.run_pending()
    jobs.run_pending()
    with db.read() as c:
        pid = c.execute("SELECT id FROM circle_proposals").fetchone()["id"]
    for h, d in hs:
        client.post(f"/api/agent/invites/{pid}/accept", headers=h)
    jobs.run_pending()
    with db.read() as c:
        places = c.execute("SELECT * FROM place_candidates").fetchall()
    names = {p["name"]: json.loads(p["validation"]) for p in places}
    assert "Gone Gallery" not in names  # closed per Qloo -> rejected
    assert names["Real Clay Studio"]["status"] == "verified" and names["No Pin Cafe"]["status"] == "partial"
    assert "capacity_and_booking" in names["Real Clay Studio"]["unresolved"]  # booking is never claimed
    assert all(p["geo_source"] in ("qloo", "") for p in places)

    # Qloo outage: discovery completes honestly with a warning, no invented taste data
    def boom(*a, **k):
        raise QlooError("Qloo HTTP 503", 503)
    monkeypatch.setattr(circles, "taste_profile", boom)
    h, d = onboard("Dee", [("Origami", "enjoy")])
    jobs.run_pending()
    r = [x for x in runs("discovery") if x["user_id"] == d["user_id"]][0]
    assert r["status"] == "succeeded"
    run = client.get(f"/api/agent/runs/{r['id']}", headers=h).json()
    ins = next(s for s in run["steps"] if s["tool"] == "cultural_insights")
    assert ins["status"] == "warn" and "unavailable" in ins["message"] and "degraded" in ins["message"]
    res = client.get("/api/agent/discovery", headers=h).json()["result"]
    assert res["qloo"]["tags"] == [] and res["qloo"]["entities"] == []


def test_runs_resume_after_restart_and_permissions():
    h, d = onboard("Asha", [("Chess", "enjoy")])
    other, _ = onboard("Bo", [("Tennis", "enjoy")])
    r = jobs._claim()  # a worker claims the discovery run ...
    while r and r["user_id"] != d["user_id"]:
        jobs.run_one(r)
        r = jobs._claim()
    ctx = jobs.Ctx(r)
    ctx.step("consent", "check_consent", lambda: {"result": True, "message": "done before crash"})
    with db.tx() as c:  # ... and the server dies mid-run (lease expires)
        c.execute("UPDATE agent_runs SET locked_at = ? WHERE id = ?", (jobs.now() - jobs.LEASE_SECONDS - 5, r["id"]))
    jobs.run_pending()
    with db.read() as c:
        row = c.execute("SELECT * FROM agent_runs WHERE id = ?", (r["id"],)).fetchone()
        n = c.execute("SELECT COUNT(*) FROM agent_steps WHERE run_id = ? AND name = 'consent'", (r["id"],)).fetchone()[0]
    assert row["status"] == "succeeded" and n == 1 and row["attempts"] == 2  # resumed; completed step not repeated
    assert client.get(f"/api/agent/runs/{r['id']}", headers=other).status_code == 404
    assert client.post(f"/api/agent/runs/{r['id']}/retry", headers=other).status_code == 404


def test_opt_out_pause_and_consent():
    h, d = onboard("Asha", [("Chess", "enjoy")])
    jobs.run_pending()
    client.put("/api/agent/settings", json={"automation": False}, headers=h)
    assert agents.on_profile_saved(d["user_id"]) is None  # paused: nothing automatic
    h2, d2 = onboard("Bo", [("Chess", "enjoy")])
    client.put("/api/agent/settings", json={"automation": True, "circle_invites": False}, headers=h2)
    with db.read() as c:
        people, _ = agents.find_candidates(c, d["user_id"], {"label": "Chess", "signals": [{"id": "T:chess"}], "mode": "either",
                                                              "area": "Kothrud, Pune", "area_key": "kothrud pune"})
    assert [p["user_id"] for p in people] == [d["user_id"]]  # Bo opted out of invites
    h3, d3 = onboard("Cy", [("Chess", "enjoy")], discoverable=False)
    assert d3["agent_run"] is None  # no consent -> no discovery


def test_auto_policy_publishes_but_never_claims_booking(monkeypatch):
    hs = [onboard(n, [("Kites", "enjoy")]) for n in ("Ann", "Ben", "Cy")]
    jobs.run_pending()
    jobs.run_pending()
    with db.read() as c:
        pid = c.execute("SELECT id FROM circle_proposals").fetchone()["id"]
    for h, d in hs:
        v = client.post(f"/api/agent/invites/{pid}/accept", headers=h).json()
    cid = v["circle_id"]
    host = next(x for x in hs if client.get("/api/agent/summary", headers=x[0]).json()["moderated_circles"])
    assert client.put(f"/api/agent/circles/{cid}/settings", json={"approval_policy": "auto"}, headers=host[0]).json()["approval_policy"] == "auto"
    jobs.run_pending()
    with db.tx() as c:
        e = c.execute("SELECT id FROM circle_events WHERE circle_id = ?", (cid,)).fetchone()
        c.execute("UPDATE circle_events SET vote_deadline = ? WHERE id = ?", (jobs.now() - 1, e["id"]))
    assert agents.sweep()["tally"] == 1
    jobs.run_pending()
    with db.read() as c:
        ev = c.execute("SELECT * FROM events WHERE circle_id = ?", (cid,)).fetchone()
        upd = c.execute("SELECT message FROM event_updates WHERE event_id = ?", (ev["id"],)).fetchone()["message"]
    assert ev["status"] == "published" and ev["location_status"] in ("tbc", "online") and "nothing is booked" in upd


def test_planning_board_approve_now_is_validated_server_side():
    hs = [onboard(n, [("Origami", "enjoy")], availability=["weekend"]) for n in ("Ann", "Ben", "Cy")]
    jobs.run_pending()
    jobs.run_pending()
    with db.read() as c:
        pid = c.execute("SELECT id FROM circle_proposals").fetchone()["id"]
    for h, d in hs:
        v = client.post(f"/api/agent/invites/{pid}/accept", headers=h).json()
    cid = v["circle_id"]
    jobs.run_pending()
    draft = client.get(f"/api/circles/{cid}/events", headers=hs[0][0]).json()[0]
    host = next(x for x in hs if client.get("/api/agent/summary", headers=x[0]).json()["moderated_circles"])
    member = next(x for x in hs if x is not host)
    assert client.post(f"/api/agent/proposals/{draft['id']}/approve-now", json={}, headers=member[0]).status_code == 403
    out = client.post(f"/api/agent/proposals/{draft['id']}/approve-now", json={"timezone": "UTC"}, headers=host[0]).json()
    assert out["status"] == "confirmed" and out["event_id"]
    assert client.post(f"/api/agent/proposals/{draft['id']}/approve-now", json={}, headers=host[0]).status_code == 409  # no double publish
    assert client.post(f"/api/events/{out['event_id']}/complete", headers=host[0]).status_code == 409  # can't complete before it starts
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM events WHERE circle_id = ?", (cid,)).fetchone()[0] == 1
