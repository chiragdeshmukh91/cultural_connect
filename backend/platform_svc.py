"""Organisations, published events, meeting-place polls, Circle chat and notifications.

All authorization is decided here on the server. Nothing in this module fabricates data: addresses, dates,
capacities and counts come from organiser input or the database; map pins only from organiser input or a
geocoder response the server itself received.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from . import auth, db, geo, store
from .circles import _circle_or_404, _is_mod, _active, norm

EVENT_FIELDS = ("title", "description", "purpose", "category", "starts_at", "ends_at", "timezone", "location_status",
                "venue_name", "address", "lat", "lon", "geo_source", "online_url", "capacity", "rsvp_deadline",
                "cost_note", "materials", "accessibility", "requirements", "min_age", "safety", "image_url")
MATERIAL = ("starts_at", "ends_at", "timezone", "location_status", "venue_name", "address", "lat", "lon", "online_url", "status")


def now() -> float:
    return time.time()


# ---------------------------------------------------------------- notifications
def notify(c, user_ids, kind: str, title: str, body: str = "", link: str = ""):
    ts = now()
    for u in {u for u in user_ids if u}:
        c.execute("INSERT INTO notifications (user_id, kind, title, body, link, created_at) VALUES (?,?,?,?,?,?)",
                  (u, kind, title[:200], body[:500], link[:200], ts))


def notify_once(c, uid: str, key: str, kind: str, title: str, body: str = "", link: str = "") -> bool:
    """Insert a notification at most once per dedupe key (repeated agent triggers can't spam). True if inserted."""
    cur = c.execute("INSERT OR IGNORE INTO notifications (user_id, kind, title, body, link, created_at, dedupe_key) "
                    "VALUES (?,?,?,?,?,?,?)", (uid, kind, title[:200], body[:500], link[:200], now(), key[:200]))
    return cur.rowcount == 1


def list_notifications(uid: str, limit: int = 30) -> dict:
    with db.read() as c:
        rows = c.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?", (uid, min(limit, 100))).fetchall()
        unread = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (uid,)).fetchone()[0]
    return {"unread": unread, "items": [dict(r) for r in rows]}


def unread_count(uid: str) -> int:
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (uid,)).fetchone()[0]


def mark_read(uid: str, nid: int | None):
    with db.tx() as c:
        if nid:
            c.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ?", (now(), nid, uid))
        else:
            c.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (now(), uid))


# ---------------------------------------------------------------- organisations
def _slug(c, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    slug, i = base, 2
    while c.execute("SELECT 1 FROM organisations WHERE slug = ?", (slug,)).fetchone():
        slug, i = f"{base}-{i}", i + 1
    return slug


def org_role(c, oid: str, uid: str | None) -> str | None:
    if not uid:
        return None
    r = c.execute("SELECT role FROM org_members WHERE org_id = ? AND user_id = ?", (oid, uid)).fetchone()
    return r["role"] if r else None


def _org(c, ref: str):
    row = c.execute("SELECT * FROM organisations WHERE id = ? OR slug = ?", (ref, ref)).fetchone()
    if not row:
        raise HTTPException(404, "Organisation not found.")
    return row


def _require_staff(c, oid, uid, owner=False):
    role = org_role(c, oid, uid)
    if not role or (owner and role != "owner"):
        raise HTTPException(403, "Only this organisation's " + ("owners" if owner else "team") + " can do that.")
    return role


def _contact(kind: str, value: str):
    value = (value or "").strip()
    if not kind:
        return "", ""
    if kind == "email" and not auth.EMAIL_RE.match(value.lower()):
        raise HTTPException(422, "Public contact email isn't valid.")
    if kind == "phone" and not re.fullmatch(r"\+?[0-9 ()\-]{6,20}", value):
        raise HTTPException(422, "Public contact phone isn't valid.")
    if kind == "url" and not re.match(r"^https://[^\s]+\.[^\s]+$", value):
        raise HTTPException(422, "Public contact link must start with https://")
    return kind, value


def _safe_url(u: str) -> str:
    u = (u or "").strip()
    if u and not re.match(r"^https://[^\s\"'<>]+$", u):
        raise HTTPException(422, "Links must start with https://")
    return u


def _media(u: str) -> str:
    from .uploads import media_url
    return media_url(u, allow_https=True)


def create_org(uid: str, data: dict) -> dict:
    kind, value = _contact(data.get("contact_kind", ""), data.get("contact_value", ""))
    with db.tx() as c:
        oid = "O" + uuid.uuid4().hex[:10]
        c.execute("""INSERT INTO organisations (id, slug, name, description, logo_url, category, service_area, contact_kind,
                     contact_value, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (oid, _slug(c, data["name"]), data["name"].strip(), data.get("description", ""), _media(data.get("logo_url", "")),
                   data.get("category", ""), data.get("service_area", ""), kind, value, uid, now(), now()))
        c.execute("INSERT INTO org_members VALUES (?,?,?,?)", (oid, uid, "owner", now()))
    return org_detail(oid, uid)


def update_org(uid: str, oid: str, data: dict) -> dict:
    with db.tx() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid, owner=True)
        kind, value = _contact(data.get("contact_kind", row["contact_kind"]), data.get("contact_value", row["contact_value"]))
        c.execute("""UPDATE organisations SET name = ?, description = ?, logo_url = ?, category = ?, service_area = ?,
                     contact_kind = ?, contact_value = ?, updated_at = ? WHERE id = ?""",
                  (data.get("name", row["name"]), data.get("description", row["description"]),
                   _media(data.get("logo_url", row["logo_url"])), data.get("category", row["category"]),
                   data.get("service_area", row["service_area"]), kind, value, now(), row["id"]))
    return org_detail(row["id"], uid)


def _org_public(row) -> dict:
    return {"id": row["id"], "slug": row["slug"], "name": row["name"], "description": row["description"],
            "logo_url": row["logo_url"], "category": row["category"], "service_area": row["service_area"],
            "contact_kind": row["contact_kind"], "contact_value": row["contact_value"],
            "verification_status": row["verification_status"], "verified_at": row["verified_at"], "created_at": row["created_at"]}


def org_detail(ref: str, uid: str | None) -> dict:
    with db.read() as c:
        row = _org(c, ref)
        d = _org_public(row)
        role = org_role(c, row["id"], uid)
        d["my_role"] = role
        if role:
            d["verification_note"] = row["verification_note"]
            d["verification_evidence"] = row["verification_evidence"]
        evs = c.execute("SELECT * FROM events WHERE org_id = ? AND status <> 'draft' ORDER BY starts_at", (row["id"],)).fetchall()
        d["upcoming_events"] = [_event_card(c, e) for e in evs if e["status"] == "published" and not _is_past(e)]
        d["past_events"] = [_event_card(c, e) for e in reversed(evs) if e["status"] in ("completed", "cancelled") or _is_past(e)][:20]
        d["circles"] = [{"id": r["id"], "name": r["name"], "topic_label": r["topic_label"], "visibility": r["visibility"]}
                        for r in c.execute("SELECT * FROM circles WHERE org_id = ? AND status = 'active' AND visibility = 'public'", (row["id"],))]
        return d


def list_orgs(q: str = "") -> list[dict]:
    with db.read() as c:
        rows = c.execute("SELECT * FROM organisations ORDER BY name LIMIT 200").fetchall()
        qn = norm(q)
        out = []
        for r in rows:
            if qn and qn not in norm(r["name"] + " " + r["category"] + " " + r["service_area"]):
                continue
            d = _org_public(r)
            # real counts only: upcoming published public events and active public Circles
            d["upcoming_events"] = sum(1 for e in c.execute("SELECT * FROM events WHERE org_id = ? AND status = 'published' AND visibility = 'public'",
                                                            (r["id"],)).fetchall() if not _is_past(e))
            d["circles"] = c.execute("SELECT COUNT(*) FROM circles WHERE org_id = ? AND status = 'active' AND visibility = 'public'", (r["id"],)).fetchone()[0]
            out.append(d)
            if len(out) >= 60:
                break
        return out


def my_orgs(uid: str) -> list[dict]:
    with db.read() as c:
        rows = c.execute("SELECT o.*, m.role FROM org_members m JOIN organisations o ON o.id = m.org_id WHERE m.user_id = ? ORDER BY o.name", (uid,)).fetchall()
        return [dict(_org_public(r), my_role=r["role"]) for r in rows]


def request_verification(uid: str, oid: str, evidence: str) -> dict:
    with db.tx() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid, owner=True)
        if row["verification_status"] == "verified":
            raise HTTPException(409, "Already verified.")
        c.execute("UPDATE organisations SET verification_status = 'pending', verification_evidence = ?, verification_note = '', updated_at = ? WHERE id = ?",
                  (evidence.strip(), now(), row["id"]))
    return org_detail(oid, uid)


def admin_queue(uid: str) -> list[dict]:
    if not auth.is_admin(uid):
        raise HTTPException(403, "Platform administrators only.")
    with db.read() as c:
        return [dict(_org_public(r), verification_evidence=r["verification_evidence"])
                for r in c.execute("SELECT * FROM organisations WHERE verification_status = 'pending' ORDER BY updated_at")]


def admin_review(uid: str, oid: str, decision: str, note: str) -> dict:
    if not auth.is_admin(uid):
        raise HTTPException(403, "Platform administrators only.")
    with db.tx() as c:
        row = _org(c, oid)
        if row["verification_status"] != "pending":
            raise HTTPException(409, "No pending verification request.")
        status = "verified" if decision == "approve" else "rejected"
        c.execute("UPDATE organisations SET verification_status = ?, verification_note = ?, verified_at = ?, verified_by = ?, updated_at = ? WHERE id = ?",
                  (status, note.strip(), now() if status == "verified" else None, uid if status == "verified" else None, now(), row["id"]))
        owners = [r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id = ? AND role = 'owner'", (row["id"],))]
        notify(c, owners, "verification", f"Verification {status}: {row['name']}", note.strip(), f"#/org/{row['id']}")
    return {"status": status}


def create_staff_invite(uid: str, oid: str) -> dict:
    with db.tx() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid, owner=True)
        code = secrets.token_urlsafe(12)
        c.execute("INSERT INTO org_invites VALUES (?,?,?,?,?,NULL,NULL)", (auth._hash(code), row["id"], uid, now(), now() + 7 * 86400))
    return {"code": code, "expires_in_days": 7}


def accept_staff_invite(uid: str, code: str) -> dict:
    with db.tx() as c:
        inv = c.execute("SELECT * FROM org_invites WHERE code_hash = ?", (auth._hash(code or ""),)).fetchone()
        if not inv or inv["used_at"] or inv["expires_at"] < now():
            raise HTTPException(400, "This invite is invalid, used or expired.")
        if org_role(c, inv["org_id"], uid):
            raise HTTPException(409, "You're already on this organisation's team.")
        c.execute("INSERT INTO org_members VALUES (?,?,?,?)", (inv["org_id"], uid, "staff", now()))
        c.execute("UPDATE org_invites SET used_by = ?, used_at = ? WHERE code_hash = ?", (uid, now(), inv["code_hash"]))
        for r in c.execute("SELECT id FROM circles WHERE org_id = ? AND status = 'active'", (inv["org_id"],)).fetchall():
            c.execute("INSERT INTO memberships VALUES (?,?,?,?,?) ON CONFLICT(circle_id, user_id) DO UPDATE SET role = 'moderator', status = 'active'",
                      (r["id"], uid, "moderator", "active", now()))
    return {"org_id": inv["org_id"]}


def team(uid: str, oid: str) -> list[dict]:
    with db.read() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid)
        return [{"user_id": r["user_id"], "role": r["role"], "name": r["alias"] or (r["email"] or "").split("@")[0], "me": r["user_id"] == uid}
                for r in c.execute("""SELECT m.user_id, m.role, p.alias, a.email FROM org_members m LEFT JOIN profiles p ON p.user_id = m.user_id
                                      LEFT JOIN accounts a ON a.user_id = m.user_id WHERE m.org_id = ? ORDER BY m.created_at""", (row["id"],))]


def remove_staff(uid: str, oid: str, target: str) -> dict:
    with db.tx() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid, owner=True)
        if target == uid:
            raise HTTPException(400, "Owners can't remove themselves.")
        c.execute("DELETE FROM org_members WHERE org_id = ? AND user_id = ? AND role = 'staff'", (row["id"], target))
    return {"ok": True}


def dashboard(uid: str, oid: str) -> dict:
    with db.read() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid)
        ev = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM events WHERE org_id = ? GROUP BY status", (row["id"],))}
        rs = c.execute("""SELECT COUNT(*) FILTER (WHERE r.status = 'going') going, COUNT(*) FILTER (WHERE r.attended = 1) attended,
                          COUNT(*) FILTER (WHERE r.attended IS NOT NULL) marked
                          FROM event_rsvps r JOIN events e ON e.id = r.event_id WHERE e.org_id = ?""", (row["id"],)).fetchone()
        fb = c.execute("SELECT COUNT(*) n, AVG(rating) avg FROM event_feedback f JOIN events e ON e.id = f.event_id WHERE e.org_id = ?", (row["id"],)).fetchone()
        circ = c.execute("""SELECT COUNT(DISTINCT c.id) circles, COUNT(m.user_id) FILTER (WHERE m.status = 'active') members,
                            COUNT(m.user_id) FILTER (WHERE m.status = 'pending') pending
                            FROM circles c LEFT JOIN memberships m ON m.circle_id = c.id WHERE c.org_id = ? AND c.status = 'active'""", (row["id"],)).fetchone()
        events = [_event_card(c, e) for e in c.execute("SELECT * FROM events WHERE org_id = ? ORDER BY starts_at DESC LIMIT 100", (row["id"],))]
        circles = [dict(id=r["id"], name=r["name"], visibility=r["visibility"], members=r["n"], pending=r["p"]) for r in c.execute(
            """SELECT c.id, c.name, c.visibility, COUNT(m.user_id) FILTER (WHERE m.status = 'active') n,
               COUNT(m.user_id) FILTER (WHERE m.status = 'pending') p FROM circles c LEFT JOIN memberships m ON m.circle_id = c.id
               WHERE c.org_id = ? AND c.status = 'active' GROUP BY c.id ORDER BY c.created_at DESC""", (row["id"],))]
    programs = org_programs(uid, row["id"])
    return {"org": _org_public(row), "my_role": org_role_ro(row["id"], uid),
            "stats": {"events": ev, "going": rs["going"] or 0, "attended": rs["attended"] or 0, "attendance_marked": rs["marked"] or 0,
                      "feedback_count": fb["n"] or 0, "feedback_avg": round(fb["avg"], 2) if fb["avg"] else None,
                      "circles": circ["circles"] or 0, "circle_members": circ["members"] or 0, "pending_requests": circ["pending"] or 0,
                      "programmes": len(programs), "participants": sum(p["participants"] for p in programs)},
            "events": events, "circles": circles, "programmes": programs}


def org_role_ro(oid, uid):
    with db.read() as c:
        return org_role(c, oid, uid)


# ---------------------------------------------------------------- organisation programmes (existing organizer flow)
def org_programs(uid: str, oid: str) -> list[dict]:
    with db.read() as c:
        _require_staff(c, oid, uid)
    out = []
    for p in store.list_programs():
        doc = store.get(p["id"])
        if doc and doc.get("org_id") == oid:
            out.append({"id": doc["id"], "name": doc.get("name"), "participants": len(doc.get("participants", [])),
                        "groups": len((doc.get("bridges") or {}).get("groups", [])),
                        "approved_plans": sum(1 for s in (doc.get("plans") or {}).values() if s.get("approved")),
                        "circles": doc.get("circles", {}), "updated": doc.get("updated")})
    return out


def create_org_program(uid: str, oid: str, name: str) -> dict:
    with db.read() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid)
    from .planner import DEFAULT_CONSTRAINTS
    return store.save({"name": name, "location": row["service_area"], "org_id": row["id"], "participants": [],
                       "constraints": dict(DEFAULT_CONSTRAINTS), "grouping": {"min_size": 2, "max_size": 6, "same_area_only": False}})


def can_access_program(doc: dict, uid: str | None) -> bool:
    oid = doc.get("org_id")
    if not oid:
        return True  # legacy demo programmes created before organisations existed
    with db.read() as c:
        return bool(org_role(c, oid, uid))


def circle_from_group(uid: str, oid: str, pid: str, gid: str, name: str) -> dict:
    """Turn an organiser-reviewed programme group into a real, invite-only organisation Circle.
    Participants accept by opening the invite link with their own account; staff approve requests."""
    from .circles import verify_signals
    doc = store.get(pid)
    if not doc or doc.get("org_id") != oid:
        raise HTTPException(404, "Programme not found.")
    with db.read() as c:
        _require_staff(c, oid, uid)
    g = next((x for x in (doc.get("bridges") or {}).get("groups", []) if x["id"] == gid), None)
    if not g:
        raise HTTPException(404, "Group not found — run discovery first.")
    if (doc.get("circles") or {}).get(gid):
        raise HTTPException(409, {"message": "This group already has a Circle.", "circle_id": doc["circles"][gid]})
    label = g.get("primary_theme") or "Community"
    sigs, seen = [], set()
    for m in g["members"]:
        for r in m.get("resolved", []):
            if r["id"] not in seen and len(sigs) < 6:
                ok, _ = verify_signals(r.get("label") or r["name"], None, [{"id": r["id"]}])
                for s in ok:
                    seen.add(s["id"]); sigs.append(s)
    cid = "C" + uuid.uuid4().hex[:10]
    code = secrets.token_urlsafe(9)
    with db.tx() as c:
        staff = [r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id = ?", (oid,))]
        c.execute("""INSERT INTO circles (id, name, purpose, topic_label, topic_key, category, visibility, meeting_mode, area, area_key,
                     intents, accessibility, capacity, min_size, member_events, host_id, created_at, invite_code, org_id, join_policy, updated_at)
                     VALUES (?,?,?,?,?,'general','private','either',?,?, '["enjoy"]','["flexible_participation"]',?,2,1,?,?,?,?,'auto',?)""",
                  (cid, name.strip()[:80] or f"{label} Circle", f"Organisation Circle from programme “{doc.get('name')}”.", label,
                   "label:" + norm(label), doc.get("location", ""), "", max(3, min(50, len(g["members"]) + 4)), uid, now(), code, oid, now()))
        for s in sigs:
            c.execute("INSERT OR IGNORE INTO circle_signals VALUES (?,?,?,?,?)", (cid, s["id"], s["kind"], s["name"], s["type"]))
        for s_uid in staff:
            c.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (cid, s_uid, "host" if s_uid == uid else "moderator", "active", now()))
    doc.setdefault("circles", {})[gid] = cid
    store.save(doc)
    return {"circle_id": cid, "invite_code": code}


# ---------------------------------------------------------------- events
# Browsers still report some legacy IANA names (e.g. Chrome in India says "Asia/Calcutta").
TZ_ALIASES = {"Asia/Calcutta": "Asia/Kolkata", "Asia/Katmandu": "Asia/Kathmandu", "Asia/Saigon": "Asia/Ho_Chi_Minh",
              "Asia/Rangoon": "Asia/Yangon", "Europe/Kiev": "Europe/Kyiv", "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
              "Pacific/Truk": "Pacific/Chuuk", "Atlantic/Faeroe": "Atlantic/Faroe", "Etc/GMT": "UTC", "GMT": "UTC"}


def _tz(tzname: str) -> ZoneInfo:
    for name in (tzname, TZ_ALIASES.get(tzname or "")):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    raise HTTPException(422, f"Unknown timezone “{tzname}”. Use an IANA name such as Asia/Kolkata or Europe/London.")


def _local(s: str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{field}: enter a valid date and time.")
    return d.replace(tzinfo=None)


def _abs(e) -> tuple[datetime, datetime]:
    tz = _tz(e["timezone"])
    return _local(e["starts_at"], "Start").replace(tzinfo=tz), _local(e["ends_at"], "End").replace(tzinfo=tz)


def _is_past(e) -> bool:
    try:
        return _abs(e)[1] < datetime.now(_tz(e["timezone"]))
    except HTTPException:
        return False


def _validate_event(d: dict, existing=None) -> dict:
    v = {k: d.get(k, existing[k] if existing else None) for k in EVENT_FIELDS}
    from .uploads import media_url
    v["image_url"] = media_url(v["image_url"])
    if not v["title"] or not (3 <= len(v["title"].strip()) <= 120):
        raise HTTPException(422, "Title must be 3–120 characters.")
    tz = _tz(v["timezone"] or "")
    s, e = _local(v["starts_at"], "Start"), _local(v["ends_at"], "End")
    if e <= s:
        raise HTTPException(422, "End time must be after the start time.")
    if e - s > timedelta(days=14):
        raise HTTPException(422, "Events can last at most 14 days.")
    if v["rsvp_deadline"]:
        dl = _local(v["rsvp_deadline"], "RSVP deadline")
        if dl > s:
            raise HTTPException(422, "RSVP deadline must be before the event starts.")
        v["rsvp_deadline"] = dl.isoformat(timespec="minutes")
    cap = v["capacity"]
    if not isinstance(cap, int) or not 1 <= cap <= 5000:
        raise HTTPException(422, "Capacity must be between 1 and 5000.")
    status = v["location_status"] or "tbc"
    if status not in ("tbc", "confirmed", "online"):
        raise HTTPException(422, "Invalid location status.")
    if status == "confirmed" and not (v["address"] or "").strip():
        raise HTTPException(422, "A confirmed location needs a real address.")
    if status == "online":
        v["online_url"] = _safe_url(v["online_url"])
        v.update(address="", lat=None, lon=None, geo_source="", venue_name=v["venue_name"] or "")
    if status == "tbc":
        v.update(lat=None, lon=None, geo_source="")
    if (v["lat"] is None) != (v["lon"] is None):
        raise HTTPException(422, "Provide both latitude and longitude, or neither.")
    if v["lat"] is not None:
        if not (-90 <= v["lat"] <= 90 and -180 <= v["lon"] <= 180):
            raise HTTPException(422, "Coordinates are out of range.")
        if v["geo_source"] == "nominatim" and not geo.came_from_geocoder(v["lat"], v["lon"]):
            v["geo_source"] = "organiser"  # we didn't see this geocoder result — label it as organiser-entered
        elif v["geo_source"] == "qloo" and existing is not None and existing["geo_source"] == "qloo" \
                and existing["lat"] == v["lat"] and existing["lon"] == v["lon"]:
            pass  # unchanged coordinates that came from a Qloo place result
        elif v["geo_source"] not in ("nominatim", "organiser"):
            v["geo_source"] = "organiser"
    else:
        v["geo_source"] = ""
    if v["min_age"] is not None and not 0 <= v["min_age"] <= 120:
        raise HTTPException(422, "Minimum age is invalid.")
    v.update(starts_at=s.isoformat(timespec="minutes"), ends_at=e.isoformat(timespec="minutes"), timezone=str(tz.key), location_status=status)
    for k in ("description", "purpose", "category", "venue_name", "address", "cost_note", "materials", "accessibility", "requirements", "safety", "online_url"):
        v[k] = (v[k] or "").strip()
    return v


def _rsvp_users(c, eid, statuses=("going", "maybe")):
    q = f"SELECT user_id FROM event_rsvps WHERE event_id = ? AND status IN ({','.join('?' * len(statuses))})"
    return [r[0] for r in c.execute(q, (eid, *statuses))]


def create_org_event(uid: str, oid: str, data: dict) -> dict:
    with db.tx() as c:
        row = _org(c, oid)
        _require_staff(c, row["id"], uid)
        v = _validate_event(data)
        eid = "V" + uuid.uuid4().hex[:10]
        c.execute(f"""INSERT INTO events (id, owner_kind, org_id, {', '.join(EVENT_FIELDS)}, status, visibility, created_by, created_at, updated_at)
                      VALUES (?, 'org', ?, {', '.join('?' * len(EVENT_FIELDS))}, 'draft', 'public', ?, ?, ?)""",
                  (eid, row["id"], *[v[k] for k in EVENT_FIELDS], uid, now(), now()))
        c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, created_at) VALUES (?,?,?,?,?)",
                  (eid, uid, "created", "Draft created", now()))
    return get_event(eid, uid)


def _event_row(c, eid):
    e = c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
    if not e:
        raise HTTPException(404, "Event not found.")
    return e


def _can_manage(c, e, uid) -> bool:
    if not uid:
        return False
    if e["owner_kind"] == "org":
        return bool(org_role(c, e["org_id"], uid))
    m = c.execute("SELECT * FROM memberships WHERE circle_id = ? AND user_id = ?", (e["circle_id"], uid)).fetchone()
    return _is_mod(m)


def _can_view(c, e, uid) -> bool:
    if _can_manage(c, e, uid):
        return True
    if e["status"] == "draft":
        return False
    if e["visibility"] == "public":
        return True
    m = c.execute("SELECT status FROM memberships WHERE circle_id = ? AND user_id = ?", (e["circle_id"], uid)).fetchone() if uid else None
    return bool(m and m["status"] == "active")


def update_event(uid: str, eid: str, data: dict, reason: str = "") -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Only the organisers can edit this event.")
        if e["status"] in ("cancelled", "completed"):
            raise HTTPException(409, f"This event is {e['status']} and can't be edited.")
        v = _validate_event(data, e)
        going = c.execute("SELECT COUNT(*) FROM event_rsvps WHERE event_id = ? AND status = 'going'", (eid,)).fetchone()[0]
        if v["capacity"] < going:
            raise HTTPException(409, f"{going} people are already going — capacity can't be lower than that.")
        changed = [k for k in EVENT_FIELDS if str(v[k] if v[k] is not None else "") != str(e[k] if e[k] is not None else "")]
        if not changed:
            return get_event(eid, uid)
        c.execute(f"UPDATE events SET {', '.join(k + ' = ?' for k in EVENT_FIELDS)}, updated_at = ? WHERE id = ?",
                  (*[v[k] for k in EVENT_FIELDS], now(), eid))
        material = [k for k in changed if k in MATERIAL]
        msg = "Updated: " + ", ".join(k.replace("_", " ") for k in changed)
        kind = "location_confirmed" if "location_status" in changed and v["location_status"] == "confirmed" else "updated"
        c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, reason, created_at) VALUES (?,?,?,?,?,?)",
                  (eid, uid, kind, msg, reason.strip()[:300], now()))
        if e["status"] == "published" and material:
            notify(c, _rsvp_users(c, eid), "event_update", f"Event updated: {v['title']}",
                   (reason.strip() or msg)[:300], f"#/e/{eid}")
    return get_event(eid, uid)


def publish_event(uid: str, eid: str) -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Only the organisers can publish this event.")
        if e["status"] != "draft":
            raise HTTPException(409, "Only drafts can be published.")
        if _is_past(e):
            raise HTTPException(409, "This event's time has already passed — edit the date first.")
        c.execute("UPDATE events SET status = 'published', published_at = ?, updated_at = ? WHERE id = ?", (now(), now(), eid))
        c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, created_at) VALUES (?,?,?,?,?)", (eid, uid, "published", "Published", now()))
    return get_event(eid, uid)


def cancel_event_v(uid: str, eid: str, reason: str) -> dict:
    if len((reason or "").strip()) < 3:
        raise HTTPException(422, "Please give attendees a short reason for cancelling.")
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Only the organisers can cancel this event.")
        if e["status"] in ("cancelled", "completed"):
            raise HTTPException(409, f"Event is already {e['status']}.")
        c.execute("UPDATE events SET status = 'cancelled', cancel_reason = ?, updated_at = ? WHERE id = ?", (reason.strip(), now(), eid))
        c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, reason, created_at) VALUES (?,?,?,?,?,?)",
                  (eid, uid, "cancelled", "Event cancelled", reason.strip(), now()))
        notify(c, _rsvp_users(c, eid), "event_cancelled", f"Cancelled: {e['title']}", reason.strip(), f"#/e/{eid}")
    return get_event(eid, uid)


def complete_event(uid: str, eid: str) -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Only the organisers can do that.")
        if e["status"] != "published":
            raise HTTPException(409, "Only published events can be completed.")
        if _abs(e)[0] > datetime.now(_tz(e["timezone"])):
            raise HTTPException(409, "The event hasn't started yet.")
        c.execute("UPDATE events SET status = 'completed', updated_at = ? WHERE id = ?", (now(), eid))
        c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, created_at) VALUES (?,?,?,?,?)", (eid, uid, "completed", "Marked as completed", now()))
        notify(c, _rsvp_users(c, eid, ("going",)), "feedback", f"How was {e['title']}?", "Share quick feedback with the organisers.", f"#/e/{eid}")
    return get_event(eid, uid)


def rsvp_v(uid: str, eid: str, status: str) -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_view(c, e, uid) or e["status"] == "draft":
            raise HTTPException(404, "Event not found.")
        if e["status"] != "published":
            raise HTTPException(409, f"RSVPs are closed — this event is {e['status']}.")
        tz = _tz(e["timezone"])
        nowl = datetime.now(tz)
        if _abs(e)[0] <= nowl:
            raise HTTPException(409, "This event has already started.")
        if e["rsvp_deadline"] and _local(e["rsvp_deadline"], "deadline").replace(tzinfo=tz) < nowl:
            raise HTTPException(409, "The RSVP deadline has passed.")
        if status == "going":
            going = c.execute("SELECT COUNT(*) FROM event_rsvps WHERE event_id = ? AND status = 'going' AND user_id <> ?", (eid, uid)).fetchone()[0]
            if going >= e["capacity"]:
                raise HTTPException(409, "This event is full.")
        c.execute("INSERT INTO event_rsvps (event_id, user_id, status, updated_at) VALUES (?,?,?,?) "
                  "ON CONFLICT(event_id, user_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
                  (eid, uid, status, now()))
    return get_event(eid, uid)


def participants(uid: str, eid: str) -> list[dict]:
    with db.read() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Organisers only.")
        rows = c.execute("""SELECT r.user_id, r.status, r.attended, r.updated_at, p.alias, a.email FROM event_rsvps r
                            LEFT JOIN profiles p ON p.user_id = r.user_id LEFT JOIN accounts a ON a.user_id = r.user_id
                            WHERE r.event_id = ? ORDER BY r.status, r.updated_at""", (eid,)).fetchall()
        # Emails are never shown to organisers; aliases (or an anonymous label) only.
        return [{"user_id": r["user_id"], "name": r["alias"] or "Participant", "status": r["status"],
                 "attended": None if r["attended"] is None else bool(r["attended"]), "updated_at": r["updated_at"]} for r in rows]


def mark_attendance(uid: str, eid: str, target: str, attended: bool) -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if not _can_manage(c, e, uid):
            raise HTTPException(403, "Organisers only.")
        if _abs(e)[0] > datetime.now(_tz(e["timezone"])):
            raise HTTPException(409, "Attendance can be recorded once the event has started.")
        n = c.execute("UPDATE event_rsvps SET attended = ? WHERE event_id = ? AND user_id = ?", (int(attended), eid, target)).rowcount
        if not n:
            raise HTTPException(404, "That person hasn't RSVP'd.")
    return {"ok": True}


def feedback(uid: str, eid: str, rating: int, comment: str) -> dict:
    with db.tx() as c:
        e = _event_row(c, eid)
        if e["status"] != "completed":
            raise HTTPException(409, "Feedback opens once the event is completed.")
        r = c.execute("SELECT status, attended FROM event_rsvps WHERE event_id = ? AND user_id = ?", (eid, uid)).fetchone()
        if not r or (r["status"] != "going" and r["attended"] != 1):
            raise HTTPException(403, "Only people who attended can leave feedback.")
        c.execute("INSERT OR REPLACE INTO event_feedback VALUES (?,?,?,?,?)", (eid, uid, rating, comment.strip()[:1000], now()))
    return get_event(eid, uid)


def _event_card(c, e) -> dict:
    going = c.execute("SELECT COUNT(*) FROM event_rsvps WHERE event_id = ? AND status = 'going'", (e["id"],)).fetchone()[0]
    owner = None
    if e["owner_kind"] == "org":
        o = c.execute("SELECT name, slug, verification_status FROM organisations WHERE id = ?", (e["org_id"],)).fetchone()
        owner = {"kind": "org", "id": e["org_id"], "name": o["name"], "slug": o["slug"], "verification_status": o["verification_status"]} if o else None
    else:
        ci = c.execute("SELECT name FROM circles WHERE id = ?", (e["circle_id"],)).fetchone()
        owner = {"kind": "circle", "name": ci["name"] if ci else "Circle", "circle_id": e["circle_id"]}
    status = e["status"]
    display = status
    if status == "published" and _is_past(e):
        display = "past"
    elif status == "published" and going >= e["capacity"]:
        display = "full"
    return {"id": e["id"], "title": e["title"], "category": e["category"], "starts_at": e["starts_at"], "ends_at": e["ends_at"],
            "timezone": e["timezone"], "status": status, "display_status": display, "location_status": e["location_status"],
            "venue_name": e["venue_name"], "address": e["address"] if e["location_status"] == "confirmed" else "",
            "capacity": e["capacity"], "going": going, "owner": owner, "visibility": e["visibility"], "image_url": e["image_url"]}


def get_event(eid: str, uid: str | None) -> dict:
    with db.read() as c:
        e = _event_row(c, eid)
        if not _can_view(c, e, uid):
            raise HTTPException(404, "Event not found.")
        d = _event_card(c, e)
        manage = _can_manage(c, e, uid)
        d.update({k: e[k] for k in ("description", "purpose", "online_url", "rsvp_deadline", "cost_note", "materials",
                                     "accessibility", "requirements", "min_age", "safety", "cancel_reason", "created_at",
                                     "updated_at", "published_at", "geo_source", "proposal_id")})
        if e["location_status"] == "confirmed" and e["lat"] is not None:
            d["map"] = {"lat": e["lat"], "lon": e["lon"], "source": e["geo_source"]}
        if manage:
            d.update(lat=e["lat"], lon=e["lon"], raw_address=e["address"])
        rs = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM event_rsvps WHERE event_id = ? GROUP BY status", (eid,))}
        mine = c.execute("SELECT status, attended FROM event_rsvps WHERE event_id = ? AND user_id = ?", (eid, uid)).fetchone() if uid else None
        fb = c.execute("SELECT COUNT(*) n, AVG(rating) avg FROM event_feedback WHERE event_id = ?", (eid,)).fetchone()
        my_fb = c.execute("SELECT rating, comment FROM event_feedback WHERE event_id = ? AND user_id = ?", (eid, uid)).fetchone() if uid else None
        d["rsvp_counts"] = rs
        d["my_rsvp"] = mine["status"] if mine else None
        d["feedback"] = {"count": fb["n"], "avg": round(fb["avg"], 2) if fb["avg"] else None, "mine": dict(my_fb) if my_fb else None}
        d["updates"] = [dict(r) for r in c.execute("SELECT kind, message, reason, created_at FROM event_updates WHERE event_id = ? ORDER BY id DESC LIMIT 30", (eid,))]
        d["can_manage"] = manage
        if e["owner_kind"] == "org":
            o = c.execute("SELECT contact_kind, contact_value FROM organisations WHERE id = ?", (e["org_id"],)).fetchone()
            d["contact"] = {"kind": o["contact_kind"], "value": o["contact_value"]} if o and o["contact_kind"] else None
        else:
            d["contact"] = {"kind": "circle_chat", "value": f"#/c/{e['circle_id']}/chat"}
        tz = _tz(e["timezone"])
        nowl = datetime.now(tz)
        d["rsvp_open"] = (e["status"] == "published" and _abs(e)[0] > nowl and
                          not (e["rsvp_deadline"] and _local(e["rsvp_deadline"], "d").replace(tzinfo=tz) < nowl))
        return d


def public_events(q: str = "", area: str = "") -> list[dict]:
    with db.read() as c:
        rows = c.execute("SELECT * FROM events WHERE status = 'published' AND visibility = 'public' ORDER BY starts_at LIMIT 300").fetchall()
        out = []
        qn, an = norm(q), norm(area)
        for e in rows:
            if _is_past(e):
                continue
            hay = norm(" ".join(str(e[k] or "") for k in ("title", "description", "category", "address", "venue_name")))
            if qn and qn not in hay:
                continue
            if an and e["location_status"] == "confirmed" and not set(an.split()) & set(norm(e["address"]).split()):
                continue
            out.append(_event_card(c, e))
        return out[:60]


def my_activities(uid: str) -> dict:
    with db.read() as c:
        mine = c.execute("""SELECT e.*, r.status AS my FROM event_rsvps r JOIN events e ON e.id = r.event_id
                            WHERE r.user_id = ? ORDER BY e.starts_at""", (uid,)).fetchall()
        circ = c.execute("""SELECT e.* FROM events e JOIN memberships m ON m.circle_id = e.circle_id AND m.user_id = ? AND m.status = 'active'
                            WHERE e.status = 'published' ORDER BY e.starts_at""", (uid,)).fetchall()
        ids = {e["id"] for e in mine}
        upcoming = [dict(_event_card(c, e), my_rsvp=e["my"]) for e in mine if not _is_past(e) and e["status"] == "published"]
        upcoming += [dict(_event_card(c, e), my_rsvp=None) for e in circ if e["id"] not in ids and not _is_past(e)]
        past = [dict(_event_card(c, e), my_rsvp=e["my"]) for e in mine if _is_past(e) or e["status"] in ("completed", "cancelled")]
        proposals = [dict(id=r["id"], title=r["title"], circle_id=r["circle_id"], circle_name=r["name"]) for r in c.execute(
            """SELECT ce.id, ce.title, ce.circle_id, ci.name FROM circle_events ce JOIN memberships m ON m.circle_id = ce.circle_id
               AND m.user_id = ? AND m.status = 'active' JOIN circles ci ON ci.id = ce.circle_id WHERE ce.status = 'proposed'
               ORDER BY ce.created_at DESC LIMIT 20""", (uid,))]
    upcoming.sort(key=lambda x: x["starts_at"])
    return {"upcoming": upcoming, "past": past[:30], "proposals": proposals}


def event_from_proposal(c, uid: str, proposal, concept: dict, time_iso: str, tzname: str, place, capacity: int, row,
                        location_confirmed: bool = True, note: str = "Confirmed by a Circle host from a member vote") -> str:
    """Create the real Circle event when a host confirms an activity proposal (called inside the confirm transaction).
    location_confirmed=False (agent auto-publish): the voted venue is shown as suggested, location stays 'to be confirmed'."""
    tz = _tz(tzname)
    start = _local(time_iso, "Time")
    end = start + timedelta(minutes=int(concept.get("duration_min") or 60))
    eid = "V" + uuid.uuid4().hex[:10]
    agenda = "\n".join(f"• {a['title']} ({a['minutes']} min): {a['detail']}" for a in concept.get("agenda", []))
    loc = ("confirmed" if location_confirmed else "tbc") if place else ("online" if row["meeting_mode"] == "online" else "tbc")
    pin = place is not None and loc == "confirmed"
    c.execute("""INSERT INTO events (id, owner_kind, circle_id, proposal_id, title, description, purpose, category, starts_at, ends_at,
                 timezone, location_status, venue_name, address, lat, lon, geo_source, capacity, cost_note, materials, accessibility,
                 safety, status, visibility, created_by, created_at, updated_at, published_at)
                 VALUES (?, 'circle', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 'members', ?, ?, ?, ?)""",
              (eid, row["id"], proposal["id"], concept["title"][:120], (concept.get("summary", "") + "\n\n" + agenda).strip(),
               f"Chosen by {row['name']} members from an activity proposal.", concept.get("format_name", ""),
               start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), tz.key, loc,
               place["name"] if place else "", place["address"] if place else "", place["lat"] if pin else None,
               place["lon"] if pin else None, place["geo_source"] if pin and place["lat"] is not None else "", capacity,
               f"~{(concept.get('cost_estimate') or {}).get('amount', 0)} total (planning estimate, not a quote)",
               ", ".join(concept.get("materials", [])), "; ".join(concept.get("accessibility", [])),
               "; ".join(concept.get("safeguards", [])), uid, now(), now(), now()))
    c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, created_at) VALUES (?,?,?,?,?)",
              (eid, uid, "published", note, now()))
    members = [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active'", (row["id"],))]
    notify(c, [m for m in members if m != uid], "event_confirmed", f"New event in {row['name']}: {concept['title']}",
           f"{start.strftime('%a %d %b, %H:%M')} — " + (place["name"] if place else "location to be confirmed"), f"#/e/{eid}")
    return eid


# ---------------------------------------------------------------- meeting-place polls
def _proposal(c, pid, uid):
    p = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "Proposal not found.")
    row, m = _circle_or_404(c, p["circle_id"], uid)
    if not _active(m):
        raise HTTPException(403, "Members only.")
    return p, row, m


def places(uid: str, pid: str) -> dict:
    with db.read() as c:
        _proposal(c, pid, uid)
        rows = c.execute("""SELECT pc.*, COUNT(v.user_id) votes, pr.alias FROM place_candidates pc
                            LEFT JOIN place_votes v ON v.place_id = pc.id LEFT JOIN profiles pr ON pr.user_id = pc.proposer_id
                            WHERE pc.proposal_id = ? GROUP BY pc.id ORDER BY votes DESC, pc.id""", (pid,)).fetchall()
        mine = c.execute("SELECT place_id FROM place_votes WHERE proposal_id = ? AND user_id = ?", (pid, uid)).fetchone()
        return {"places": [{"id": r["id"], "name": r["name"], "address": r["address"], "lat": r["lat"], "lon": r["lon"],
                            "geo_source": r["geo_source"], "url": r["url"], "cost_note": r["cost_note"],
                            "accessibility_note": r["accessibility_note"], "votes": r["votes"],
                            "proposer": r["alias"] or ("🤖 Planning agent" if r["source_ref"] else "Member"),
                            "source_ref": r["source_ref"], "validation": json.loads(r["validation"]) if r["validation"] else None}
                           for r in rows],
                "my_vote": mine["place_id"] if mine else None}


def add_place(uid: str, pid: str, data: dict) -> dict:
    with db.tx() as c:
        p, row, m = _proposal(c, pid, uid)
        if p["status"] != "proposed":
            raise HTTPException(409, "This proposal is closed.")
        if c.execute("SELECT COUNT(*) FROM place_candidates WHERE proposal_id = ?", (pid,)).fetchone()[0] >= 10:
            raise HTTPException(409, "This proposal already has 10 place options.")
        lat, lon, src = data.get("lat"), data.get("lon"), ""
        if lat is not None or lon is not None:
            if not geo.came_from_geocoder(lat, lon):
                raise HTTPException(422, "Map coordinates must come from the map search. Leave them out to add the address only.")
            src = "nominatim"
        try:
            c.execute("""INSERT INTO place_candidates (proposal_id, proposer_id, name, address, lat, lon, geo_source, url, cost_note,
                         accessibility_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (pid, uid, data["name"].strip(), data["address"].strip(), lat, lon, src, _safe_url(data.get("url", "")),
                       data.get("cost_note", "").strip(), data.get("accessibility_note", "").strip(), now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That place is already on the list.")
    return places(uid, pid)


def vote_place(uid: str, pid: str, place_id: int) -> dict:
    with db.tx() as c:
        p, row, m = _proposal(c, pid, uid)
        if p["status"] != "proposed":
            raise HTTPException(409, "Voting is closed.")
        if not c.execute("SELECT 1 FROM place_candidates WHERE id = ? AND proposal_id = ?", (place_id, pid)).fetchone():
            raise HTTPException(404, "Place not found.")
        c.execute("INSERT OR REPLACE INTO place_votes VALUES (?,?,?)", (pid, uid, place_id))
    return places(uid, pid)


# ---------------------------------------------------------------- Circle chat (persisted; clients poll)
def _thread_ok(c, cid: str, thread: str):
    if not thread:
        return
    kind, _, ref = thread.partition(":")
    if kind == "proposal":
        ok = c.execute("SELECT 1 FROM circle_events WHERE id = ? AND circle_id = ?", (ref, cid)).fetchone()
    elif kind == "event":
        ok = c.execute("SELECT 1 FROM events WHERE id = ? AND circle_id = ?", (ref, cid)).fetchone()
    else:
        ok = None
    if not ok:
        raise HTTPException(400, "Unknown thread.")


def messages(uid: str, cid: str, thread: str = "", after: int | None = None, before: int | None = None, limit: int = 40) -> dict:
    limit = max(1, min(limit, 100))
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to read its chat.")
        _thread_ok(c, cid, thread)
        mod = _is_mod(m)
        blocked = {r[0] for r in c.execute("SELECT blocked_id FROM blocks WHERE blocker_id = ?", (uid,))}
        q = """SELECT cm.*, p.alias, a.email IS NOT NULL AS has_acct FROM circle_messages cm LEFT JOIN profiles p ON p.user_id = cm.user_id
               LEFT JOIN accounts a ON a.user_id = cm.user_id WHERE cm.circle_id = ? AND cm.thread = ?"""
        args = [cid, thread]
        if after:
            q += " AND cm.id > ? ORDER BY cm.id ASC LIMIT ?"
            args += [after, limit]
            rows = c.execute(q, args).fetchall()
        else:
            if before:
                q += " AND cm.id < ?"
                args.append(before)
            q += " ORDER BY cm.id DESC LIMIT ?"
            args.append(limit + 1)
            rows = c.execute(q, args).fetchall()
            more = len(rows) > limit
            rows = list(reversed(rows[:limit]))
        out = [{"id": r["id"], "author": r["alias"] or ("Organisation staff" if r["user_id"] else "[deleted account]"),
                "author_id": r["user_id"], "mine": r["user_id"] == uid, "created_at": r["created_at"], "client_id": r["client_id"] if r["user_id"] == uid else None,
                "deleted": bool(r["deleted"]), "hidden": bool(r["hidden"]), "blocked": r["user_id"] in blocked,
                "body": "" if (r["deleted"] or r["user_id"] in blocked or (r["hidden"] and not mod)) else r["body"]} for r in rows]
        return {"messages": out, "has_more": (not after) and more, "can_moderate": mod, "server_time": now()}


def send_message(uid: str, cid: str, body: str, client_id: str, thread: str = "") -> dict:
    body = (body or "").strip()
    if not body:
        raise HTTPException(422, "Message is empty.")
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to chat.")
        _thread_ok(c, cid, thread)
        dup = c.execute("SELECT id FROM circle_messages WHERE circle_id = ? AND user_id = ? AND client_id = ?", (cid, uid, client_id)).fetchone()
        if dup:
            return {"id": dup["id"], "duplicate": True}
        cur = c.execute("INSERT INTO circle_messages (circle_id, user_id, thread, body, client_id, created_at) VALUES (?,?,?,?,?,?)",
                        (cid, uid, thread, body, client_id, now()))
    return {"id": cur.lastrowid, "duplicate": False}


def delete_message(uid: str, cid: str, mid: int) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        r = c.execute("SELECT * FROM circle_messages WHERE id = ? AND circle_id = ?", (mid, cid)).fetchone()
        if not r:
            raise HTTPException(404, "Message not found.")
        if r["user_id"] == uid and _active(m):
            c.execute("UPDATE circle_messages SET deleted = 1 WHERE id = ?", (mid,))
        elif _is_mod(m):
            c.execute("UPDATE circle_messages SET hidden = 1 WHERE id = ?", (mid,))
        else:
            raise HTTPException(403, "Not allowed.")
    return {"ok": True}


def report_message(uid: str, cid: str, mid: int, reason: str) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Members only.")
        if not c.execute("SELECT 1 FROM circle_messages WHERE id = ? AND circle_id = ?", (mid, cid)).fetchone():
            raise HTTPException(404, "Message not found.")
        try:
            c.execute("INSERT INTO reports (reporter_id, circle_id, target_type, target_id, reason, created_at) VALUES (?,?,?,?,?,?)",
                      (uid, cid, "message", str(mid), reason.strip(), now()))
        except sqlite3.IntegrityError:
            return {"ok": True, "already": True}
        mods = [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active' AND role IN ('host','moderator')", (cid,))]
        notify(c, mods, "report", f"New report in {row['name']}", "A chat message was reported.", f"#/c/{cid}/about")
    return {"ok": True}
