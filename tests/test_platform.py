"""Accounts, organisations, events, meeting-place polls, chat, notifications (Qloo faked; no network)."""
import time
from datetime import datetime, timedelta

import pytest

from backend import auth, config, db, geo, mailer, store
from tests.conftest import fake_resolve
from tests.test_circles import _future, account, client, make_circle, signup

PW = "Corr3ct-Horse-Battery"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append((to, subject, body)) or False)
    return sent


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def link_token(body):
    return body.split("token=")[1].split()[0]


def iso(days, hour=10):
    return (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


def event_body(**kw):
    b = {"title": "Community dog-feeding walk", "description": "We feed and check on street dogs with the shelter team.",
         "category": "Animal welfare", "starts_at": iso(5, 9), "ends_at": iso(5, 11), "timezone": "Asia/Kolkata",
         "location_status": "confirmed", "venue_name": "Shelter gate", "address": "12 MG Road, Pune 411001", "capacity": 2,
         "rsvp_deadline": iso(4, 18), "cost_note": "Free", "materials": "Water bottle", "requirements": "18+", "min_age": 18,
         "safety": "Don't approach unfamiliar dogs alone."}
    b.update(kw)
    return b


# ---------------------------------------------------------------- auth
def test_signup_signin_signout_and_duplicates(outbox):
    r = client.post("/api/auth/signup", json={"email": "Asha@Example.org", "password": PW, "mode": "individual"})
    assert r.status_code == 200 and r.json()["token"].startswith("s_")
    tok = r.json()["token"]
    assert outbox and "verify" in outbox[0][2]
    assert client.post("/api/auth/signup", json={"email": "asha@example.org", "password": PW}).status_code == 409
    assert client.post("/api/auth/signup", json={"email": "x@example.org", "password": "short"}).status_code == 422
    assert client.post("/api/auth/signup", json={"email": "not-an-email", "password": PW}).status_code == 422
    me = client.get("/api/auth/me", headers=H(tok)).json()
    assert me["account"]["email"] == "asha@example.org" and not me["account"]["email_verified"] and not me["has_profile"]
    assert client.post("/api/auth/signin", json={"email": "asha@example.org", "password": "Wrong-Passw0rd"}).status_code == 401
    assert client.post("/api/auth/signin", json={"email": "nobody@example.org", "password": PW}).status_code == 401
    tok2 = client.post("/api/auth/signin", json={"email": "ASHA@example.org", "password": PW}).json()["token"]
    assert client.get("/api/auth/me", headers=H(tok2)).json()["user_id"] == me["user_id"]
    client.post("/api/auth/signout", headers=H(tok2))
    assert client.get("/api/auth/me", headers=H(tok2)).status_code == 401
    assert client.get("/api/auth/me", headers=H(tok)).status_code == 200  # other session untouched
    with db.read() as c:
        assert "Corr3ct" not in c.execute("SELECT password_hash FROM accounts").fetchone()[0]


def test_email_verification_and_password_reset(outbox):
    tok = client.post("/api/auth/signup", json={"email": "ravi@example.org", "password": PW}).json()["token"]
    vt = link_token(outbox[0][2])
    assert client.post("/api/auth/verify", json={"token": vt}).json()["verified"]
    assert client.post("/api/auth/verify", json={"token": vt}).status_code == 400  # single use
    assert client.get("/api/auth/me", headers=H(tok)).json()["account"]["email_verified"] == 1
    r = client.post("/api/auth/forgot", json={"email": "ravi@example.org"})
    r2 = client.post("/api/auth/forgot", json={"email": "ghost@example.org"})
    assert r.json()["message"] == r2.json()["message"]  # no account enumeration
    rt = link_token(outbox[-1][2])
    new = client.post("/api/auth/reset", json={"token": rt, "password": "N3w-Strong-Passphrase"}).json()["token"]
    assert client.get("/api/auth/me", headers=H(tok)).status_code == 401  # all old sessions revoked
    assert client.get("/api/auth/me", headers=H(new)).status_code == 200
    assert client.post("/api/auth/reset", json={"token": rt, "password": "An0ther-Strong-One"}).status_code == 400
    assert client.post("/api/auth/signin", json={"email": "ravi@example.org", "password": "N3w-Strong-Passphrase"}).status_code == 200


def test_session_expiry_and_lockout():
    tok = client.post("/api/auth/signup", json={"email": "e@example.org", "password": PW}).json()["token"]
    with db.tx() as c:
        c.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
    r = client.get("/api/auth/me", headers=H(tok))
    assert r.status_code == 401 and "expired" in r.text
    for _ in range(auth.LOCK_AFTER):
        auth._hits.clear()
        client.post("/api/auth/signin", json={"email": "e@example.org", "password": "Wrong-Passw0rd"})
    auth._hits.clear()
    assert client.post("/api/auth/signin", json={"email": "e@example.org", "password": PW}).status_code == 429


def test_legacy_user_claims_account_and_keeps_data():
    with db.tx() as c:
        uid, legacy = auth.create_user(c)
    h = H(legacy)
    body = {"alias": "Old Timer", "adult_confirmed": True, "discoverable": True, "interests": [{"label": "Chess", "intent": "teach", "signals": [{"id": "T:chess"}]}]}
    assert client.put("/api/me", json=body, headers=h).status_code == 200
    new = client.post("/api/auth/claim", json={"email": "old@example.org", "password": PW}, headers=h).json()
    assert new["user_id"] == uid
    tok = client.post("/api/auth/signin", json={"email": "old@example.org", "password": PW}).json()["token"]
    assert client.get("/api/me", headers=H(tok)).json()["alias"] == "Old Timer"


# ---------------------------------------------------------------- organisations
def make_org(h, **kw):
    body = {"name": kw.pop("name", "Paws Pune"), "description": "Street-animal welfare volunteers.", "category": "Animal welfare",
            "service_area": "Pune", "contact_kind": "email", "contact_value": "hello@pawspune.example", **kw}
    r = client.post("/api/orgs", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_org_roles_and_verification(monkeypatch, outbox):
    owner = account("owner@example.org")
    other = account()
    o = make_org(owner)
    assert o["verification_status"] == "not_verified" and o["my_role"] == "owner"
    assert client.put(f"/api/orgs/{o['id']}", json={"name": "Hijack"}, headers=other).status_code == 403
    assert client.post("/api/orgs", json={"name": "Bad", "contact_kind": "url", "contact_value": "javascript:alert(1)"}, headers=owner).status_code == 422
    r = client.post(f"/api/orgs/{o['id']}/verification", json={"evidence": "Registered trust no. PUN/123/2019, site https://pawspune.example"}, headers=owner)
    assert r.json()["verification_status"] == "pending"
    assert client.post(f"/api/admin/verifications/{o['id']}", json={"decision": "approve"}, headers=other).status_code == 403
    admin_tok = client.post("/api/auth/signup", json={"email": "admin@example.org", "password": PW}).json()["token"]
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.org"})
    assert client.get("/api/admin/verifications", headers=H(admin_tok)).status_code == 403  # admin email must be verified
    client.post("/api/auth/verify", json={"token": link_token(outbox[-1][2])})
    assert [x["id"] for x in client.get("/api/admin/verifications", headers=H(admin_tok)).json()] == [o["id"]]
    client.post(f"/api/admin/verifications/{o['id']}", json={"decision": "approve", "note": "Checked registry"}, headers=H(admin_tok))
    pub = client.get(f"/api/orgs/{o['slug']}").json()
    assert pub["verification_status"] == "verified" and "verification_evidence" not in pub
    assert client.get("/api/notifications", headers=owner).json()["unread"] == 1


def test_staff_invites():
    owner, staff = account(), account()
    o = make_org(owner)
    code = client.post(f"/api/orgs/{o['id']}/invites", headers=owner).json()["code"]
    assert client.post(f"/api/orgs/{o['id']}/invites", headers=staff).status_code == 403
    assert client.post("/api/org-invites/accept", json={"code": code}, headers=staff).json()["org_id"] == o["id"]
    assert client.post("/api/org-invites/accept", json={"code": code}, headers=account()).status_code == 400  # single use
    assert client.post(f"/api/orgs/{o['id']}/events", json=event_body(), headers=staff).status_code == 200
    assert client.put(f"/api/orgs/{o['id']}", json={"name": "Renamed by staff"}, headers=staff).status_code == 403
    assert len(client.get(f"/api/orgs/{o['id']}/team", headers=staff).json()) == 2


# ---------------------------------------------------------------- events
def test_event_lifecycle_rsvp_updates_cancel():
    owner = account()
    o = make_org(owner)
    bad = client.post(f"/api/orgs/{o['id']}/events", json=event_body(ends_at=iso(5, 8)), headers=owner)
    assert bad.status_code == 422
    assert client.post(f"/api/orgs/{o['id']}/events", json=event_body(address=""), headers=owner).status_code == 422
    assert client.post(f"/api/orgs/{o['id']}/events", json=event_body(timezone="Mars/Base"), headers=owner).status_code == 422
    ev = client.post(f"/api/orgs/{o['id']}/events", json=event_body(lat=18.52, lon=73.85, geo_source="nominatim"), headers=owner).json()
    assert ev["status"] == "draft" and ev["geo_source"] == "organiser"  # server never saw that geocoder result
    assert client.get(f"/api/events/{ev['id']}").status_code == 404  # drafts are private
    assert client.post(f"/api/orgs/{o['id']}/events", json=event_body(), headers=account()).status_code == 403
    client.post(f"/api/events/{ev['id']}/publish", headers=owner)
    pub = client.get(f"/api/events/{ev['id']}").json()
    assert pub["status"] == "published" and pub["map"]["source"] == "organiser" and pub["contact"]["kind"] == "email"
    assert [e["id"] for e in client.get("/api/events?q=dog").json()] == [ev["id"]]
    a, b, c_ = account(), account(), account()
    assert client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=a).json()["my_rsvp"] == "going"
    client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=b)
    r = client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=c_)
    assert r.status_code == 409 and "full" in r.text
    assert client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "maybe"}, headers=c_).status_code == 200
    assert client.get(f"/api/events/{ev['id']}").json()["display_status"] == "full"
    upd = client.put(f"/api/events/{ev['id']}", json=event_body(capacity=3, starts_at=iso(6, 9), ends_at=iso(6, 11),
                                                                 rsvp_deadline=iso(5, 18), reason="Rain forecast"), headers=owner).json()
    assert upd["updates"][0]["reason"] == "Rain forecast"
    for h in (a, b, c_):
        n = client.get("/api/notifications", headers=h).json()
        assert n["unread"] == 1 and "Rain forecast" in n["items"][0]["body"]
    assert client.put(f"/api/events/{ev['id']}", json=event_body(capacity=1), headers=owner).status_code == 409  # below going count
    assert client.post(f"/api/events/{ev['id']}/attendance", json={"user_id": "x", "attended": True}, headers=owner).status_code == 409
    assert client.post(f"/api/events/{ev['id']}/cancel", json={"reason": ""}, headers=owner).status_code == 422
    assert client.post(f"/api/events/{ev['id']}/cancel", json={"reason": "Shelter closed"}, headers=a).status_code == 403
    can = client.post(f"/api/events/{ev['id']}/cancel", json={"reason": "Shelter closed"}, headers=owner).json()
    assert can["status"] == "cancelled" and can["cancel_reason"] == "Shelter closed"
    assert client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=c_).status_code == 409
    org_pub = client.get(f"/api/orgs/{o['slug']}").json()
    assert org_pub["upcoming_events"] == [] and org_pub["past_events"][0]["status"] == "cancelled"


def test_tbc_location_completion_attendance_feedback():
    owner = account()
    o = make_org(owner)
    ev = client.post(f"/api/orgs/{o['id']}/events", json=event_body(location_status="tbc", address="", rsvp_deadline=None, capacity=10), headers=owner).json()
    client.post(f"/api/events/{ev['id']}/publish", headers=owner)
    d = client.get(f"/api/events/{ev['id']}").json()
    assert d["location_status"] == "tbc" and "map" not in d and d["address"] == ""
    a = account()
    a_id = client.get("/api/auth/me", headers=a).json()["user_id"]
    client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=a)
    assert client.post(f"/api/events/{ev['id']}/feedback", json={"rating": 5}, headers=a).status_code == 409
    with db.tx() as c:  # move the event into the past to exercise completion
        c.execute("UPDATE events SET starts_at = ?, ends_at = ? WHERE id = ?", (iso(-1, 9), iso(-1, 11), ev["id"]))
    assert client.post(f"/api/events/{ev['id']}/attendance", json={"user_id": a_id, "attended": True}, headers=owner).json()["ok"]
    assert client.post(f"/api/events/{ev['id']}/complete", headers=owner).json()["status"] == "completed"
    assert client.post(f"/api/events/{ev['id']}/feedback", json={"rating": 4, "comment": "Lovely"}, headers=account()).status_code == 403
    fb = client.post(f"/api/events/{ev['id']}/feedback", json={"rating": 4, "comment": "Lovely"}, headers=a).json()["feedback"]
    assert fb["count"] == 1 and fb["avg"] == 4
    dash = client.get(f"/api/orgs/{o['id']}/dashboard", headers=owner).json()["stats"]
    assert dash["events"] == {"completed": 1} and dash["attended"] == 1 and dash["feedback_avg"] == 4
    assert client.get(f"/api/orgs/{o['id']}/dashboard", headers=a).status_code == 403
    parts = client.get(f"/api/events/{ev['id']}/participants", headers=owner).json()
    assert parts[0]["attended"] is True and "@" not in str(parts)  # organisers never see emails


# ---------------------------------------------------------------- org programme -> Circle
def test_org_programme_to_invite_only_circle():
    owner = account()
    o = make_org(owner)
    p = client.post(f"/api/orgs/{o['id']}/programs", json={"name": "Seniors x Students"}, headers=owner).json()
    assert client.get(f"/api/programs/{p['id']}").status_code == 404  # org programmes are private to the team
    assert p["id"] not in [x["id"] for x in client.get("/api/programs").json()]
    doc = client.get(f"/api/programs/{p['id']}", headers=owner).json()

    def person(pid, name, label, intent):
        return {"id": pid, "name": name, "consent": True, "location": "Pune",
                "interests": [{"label": label, "intent": intent, "resolved": fake_resolve(label)["candidates"][:1]}]}
    doc["participants"] = [person("p1", "Asha", "Chess", "teach"), person("p2", "Arjun", "Chess", "learn")]
    doc["org_id"] = "O-somebody-else"
    client.put(f"/api/programs/{p['id']}", json=doc, headers=owner)
    assert store.get(p["id"])["org_id"] == o["id"]  # client can't move it
    client.post("/api/discovery/run", json={"program_id": p["id"]}, headers=owner)
    groups = client.post("/api/bridges/build", json={"program_id": p["id"]}, headers=owner).json()["bridges"]["groups"]
    res = client.post(f"/api/orgs/{o['id']}/programs/{p['id']}/groups/{groups[0]['id']}/circle", json={"name": "Chess Mentors"}, headers=owner).json()
    assert client.post(f"/api/orgs/{o['id']}/programs/{p['id']}/groups/{groups[0]['id']}/circle", json={}, headers=owner).status_code == 409
    cid, code = res["circle_id"], res["invite_code"]
    det = client.get(f"/api/circles/{cid}", headers=owner).json()
    assert det["org"]["id"] == o["id"] and det["signals"][0]["id"] == "T:chess"
    hp, _ = signup("Participant", [("Chess", "learn")])
    assert client.get(f"/api/circles/{cid}", headers=hp).status_code == 404
    assert client.post(f"/api/circles/{cid}/join?invite={code}", headers=hp).json()["status"] == "pending"
    pid_user = client.get("/api/me", headers=hp).json()["user_id"]
    assert client.post(f"/api/circles/{cid}/members/{pid_user}", json={"action": "approve"}, headers=owner).status_code == 200
    assert client.get(f"/api/orgs/{o['id']}/dashboard", headers=owner).json()["stats"]["circle_members"] == 2


# ---------------------------------------------------------------- chat
def test_chat_permissions_idempotency_pagination_blocking():
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess").json()["id"]
    m, md = signup("Member", [("Chess", "learn")])
    out, _ = signup("Outsider", [("Chess", "learn")])
    client.post(f"/api/circles/{cid}/join", headers=m)
    assert client.post(f"/api/circles/{cid}/messages", json={"body": "hi", "client_id": "abcdef1"}, headers=out).status_code == 403
    assert client.get(f"/api/circles/{cid}/messages", headers=out).status_code == 403
    r1 = client.post(f"/api/circles/{cid}/messages", json={"body": "hello", "client_id": "abcdef1"}, headers=m).json()
    r2 = client.post(f"/api/circles/{cid}/messages", json={"body": "hello", "client_id": "abcdef1"}, headers=m).json()
    assert r1["id"] == r2["id"] and r2["duplicate"]
    for i in range(5):
        client.post(f"/api/circles/{cid}/messages", json={"body": f"msg {i}", "client_id": f"cid00{i}x"}, headers=hh)
    page = client.get(f"/api/circles/{cid}/messages?limit=3", headers=m).json()
    assert [x["body"] for x in page["messages"]] == ["msg 2", "msg 3", "msg 4"] and page["has_more"]
    older = client.get(f"/api/circles/{cid}/messages?limit=3&before={page['messages'][0]['id']}", headers=m).json()
    assert older["messages"][0]["body"] == "hello"
    newer = client.get(f"/api/circles/{cid}/messages?after={page['messages'][-1]['id']}", headers=m).json()
    assert newer["messages"] == []
    host_id = client.get("/api/me", headers=hh).json()["user_id"]
    client.post("/api/me/blocks", json={"user_id": host_id}, headers=m)
    assert all(x["body"] == "" for x in client.get(f"/api/circles/{cid}/messages", headers=m).json()["messages"] if x["author_id"] == host_id)
    assert client.post(f"/api/circles/{cid}/messages/{r1['id']}/report", json={"reason": "spam test"}, headers=hh).json()["ok"]
    assert client.delete(f"/api/circles/{cid}/messages/{r1['id']}", headers=hh).json()["ok"]  # moderator hide
    assert client.get(f"/api/circles/{cid}/messages", headers=hh).json()["messages"][0]["hidden"]


# ---------------------------------------------------------------- meeting places -> real Circle event
def test_place_poll_confirm_creates_real_event(monkeypatch):
    hh, hp = signup("Host", [("Chess", "teach")])
    cid = make_circle(hh, hp, "Chess", min_size=2).json()["id"]
    m, _ = signup("Member", [("Chess", "learn")])
    out, _ = signup("Outsider", [("Chess", "learn")])
    client.post(f"/api/circles/{cid}/join", headers=m)
    prop = client.post(f"/api/circles/{cid}/events", headers=m, json={"duration_min": 60, "budget": 20, "time_options": [_future(4)]}).json()
    pid = prop["id"]
    assert client.get(f"/api/proposals/{pid}/places", headers=out).status_code in (403, 404)
    r = client.post(f"/api/proposals/{pid}/places", json={"name": "Library hall", "address": "Kothrud Library, Pune", "lat": 1.0, "lon": 2.0}, headers=m)
    assert r.status_code == 422  # coordinates not from the geocoder are refused
    client.post(f"/api/proposals/{pid}/places", json={"name": "Library hall", "address": "Kothrud Library, Pune"}, headers=m)
    geo.remember(18.5074, 73.8077)
    pl = client.post(f"/api/proposals/{pid}/places", json={"name": "Park pavilion", "address": "Kothrud Park, Pune", "lat": 18.5074, "lon": 73.8077}, headers=hh).json()
    assert client.post(f"/api/proposals/{pid}/places", json={"name": "Park pavilion", "address": "Kothrud Park, Pune"}, headers=hh).status_code == 409
    park = next(p for p in pl["places"] if p["name"] == "Park pavilion")
    assert park["geo_source"] == "nominatim"
    client.post(f"/api/proposals/{pid}/places/vote", json={"place_id": park["id"]}, headers=m)
    lib = next(p for p in pl["places"] if p["name"] == "Library hall")
    client.post(f"/api/proposals/{pid}/places/vote", json={"place_id": lib["id"]}, headers=hh)
    v = client.post(f"/api/proposals/{pid}/places/vote", json={"place_id": park["id"]}, headers=hh).json()  # change vote
    assert {p["name"]: p["votes"] for p in v["places"]} == {"Park pavilion": 2, "Library hall": 0}
    assert client.post(f"/api/circle-events/{pid}/confirm", json={"option": 0, "time_index": 0, "place_id": park["id"], "timezone": "Asia/Kolkata"}, headers=m).status_code == 403
    conf = client.post(f"/api/circle-events/{pid}/confirm", json={"option": 0, "time_index": 0, "place_id": park["id"], "timezone": "Asia/Kolkata"}, headers=hh).json()
    eid = conf["event_id"]
    ev = client.get(f"/api/events/{eid}", headers=m).json()
    assert ev["location_status"] == "confirmed" and ev["address"] == "Kothrud Park, Pune" and ev["map"]["source"] == "nominatim"
    assert ev["contact"]["kind"] == "circle_chat" and ev["visibility"] == "members"
    assert client.get(f"/api/events/{eid}", headers=out).status_code == 404
    assert client.get(f"/api/events/{eid}").status_code == 404
    assert client.get("/api/notifications", headers=m).json()["items"][0]["kind"] == "event_confirmed"
    assert client.post(f"/api/events/{eid}/rsvp", json={"status": "going"}, headers=m).json()["my_rsvp"] == "going"
    assert client.post(f"/api/proposals/{pid}/places/vote", json={"place_id": lib["id"]}, headers=m).status_code == 409
    acts = client.get("/api/me/activities", headers=m).json()
    assert acts["upcoming"][0]["id"] == eid
    client.post(f"/api/circles/{cid}/messages", json={"body": "See you there", "client_id": "thread01", "thread": f"event:{eid}"}, headers=m)
    assert client.get(f"/api/circles/{cid}/messages?thread=event:{eid}", headers=hh).json()["messages"][0]["body"] == "See you there"
    assert client.post(f"/api/circles/{cid}/messages", json={"body": "x", "client_id": "thread02", "thread": "event:nope"}, headers=m).status_code == 400


def test_geocoder_disabled_is_honest():
    r = client.get("/api/geo/search?q=Pune library", headers=account())
    assert r.status_code == 501 and "isn't configured" in r.text


def test_notifications_mark_read_and_security_headers():
    h = account()
    uid = client.get("/api/auth/me", headers=h).json()["user_id"]
    from backend.platform_svc import notify
    with db.tx() as c:
        notify(c, [uid], "test", "Hello")
    assert client.get("/api/notifications/unread", headers=h).json()["unread"] == 1
    client.post("/api/notifications/read", headers=h)
    assert client.get("/api/notifications/unread", headers=h).json()["unread"] == 0
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"


def test_deleting_sole_org_owner_cancels_events_and_notifies():
    owner = account()
    o = make_org(owner)
    ev = client.post(f"/api/orgs/{o['id']}/events", json=event_body(capacity=5), headers=owner).json()
    client.post(f"/api/events/{ev['id']}/publish", headers=owner)
    a = account()
    client.post(f"/api/events/{ev['id']}/rsvp", json={"status": "going"}, headers=a)
    assert client.delete("/api/me", headers=owner).json()["deleted"]
    assert client.get(f"/api/events/{ev['id']}").json()["status"] == "cancelled"
    assert client.get("/api/notifications", headers=a).json()["items"][0]["kind"] == "event_cancelled"


def test_legacy_timezone_names_from_browsers_are_accepted():
    from backend.platform_svc import _tz
    assert _tz("Asia/Calcutta") is not None and _tz("Asia/Kolkata") is not None
    owner = account()
    o = make_org(owner)
    r = client.post(f"/api/orgs/{o['id']}/events", json=event_body(timezone="Asia/Calcutta"), headers=owner)
    assert r.status_code == 200, r.text
