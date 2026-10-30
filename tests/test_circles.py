"""Integration tests for individuals + Circles, with Qloo replaced by deterministic fakes (no network)."""
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import auth, config, db, main
from tests.conftest import _n, fake_resolve

client = TestClient(main.app)


def profile(alias, interests, **kw):
    body = {"alias": alias, "area": kw.pop("area", "Kothrud, Pune"), "adult_confirmed": True,
            "discoverable": kw.pop("discoverable", True), "share_interests": kw.pop("share_interests", True),
            "interests": [{"label": l, "intent": i, "signals": [{"id": f"T:{_n(l)}"}]} for l, i in interests]}
    body.update(kw)
    return body


_n_accounts = [0]


def account(email=None):
    _n_accounts[0] += 1
    email = email or f"user{_n_accounts[0]}@example.org"
    r = client.post("/api/auth/signup", json={"email": email, "password": "Corr3ct-Horse-Battery"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def signup(alias, interests, **kw):
    h = account()
    r = client.post("/api/me", json=profile(alias, interests, **kw), headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    d["token"] = h["Authorization"][7:]
    return h, d


def make_circle(h, prof, label, **kw):
    iid = next(i["id"] for i in prof["profile"]["interests"] if i["label"] == label)
    body = {"interest_id": iid, "name": f"{label} Circle", "meeting_mode": kw.pop("meeting_mode", "either"),
            "capacity": kw.pop("capacity", 12), "min_size": kw.pop("min_size", 2), **kw}
    return client.post("/api/circles", json=body, headers=h)


def ncircles():
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM circles").fetchone()[0]


# ---------------------------------------------------------------- onboarding + consent + Qloo
def test_onboarding_adult_token_and_profile():
    assert client.post("/api/me", json=profile("Asha", [("Chess", "teach")])).status_code == 401  # account required
    r = client.post("/api/me", json=profile("Asha", [("Chess", "teach")], adult_confirmed=False), headers=account())
    assert r.status_code == 422
    h, d = signup("Asha", [("Chess", "teach")])
    assert d["token"] and d["profile"]["alias"] == "Asha"
    me = client.get("/api/me", headers=h).json()
    assert me["interests"][0]["signals"][0]["id"] == "T:chess" and me["interests"][0]["signals"][0]["retrieved_at"]
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    with db.read() as c:  # raw token never stored
        assert c.execute("SELECT COUNT(*) FROM users WHERE token_hash = ?", (d["token"],)).fetchone()[0] == 0


def test_fabricated_qloo_ids_are_dropped():
    body = profile("Ravi", [("Chess", "enjoy")])
    body["interests"][0]["signals"] = [{"id": "T:chess"}, {"id": "MADE-UP-ID"}]
    d = client.post("/api/me", json=body, headers=account()).json()
    ids = [s["id"] for s in d["profile"]["interests"][0]["signals"]]
    assert ids == ["T:chess"] and d["warnings"]


def test_failed_qloo_keeps_declared_label():
    h, d = signup("Mina", [("Qloo down", "discuss")])
    it = d["profile"]["interests"][0]
    assert it["label"] == "Qloo down" and it["signals"] == [] and any("Qloo unavailable" in w for w in d["warnings"])


def test_playground_resolve_does_not_create_circle(monkeypatch):
    r = client.post("/api/interests/resolve", json={"label": "Jazz"})
    assert r.status_code == 200 and r.json()["candidates"]
    assert ncircles() == 0
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_recommendations_require_consent_and_withdrawal():
    h, _ = signup("Ana", [("Chess", "learn")], discoverable=False)
    assert client.get("/api/circles/recommendations", headers=h).status_code == 403
    assert client.put("/api/me/consent", json={"discoverable": True}, headers=h).json()["discoverable"] is True
    assert client.get("/api/circles/recommendations", headers=h).status_code == 200
    client.put("/api/me/consent", json={"discoverable": False}, headers=h)
    assert client.get("/api/circles/recommendations", headers=h).status_code == 403


# ---------------------------------------------------------------- matching
def test_match_existing_circle_declared_and_qloo_reasons():
    hh, hp = signup("Host", [("Chess", "teach"), ("Board games", "enjoy")])
    assert make_circle(hh, hp, "Chess", intents=["teach", "learn"]).status_code == 200
    assert make_circle(hh, hp, "Board games").status_code == 200
    hu, _ = signup("Learner", [("Chess", "learn")])
    rec = client.get("/api/circles/recommendations", headers=hu).json()
    names = [r["name"] for r in rec["recommendations"]]
    assert names[0] == "Chess Circle"  # declared match outranks Qloo-only link
    chess = rec["recommendations"][0]
    assert any(x["source"] == "declared" for x in chess["reasons"])
    board = next(r for r in rec["recommendations"] if r["name"] == "Board games Circle")
    assert [x["source"] for x in board["reasons"]][0] == "qloo"  # only Qloo-derived link, labelled as such
    assert "%" not in str(rec)
    assert rec["create_suggestions"] == []


def test_hard_constraints_beat_taste():
    hh, hp = signup("Host", [("Chess", "teach")], area="Pune")
    make_circle(hh, hp, "Chess", meeting_mode="in_person", area="Pune")
    h1, _ = signup("OnlineOnly", [("Chess", "learn")], activity_prefs=["online"])
    r1 = client.get("/api/circles/recommendations", headers=h1).json()
    assert r1["recommendations"] == [] and r1["excluded"] == {"meeting mode": 1}
    h2, _ = signup("Wheels", [("Chess", "learn")], accessibility=["wheelchair"], area="Pune")
    r2 = client.get("/api/circles/recommendations", headers=h2).json()
    assert r2["recommendations"] == [] and r2["excluded"] == {"accessibility": 1}
    assert r2["create_suggestions"][0]["label"] == "Chess"


def test_no_match_offers_creation_and_duplicates_are_blocked():
    h1, p1 = signup("Amy", [("Jazz", "enjoy")])
    rec = client.get("/api/circles/recommendations", headers=h1).json()
    assert rec["recommendations"] == [] and rec["create_suggestions"][0]["label"] == "Jazz"
    assert ncircles() == 0  # nothing created until the user confirms
    assert make_circle(h1, p1, "Jazz").status_code == 200
    h2, p2 = signup("Ben", [("jazz", "enjoy")])
    r = make_circle(h2, p2, "jazz")
    assert r.status_code == 409 and r.json()["detail"]["name"] == "Jazz Circle"
    assert ncircles() == 1


def test_unique_index_blocks_race():
    hh, hp = signup("Amy", [("Jazz", "enjoy")])
    make_circle(hh, hp, "Jazz")
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            c.execute("INSERT INTO circles (id, name, topic_label, topic_key, area_key, created_at) "
                      "SELECT 'X1', 'Dup', topic_label, topic_key, area_key, 0 FROM circles LIMIT 1")


def test_join_idempotent_capacity_and_leave():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess", capacity=3).json()["id"]
    a, _ = signup("Amy", [("Chess", "learn")])
    b, _ = signup("Ben", [("Chess", "learn")])
    c_, _ = signup("Cal", [("Chess", "learn")])
    assert client.post(f"/api/circles/{cid}/join", headers=a).json() == {"status": "active", "already": False}
    assert client.post(f"/api/circles/{cid}/join", headers=a).json()["already"] is True
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ?", (cid,)).fetchone()[0] == 2
    assert client.post(f"/api/circles/{cid}/join", headers=b).status_code == 200
    r = client.post(f"/api/circles/{cid}/join", headers=c_)
    assert r.status_code == 403 and "full" in r.text
    assert client.post(f"/api/circles/{cid}/leave", headers=b).json()["left"]
    assert client.post(f"/api/circles/{cid}/join", headers=c_).status_code == 200


def test_private_circle_does_not_leak():
    hh, hp = signup("Host", [("Diabetes", "discuss")])
    r = make_circle(hh, hp, "Diabetes", visibility="private")
    cid = r.json()["id"]
    assert r.json()["category"] == "health" and "not a source of diagnosis" in r.json()["notice"]
    out, _ = signup("Outsider", [("Diabetes", "discuss")])
    assert client.get("/api/circles").json() == []
    assert client.get(f"/api/circles/{cid}", headers=out).status_code == 404
    assert client.get(f"/api/circles/{cid}/posts", headers=out).status_code == 404
    assert client.get(f"/api/circles/{cid}/members", headers=out).status_code == 404
    assert client.post(f"/api/circles/{cid}/join", headers=out).status_code == 404  # no invite code
    code = r.json()["invite_code"]
    assert code and client.get(f"/api/circles/{cid}?invite={code}", headers=out).json()["name"]
    assert "invite_code" not in client.get(f"/api/circles/{cid}?invite={code}", headers=out).json()
    assert client.post(f"/api/circles/{cid}/join?invite={code}", headers=out).json()["status"] == "pending"
    assert client.get(f"/api/circles/{cid}/posts", headers=out).status_code == 403
    uid = client.get("/api/me", headers=out).json()["user_id"]
    assert client.post(f"/api/circles/{cid}/members/{uid}", json={"action": "approve"}, headers=out).status_code == 403
    assert client.post(f"/api/circles/{cid}/members/{uid}", json={"action": "approve"}, headers=hh).status_code == 200
    assert client.get(f"/api/circles/{cid}/posts", headers=out).status_code == 200


# ---------------------------------------------------------------- discussion + moderation
def test_discussion_crud_pagination_and_authz():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess").json()["id"]
    m, _ = signup("Member", [("Chess", "learn")])
    nm, _ = signup("NonMember", [("Chess", "learn")])
    client.post(f"/api/circles/{cid}/join", headers=m)
    assert client.post(f"/api/circles/{cid}/posts", json={"body": "hi"}, headers=nm).status_code == 403
    p1 = client.post(f"/api/circles/{cid}/posts", json={"body": "<b>Hello</b> all"}, headers=m).json()["id"]
    assert client.post(f"/api/circles/{cid}/posts", json={"body": "<b>Hello</b> all"}, headers=m).status_code == 409
    client.post(f"/api/circles/{cid}/posts", json={"body": "Welcome!", "parent_id": p1}, headers=hh)
    assert client.patch(f"/api/circles/{cid}/posts/{p1}", json={"body": "hacked"}, headers=hh).status_code == 403
    assert client.patch(f"/api/circles/{cid}/posts/{p1}", json={"body": "Hello all (edited)"}, headers=m).status_code == 200
    for i in range(3):
        auth._hits.clear()
        client.post(f"/api/circles/{cid}/posts", json={"body": f"post {i}"}, headers=hh)
    page = client.get(f"/api/circles/{cid}/posts?limit=2", headers=m).json()
    assert len(page["posts"]) == 2 and page["next_before"]
    rest = client.get(f"/api/circles/{cid}/posts?limit=2&before={page['next_before']}", headers=m).json()
    first = rest["posts"][-1]
    assert first["body"] == "Hello all (edited)" and first["edited_at"] and first["replies"][0]["body"] == "Welcome!"
    assert client.delete(f"/api/circles/{cid}/posts/{p1}", headers=m).status_code == 200


def test_report_hide_and_block():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess").json()["id"]
    a, ad = signup("Amy", [("Chess", "learn")])
    b, bd = signup("Ben", [("Chess", "learn")])
    client.post(f"/api/circles/{cid}/join", headers=a)
    client.post(f"/api/circles/{cid}/join", headers=b)
    pid = client.post(f"/api/circles/{cid}/posts", json={"body": "rude words"}, headers=b).json()["id"]
    assert client.post(f"/api/circles/{cid}/reports", json={"target_type": "post", "target_id": str(pid), "reason": "Abusive"}, headers=a).json()["ok"]
    assert client.get(f"/api/circles/{cid}/reports", headers=a).status_code == 403
    reps = client.get(f"/api/circles/{cid}/reports", headers=hh).json()
    assert reps[0]["post_body"] == "rude words"
    client.post(f"/api/circles/{cid}/posts/{pid}/hide", json={"hidden": True}, headers=hh)
    assert client.get(f"/api/circles/{cid}/posts", headers=a).json()["posts"][0]["body"] == ""
    # block: B's posts disappear for A; A can't join a new Circle B is in
    client.post(f"/api/circles/{cid}/posts/{pid}/hide", json={"hidden": False}, headers=hh)
    client.post("/api/me/blocks", json={"user_id": bd["user_id"]}, headers=a)
    view = client.get(f"/api/circles/{cid}/posts", headers=a).json()["posts"][0]
    assert view["blocked"] and view["body"] == ""
    c2 = make_circle(b, bd, "Chess", visibility="private", name="B private").json()
    assert client.post(f"/api/circles/{c2['id']}/join?invite={c2['invite_code']}", headers=a).status_code == 403


# ---------------------------------------------------------------- member-led events
def _future(days):
    return (datetime.now() + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat()


def test_event_propose_vote_confirm_rsvp():
    hh, hp = signup("Host", [("Chess", "teach")], availability=["weekday_evening", "weekend"])
    cid = make_circle(hh, hp, "Chess", min_size=2, intents=["teach", "learn"]).json()["id"]
    m, _ = signup("Member", [("Chess", "learn")], budget_max=20)
    client.post(f"/api/circles/{cid}/join", headers=m)
    ev = client.post(f"/api/circles/{cid}/events", headers=m, json={
        "duration_min": 60, "budget": 20, "time_options": [_future(3), _future(10)]}).json()
    plan = ev["plan"]
    assert ev["status"] == "proposed" and 1 <= len(plan["concepts"]) <= 2
    k = plan["concepts"][0]
    assert {c["check"] for c in k["checks"]} >= {"Duration", "Budget", "Meeting mode", "Capacity", "Venue & booking"}
    assert k["unresolved_questions"] and k["evidence_refs"]
    assert any(e["source"] == "qloo" for e in plan["evidence"])
    assert all(c["status"] != "fail" for c in k["checks"])
    client.post(f"/api/circle-events/{ev['id']}/vote", json={"kind": "activity", "choice": 0}, headers=m)
    v = client.post(f"/api/circle-events/{ev['id']}/vote", json={"kind": "time", "choice": 1}, headers=hh).json()
    assert v["votes"]["activity"] == {"0": 1} or v["votes"]["activity"] == {0: 1}
    assert client.post(f"/api/circle-events/{ev['id']}/rsvp", json={"status": "going"}, headers=m).status_code == 409
    assert client.post(f"/api/circle-events/{ev['id']}/confirm", json={"option": 0, "time_index": 1}, headers=m).status_code == 403
    conf = client.post(f"/api/circle-events/{ev['id']}/confirm", json={"option": 0, "time_index": 1}, headers=hh).json()
    assert conf["status"] == "confirmed" and conf["chosen_time"]
    assert client.post(f"/api/circle-events/{ev['id']}/rsvp", json={"status": "going"}, headers=m).json()["my_rsvp"] == "going"
    assert client.get("/api/me/events", headers=m).json()[0]["status"] == "confirmed"


def test_event_hard_constraints_enforced_in_code():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess", min_size=3, capacity=5).json()["id"]
    r = client.post(f"/api/circles/{cid}/events", headers=hh, json={"duration_min": 60, "budget": 10, "capacity": 9})
    assert r.status_code == 400  # capacity above Circle capacity
    r = client.post(f"/api/circles/{cid}/events", headers=hh, json={"duration_min": 60, "budget": 10, "time_options": ["2001-01-01T10:00"]})
    assert r.status_code == 400  # past time
    ev = client.post(f"/api/circles/{cid}/events", headers=hh, json={"duration_min": 60, "budget": 10, "time_options": [_future(5)]}).json()
    r = client.post(f"/api/circle-events/{ev['id']}/confirm", json={"option": 0, "time_index": 0}, headers=hh)
    assert r.status_code == 409 and "Minimum group size" in r.text  # only 1 member, minimum 3
    assert client.post(f"/api/circle-events/{ev['id']}/cancel", headers=hh).json()["status"] == "cancelled"


# ---------------------------------------------------------------- deletion
def test_account_deletion_transfers_host_and_erases_posts():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess").json()["id"]
    m, md = signup("Member", [("Chess", "learn")])
    client.post(f"/api/circles/{cid}/join", headers=m)
    client.post(f"/api/circles/{cid}/posts", json={"body": "my secret"}, headers=hh)
    assert client.delete("/api/me", headers=hh).json()["deleted"]
    assert client.get("/api/me", headers=hh).status_code == 401
    mem = client.get(f"/api/circles/{cid}/members", headers=m).json()
    assert mem["is_host"] and len(mem["members"]) == 1
    post = client.get(f"/api/circles/{cid}/posts", headers=m).json()["posts"][0]
    assert post["body"] == "" and post["author"] == "[deleted account]"


# ---------------------------------------------------------------- existing organizer workflow still works
def test_organizer_workflow_regression():
    def person(pid, name, ints):
        return {"id": pid, "name": name, "consent": True, "location": "Pune",
                "interests": [{"label": l, "intent": i, "resolved": [c for c in fake_resolve(l)["candidates"][:1]]} for l, i in ints]}
    prog = client.post("/api/programs", json={"name": "Org", "location": "Pune", "constraints": {"duration_min": 60, "budget": 30},
                                              "grouping": {"min_size": 2, "max_size": 4},
                                              "participants": [person("p1", "A", [("Chess", "teach")]), person("p2", "B", [("Chess", "learn")])]}).json()
    pid = prog["id"]
    assert client.post("/api/discovery/run", json={"program_id": pid}).status_code == 200
    groups = client.post("/api/bridges/build", json={"program_id": pid}).json()["bridges"]["groups"]
    assert groups
    plan = client.post("/api/events/generate", json={"program_id": pid, "group_id": groups[0]["id"]}).json()
    assert plan["concepts"]
    assert client.post("/api/events/approve", json={"program_id": pid, "group_id": groups[0]["id"],
                                                    "concept_id": plan["concepts"][0]["id"]}).status_code == 200
    assert ncircles() == 0


def test_migrations_are_reversible(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "m.db")
    assert db.migrate() == ["0001", "0002", "0003", "0004", "0005", "0006"]
    assert db.rollback("0002") == ["0006", "0005", "0004", "0003", "0002"]
    with db.read() as c:
        assert not c.execute("SELECT name FROM sqlite_master WHERE name = 'circles'").fetchone()
        assert c.execute("SELECT name FROM sqlite_master WHERE name = 'programs'").fetchone()
    assert db.migrate() == ["0002", "0003", "0004", "0005", "0006"]
