"""Self-serve individuals and community Circles.

Reuses: qloo_service (resolution + taste insights), bridges (traceable pair evidence), planner (activity agent).
Rules enforced here, in application code (never delegated to an LLM):
  * hard constraints (adult-only, capacity, blocks, exclusions, accessibility, meeting mode, area, language)
    are applied BEFORE any ranking; taste evidence can only re-order eligible Circles;
  * declared interests and Qloo-derived affinities are reported separately, with no similarity percentages;
  * Qloo IDs are only stored if the backend itself saw them in a Qloo resolution for that label.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import db, planner
from .bridges import describe_group, pair_evidence
from .qloo_client import QlooError
from .qloo_service import resolve_interest, taste_profile

INTENTS = ("enjoy", "teach", "learn", "discuss", "collaborate")
ACCESS = ("wheelchair", "quiet_space", "visual_aids", "captions", "flexible_participation")
AVAIL = ("weekday_daytime", "weekday_evening", "weekend")
PREFS = ("in_person", "online", "indoor", "outdoor")
TASTE_TTL = 24 * 3600

GUIDELINES = [
    "Be kind and assume good intent. No harassment, hate speech or personal attacks.",
    "Share only what you're comfortable with; never post others' private information.",
    "No selling, spam or recruiting for unrelated causes.",
    "Meet in public or organizer-approved places; you never have to share your address.",
    "Report anything that feels unsafe — moderators review every report.",
]
NOTICES = {
    "health": "This Circle is for peer discussion and support only. It is not a source of diagnosis, treatment "
              "or medical advice. Talk to a qualified professional about your own health, and contact local "
              "emergency services in an emergency.",
    "political": "This Circle discusses political and civic topics. Disagree respectfully, debate ideas not people, "
                 "and don't use the space for campaigning or recruiting.",
}
_HEALTH_WORDS = {"health", "diabetes", "cancer", "asthma", "arthritis", "dementia", "alzheimer", "autism", "adhd",
                 "anxiety", "depression", "mental", "disease", "illness", "chronic", "pain", "recovery", "heart",
                 "kidney", "thyroid", "pcos", "parkinson", "stroke", "disability", "wellbeing", "caregiving"}
_POLITICAL_WORDS = {"politics", "political", "election", "elections", "policy", "government", "civic", "democracy",
                    "parliament", "voting", "activism", "party"}


# ---------------------------------------------------------------- helpers
def now() -> float:
    return time.time()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def area_tokens(s: str) -> set:
    return {t for t in norm(s).split() if len(t) > 1}


def jl(v) -> str:
    return json.dumps(list(v or []))


def pl(s) -> list:
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def suggest_category(label: str, signals: list[dict]) -> str:
    words = set(norm(label).split())
    types = " ".join((s.get("type") or "") for s in signals)
    if words & _POLITICAL_WORDS or "political_preferences" in types:
        return "political"
    if words & _HEALTH_WORDS:
        return "health"
    return "general"


def _profile_row(c, uid):
    return c.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()


def _require_profile(c, uid):
    p = _profile_row(c, uid)
    if not p:
        raise HTTPException(403, "Create your profile first.")
    return p


def _interests(c, uid) -> list[dict]:
    rows = c.execute("SELECT * FROM profile_interests WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    out = []
    for r in rows:
        sig = c.execute("SELECT qloo_id, kind, name, type, source, retrieved_at FROM interest_signals "
                        "WHERE interest_id = ? ORDER BY qloo_id", (r["id"],)).fetchall()
        out.append({"id": r["id"], "label": r["label"], "intent": r["intent"],
                    "signals": [{"id": s["qloo_id"], "kind": s["kind"], "name": s["name"], "type": s["type"],
                                 "source": s["source"], "retrieved_at": s["retrieved_at"]} for s in sig]})
    return out


# ---------------------------------------------------------------- profile
def verify_signals(label: str, category: str | None, submitted: list[dict]) -> tuple[list[dict], str | None]:
    """Keep only signals that Qloo actually returned for this label (served from the backend cache when warm)."""
    if not submitted:
        return [], None
    try:
        res = resolve_interest(label, category)
    except QlooError as exc:
        return [], f"“{label}” saved without Qloo IDs: Qloo unavailable ({exc.status or 'error'})."
    known = {c["id"]: c for c in res.get("candidates", [])}
    keep = []
    for s in submitted[:4]:
        k = known.get(s.get("id"))
        if k:
            keep.append({"id": k["id"], "kind": k["kind"], "name": k.get("name") or label,
                         "type": k.get("type") or "", "source": k.get("source") or ""})
    warn = None if len(keep) == len(submitted[:4]) else f"Some Qloo IDs for “{label}” could not be verified and were dropped."
    return keep, warn


def save_profile(uid: str | None, data: dict) -> dict:
    """Create (uid=None) or update a profile. Returns {user_id, token?, profile, warnings}."""
    warnings = []
    interests = []
    seen = set()
    for it in data["interests"]:
        key = norm(it["label"])
        if not key or key in seen:
            continue
        seen.add(key)
        sig, w = verify_signals(it["label"], it.get("category"), it.get("signals") or [])
        if w:
            warnings.append(w)
        interests.append({"label": it["label"].strip()[:60], "intent": it["intent"], "signals": sig})
    token = None
    ts = now()
    with db.tx() as c:
        if uid is None:
            from .auth import create_user
            uid, token = create_user(c)
        existing = _profile_row(c, uid)
        consent_at = (existing["consent_at"] if existing and existing["discoverable"] and data["discoverable"]
                      else (ts if data["discoverable"] else None))
        c.execute("""INSERT INTO profiles (user_id, alias, area, show_area, share_interests, bio, language, budget_max,
                       availability, activity_prefs, accessibility, exclude_topics, adult_confirmed, discoverable, consent_at, updated_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET alias=excluded.alias, area=excluded.area, show_area=excluded.show_area,
                       share_interests=excluded.share_interests, bio=excluded.bio, language=excluded.language,
                       budget_max=excluded.budget_max, availability=excluded.availability, activity_prefs=excluded.activity_prefs,
                       accessibility=excluded.accessibility, exclude_topics=excluded.exclude_topics,
                       adult_confirmed=excluded.adult_confirmed, discoverable=excluded.discoverable,
                       consent_at=excluded.consent_at, updated_at=excluded.updated_at""",
                  (uid, data["alias"], data.get("area", ""), int(data.get("show_area", False)),
                   int(data.get("share_interests", False)), data.get("bio", ""), data.get("language", ""),
                   data.get("budget_max"), jl(data.get("availability")), jl(data.get("activity_prefs")),
                   jl(data.get("accessibility")), jl(data.get("exclude_topics")), 1, int(data["discoverable"]),
                   consent_at, ts))
        c.execute("DELETE FROM profile_interests WHERE user_id = ?", (uid,))
        for it in interests:
            cur = c.execute("INSERT INTO profile_interests (user_id, label, intent) VALUES (?,?,?)",
                            (uid, it["label"], it["intent"]))
            for s in it["signals"]:
                c.execute("INSERT OR IGNORE INTO interest_signals VALUES (?,?,?,?,?,?,?)",
                          (cur.lastrowid, s["id"], s["kind"], s["name"], s["type"], s["source"], ts))
        if not data["discoverable"]:
            c.execute("DELETE FROM user_taste WHERE user_id = ?", (uid,))
    out = {"user_id": uid, "profile": get_profile(uid), "warnings": warnings}
    if token:
        out["token"] = token
    return out


def get_profile(uid: str) -> dict:
    with db.read() as c:
        p = _profile_row(c, uid)
        if not p:
            raise HTTPException(404, "No profile yet.")
        d = dict(p)
        for k in ("availability", "activity_prefs", "accessibility", "exclude_topics"):
            d[k] = pl(d[k])
        d["show_area"], d["share_interests"], d["discoverable"] = bool(d["show_area"]), bool(d["share_interests"]), bool(d["discoverable"])
        d["interests"] = _interests(c, uid)
        t = c.execute("SELECT retrieved_at FROM user_taste WHERE user_id = ?", (uid,)).fetchone()
        d["taste_retrieved_at"] = t["retrieved_at"] if t else None
        return d


def set_discovery(uid: str, on: bool) -> dict:
    with db.tx() as c:
        _require_profile(c, uid)
        c.execute("UPDATE profiles SET discoverable = ?, consent_at = ?, updated_at = ? WHERE user_id = ?",
                  (int(on), now() if on else None, now(), uid))
        if not on:
            c.execute("DELETE FROM user_taste WHERE user_id = ?", (uid,))
    return get_profile(uid)


def delete_account(uid: str) -> dict:
    """Policy: profile, interests, Qloo mappings, taste cache, memberships, votes, RSVPs and blocks are deleted.
    Posts are erased (body removed, author detached) so replies keep their thread. Hosted Circles pass to the
    longest-standing moderator/member, or are archived if empty."""
    with db.tx() as c:
        hosted = [r["circle_id"] for r in c.execute(
            "SELECT circle_id FROM memberships WHERE user_id = ? AND role = 'host' AND status = 'active'", (uid,))]
        for cid in hosted:
            _transfer_host(c, cid, uid)
        c.execute("UPDATE posts SET body = '', deleted = 1, user_id = NULL WHERE user_id = ?", (uid,))
        c.execute("DELETE FROM users WHERE id = ?", (uid,))
    return {"deleted": True, "circles_transferred_or_archived": len(hosted)}


def _transfer_host(c, cid, uid):
    nxt = c.execute("""SELECT user_id FROM memberships WHERE circle_id = ? AND user_id <> ? AND status = 'active'
                       ORDER BY CASE role WHEN 'moderator' THEN 0 ELSE 1 END, joined_at LIMIT 1""", (cid, uid)).fetchone()
    if nxt:
        c.execute("UPDATE memberships SET role = 'host' WHERE circle_id = ? AND user_id = ?", (cid, nxt["user_id"]))
        c.execute("UPDATE circles SET host_id = ? WHERE id = ?", (nxt["user_id"], cid))
    else:
        c.execute("UPDATE circles SET status = 'archived', host_id = NULL WHERE id = ?", (cid,))


# ---------------------------------------------------------------- taste (Qloo Insights)
def _taste(uid: str, interests: list[dict]) -> tuple[dict | None, str | None]:
    resolved = [{"kind": s["kind"], "id": s["id"], "name": s["name"], "type": s["type"]}
                for it in interests for s in it["signals"]]
    if not resolved:
        return None, None
    sig = hashlib.sha1(",".join(sorted(r["id"] for r in resolved)).encode()).hexdigest()
    with db.read() as c:
        row = c.execute("SELECT taste, retrieved_at FROM user_taste WHERE user_id = ?", (uid,)).fetchone()
    if row:
        cached = json.loads(row["taste"])
        if cached.get("sig") == sig and now() - row["retrieved_at"] < TASTE_TTL:
            return cached, None
    try:
        prof = taste_profile(resolved)
    except QlooError as exc:
        return None, f"Qloo taste insights unavailable ({exc.status or 'error'}); matching on declared interests only."
    taste = {"sig": sig, "tags": [{"id": t["id"], "name": t["name"]} for t in prof.get("tags", []) if t.get("id")],
             "entities": [{"id": e["id"], "name": e["name"], "type": e.get("type")} for e in prof.get("entities", []) if e.get("id")],
             "requests": prof.get("requests", []), "warnings": prof.get("warnings", [])}
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO user_taste VALUES (?,?,?)", (uid, json.dumps(taste), now()))
    partial = prof.get("warnings") or []
    return taste, (f"Some Qloo taste insights were unavailable ({len(partial)} request(s) failed); "
                   "recommendations use the Qloo data that was returned." if partial else None)


# ---------------------------------------------------------------- circles: read models
def _summary(c, row) -> dict:
    count = c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (row["id"],)).fetchone()[0]
    sig = c.execute("SELECT qloo_id, kind, name, type FROM circle_signals WHERE circle_id = ?", (row["id"],)).fetchall()
    return {"id": row["id"], "name": row["name"], "purpose": row["purpose"], "topic_label": row["topic_label"],
            "category": row["category"], "visibility": row["visibility"], "meeting_mode": row["meeting_mode"],
            "area": row["area"], "language": row["language"], "intents": pl(row["intents"]),
            "accessibility": pl(row["accessibility"]), "capacity": row["capacity"], "min_size": row["min_size"],
            "member_count": count, "status": row["status"], "member_events": bool(row["member_events"]),
            "signals": [{"id": s["qloo_id"], "kind": s["kind"], "name": s["name"], "type": s["type"]} for s in sig],
            "notice": NOTICES.get(row["category"])}


def _membership(c, cid, uid):
    if not uid:
        return None
    return c.execute("SELECT * FROM memberships WHERE circle_id = ? AND user_id = ?", (cid, uid)).fetchone()


def _active(m) -> bool:
    return bool(m) and m["status"] == "active"


def _is_mod(m) -> bool:
    return _active(m) and m["role"] in ("host", "moderator")


def _circle_or_404(c, cid, uid=None, invite: str | None = None):
    row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "Circle not found.")
    m = _membership(c, cid, uid)
    invited = bool(invite) and row["invite_code"] is not None and secrets.compare_digest(invite, row["invite_code"])
    if row["visibility"] == "private" and not (m and m["status"] in ("active", "pending")) and not invited:
        raise HTTPException(404, "Circle not found.")  # never confirm a private Circle exists
    return row, m


def browse(q: str = "", category: str = "", uid: str | None = None) -> list[dict]:
    with db.read() as c:
        rows = c.execute("SELECT * FROM circles WHERE status = 'active' AND visibility = 'public' ORDER BY created_at DESC LIMIT 200").fetchall()
        out = []
        qn = norm(q)
        for r in rows:
            if category and r["category"] != category:
                continue
            if qn and qn not in norm(r["name"] + " " + r["topic_label"] + " " + r["purpose"]):
                continue
            s = _summary(c, r)
            m = _membership(c, r["id"], uid)
            s["my_status"] = m["status"] if m else None
            out.append(s)
        return out[:60]


def circle_detail(cid: str, uid: str | None, invite: str | None = None) -> dict:
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid, invite)
        s = _summary(c, row)
        s["guidelines"] = GUIDELINES
        s["expectations"] = [
            f"Meet {'online' if row['meeting_mode'] == 'online' else 'in person' if row['meeting_mode'] == 'in_person' else 'online or in person'}"
            + (f" around {row['area']}" if row["area"] and row["meeting_mode"] != "online" else ""),
            f"Group size {row['min_size']}–{row['capacity']} people",
            "Events are proposed by members, voted on, and confirmed by a host — nothing is booked automatically",
            "Members can see that you joined this Circle",
        ]
        s["my_membership"] = {"role": m["role"], "status": m["status"]} if m else None
        host = c.execute("SELECT alias FROM profiles WHERE user_id = ?", (row["host_id"],)).fetchone() if row["host_id"] else None
        s["host_alias"] = host["alias"] if host and _active(m) else None
        if _is_mod(m) and row["visibility"] == "private":
            s["invite_code"] = row["invite_code"]
        return s


# ---------------------------------------------------------------- matching
def _hard_fail(circle: dict, prof: dict, labels_norm: set, c, uid) -> str | None:
    if circle["member_count"] >= circle["capacity"]:
        return "full"
    prefs = set(prof["activity_prefs"])
    mode = circle["meeting_mode"]
    if mode == "in_person" and prefs and "in_person" not in prefs and prefs <= {"online"}:
        return "meeting mode"
    if mode == "online" and prefs and "online" not in prefs and prefs <= {"in_person", "indoor", "outdoor"}:
        return "meeting mode"
    if mode == "in_person" and circle["area"] and prof["area"] and not (area_tokens(circle["area"]) & area_tokens(prof["area"])):
        return "area"
    if circle["language"] and prof["language"] and norm(circle["language"]) != norm(prof["language"]):
        return "language"
    needs = set(prof["accessibility"]) - {"flexible_participation"}
    if mode == "online":
        needs -= {"wheelchair"}
    if needs - set(circle["accessibility"]):
        return "accessibility"
    excl = {norm(x) for x in prof["exclude_topics"] if norm(x)}
    topic = norm(circle["topic_label"] + " " + circle["name"])
    if any(e in topic for e in excl):
        return "excluded topic"
    blocked = c.execute("""SELECT 1 FROM memberships m JOIN blocks b ON
                             ((b.blocker_id = ? AND b.blocked_id = m.user_id) OR (b.blocked_id = ? AND b.blocker_id = m.user_id))
                           WHERE m.circle_id = ? AND m.status = 'active' LIMIT 1""", (uid, uid, circle["id"])).fetchone()
    if blocked:
        return "blocked member"
    return None


def recommend(uid: str) -> dict:
    prof = get_profile(uid)
    if not prof["discoverable"]:
        raise HTTPException(403, "Turn on discovery (consent) to get Circle recommendations.")
    interests = prof["interests"]
    taste, warn = _taste(uid, interests)
    my_ids = {s["id"]: (it, s) for it in interests for s in it["signals"]}
    my_labels = {norm(it["label"]): it for it in interests}
    taste_ids = {}
    if taste:
        for t in taste["tags"]:
            taste_ids[t["id"]] = ("taste tag", t["name"])
        for e in taste["entities"]:
            taste_ids[e["id"]] = ("recommended " + (e.get("type") or "").split(":")[-1].replace("_", " "), e["name"])
    recs, excluded = [], {}
    matched_interest_labels = set()
    with db.read() as c:
        rows = c.execute("SELECT * FROM circles WHERE status = 'active' AND visibility = 'public'").fetchall()
        for r in rows:
            m = _membership(c, r["id"], uid)
            if m and m["status"] in ("active", "pending", "removed"):
                continue
            circ = _summary(c, r)
            reasons, pts, labels_hit = [], 0.0, set()
            for s in circ["signals"]:
                if s["id"] in my_ids:
                    it, mine = my_ids[s["id"]]
                    reasons.append({"source": "declared", "text": f"You declared “{it['label']}” — same Qloo {s['kind']} “{s['name']}” as this Circle's topic."})
                    pts += 3
                    labels_hit.add(norm(it["label"]))
                    if it["intent"] in circ["intents"]:
                        reasons.append({"source": "preference", "text": f"You want to {it['intent']} — this Circle welcomes members who {it['intent']}."})
                        pts += 1
            lab = norm(circ["topic_label"])
            if lab in my_labels and not any(x["source"] == "declared" for x in reasons):
                it = my_labels[lab]
                reasons.append({"source": "declared", "text": f"You declared “{it['label']}”, the topic of this Circle."})
                pts += 2
                labels_hit.add(lab)
            qloo_pts = 0.0
            for s in circ["signals"]:
                if s["id"] in taste_ids and s["id"] not in my_ids and qloo_pts < 3:
                    kind, name = taste_ids[s["id"]]
                    reasons.append({"source": "qloo", "text": f"Qloo Insights for your interests returned the {kind} “{name}”, which is this Circle's topic."})
                    qloo_pts += 1.5
            pts += qloo_pts
            if pts <= 0:
                continue  # no declared or Qloo-supported link: never recommend on preferences alone
            fail = _hard_fail(circ, prof, set(my_labels), c, uid)
            if fail:
                excluded[fail] = excluded.get(fail, 0) + 1
                continue
            matched_interest_labels |= labels_hit
            if prof["area"] and circ["area"] and area_tokens(prof["area"]) & area_tokens(circ["area"]):
                reasons.append({"source": "preference", "text": f"Same broad area ({circ['area']})."})
                pts += 1
            if circ["member_count"] < circ["min_size"]:
                reasons.append({"source": "preference", "text": f"Needs {circ['min_size'] - circ['member_count']} more member(s) to get going."})
                pts += 0.5
            circ["reasons"] = reasons
            circ["_pts"] = pts
            recs.append(circ)
    recs.sort(key=lambda x: (-x["_pts"], x["name"]))
    for r in recs:
        r["rank_basis"] = "Ordered by count of declared matches (×3), Qloo-supported links (×1.5, max 3), intent and area fit. Not a compatibility score."
        r.pop("_pts", None)
    create = [{"interest_id": it["id"], "label": it["label"], "intent": it["intent"], "signals": it["signals"],
               "suggested_category": suggest_category(it["label"], it["signals"])}
              for it in interests if norm(it["label"]) not in matched_interest_labels]
    return {"recommendations": recs[:8], "excluded": excluded, "create_suggestions": create,
            "warnings": [w for w in [warn] if w], "taste_used": bool(taste)}


# ---------------------------------------------------------------- circle mutations
def create_circle(uid: str, data: dict) -> dict:
    with db.tx() as c:
        prof = _require_profile(c, uid)
        it = c.execute("SELECT * FROM profile_interests WHERE id = ? AND user_id = ?", (data["interest_id"], uid)).fetchone()
        if not it:
            raise HTTPException(400, "Pick one of your own interests as the Circle topic.")
        sig = c.execute("SELECT qloo_id, kind, name, type FROM interest_signals WHERE interest_id = ?", (it["id"],)).fetchall()
        topic_key = "label:" + norm(it["label"])
        area = (data.get("area") if data.get("area") is not None else prof["area"]).strip()[:60]
        akey = " ".join(sorted(area_tokens(area))) if data["meeting_mode"] != "online" else "online"
        if data["visibility"] == "public":
            dup = c.execute("SELECT id, name FROM circles WHERE status = 'active' AND visibility = 'public' AND area_key = ? AND "
                            "(topic_key = ? OR id IN (SELECT circle_id FROM circle_signals WHERE qloo_id IN (%s)))"
                            % ",".join("?" * len(sig) or "''"), (akey, topic_key, *[s["qloo_id"] for s in sig])).fetchone()
            if dup:
                raise HTTPException(409, {"message": "A public Circle for this topic and area already exists — join it, "
                                                     "or create yours as a private (invite-only) Circle.",
                                          "circle_id": dup["id"], "name": dup["name"]})
        cid = "C" + uuid.uuid4().hex[:10]
        category = data.get("category") or suggest_category(it["label"], [dict(s) for s in sig])
        try:
            c.execute("""INSERT INTO circles (id, name, purpose, topic_label, topic_key, category, visibility, meeting_mode, area,
                           area_key, language, intents, accessibility, capacity, min_size, member_events, host_id, created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (cid, data["name"], data.get("purpose", ""), it["label"], topic_key, category, data["visibility"],
                       data["meeting_mode"], area if data["meeting_mode"] != "online" else "", akey, data.get("language", ""),
                       jl(data.get("intents") or [it["intent"]]), jl(data.get("accessibility") or ["flexible_participation"]),
                       data.get("capacity", 12), data.get("min_size", 3), int(data.get("member_events", True)), uid, now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "A Circle for this topic and area was just created — refresh and join it.")
        for s in sig:
            c.execute("INSERT INTO circle_signals VALUES (?,?,?,?,?)", (cid, s["qloo_id"], s["kind"], s["name"], s["type"]))
        c.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (cid, uid, "host", "active", now()))
        if data["visibility"] == "private":
            c.execute("UPDATE circles SET invite_code = ? WHERE id = ?", (secrets.token_urlsafe(9), cid))
    return circle_detail(cid, uid)


def update_circle(uid: str, cid: str, data: dict) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not (_active(m) and m["role"] == "host"):
            raise HTTPException(403, "Only the host can edit this Circle.")
        count = c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (cid,)).fetchone()[0]
        cap = data.get("capacity", row["capacity"])
        if cap < count:
            raise HTTPException(400, f"Capacity can't be below the current member count ({count}).")
        c.execute("""UPDATE circles SET name = ?, purpose = ?, category = ?, capacity = ?, min_size = ?, member_events = ?,
                     accessibility = ?, language = ? WHERE id = ?""",
                  (data.get("name", row["name"]), data.get("purpose", row["purpose"]), data.get("category", row["category"]),
                   cap, data.get("min_size", row["min_size"]), int(data.get("member_events", row["member_events"])),
                   jl(data["accessibility"]) if "accessibility" in data else row["accessibility"],
                   data.get("language", row["language"]), cid))
    return circle_detail(cid, uid)


def join(uid: str, cid: str, invite: str | None = None) -> dict:
    with db.tx() as c:
        _require_profile(c, uid)
        row, m = _circle_or_404(c, cid, uid, invite)
        if row["status"] != "active":
            raise HTTPException(409, "This Circle is archived.")
        if m:
            if m["status"] in ("active", "pending"):
                return {"status": m["status"], "already": True}
            if m["status"] == "removed":
                raise HTTPException(403, "You were removed from this Circle by a moderator.")
        prof = get_profile_c(c, uid)
        circ = _summary(c, row)
        fail = _hard_fail(circ, prof, set(), c, uid)
        if fail:
            msg = {"full": "This Circle is full.", "blocked member": "You can't join a Circle with someone you've blocked or who blocked you.",
                   "accessibility": "This Circle hasn't committed to the accessibility needs in your profile.",
                   "area": "This in-person Circle meets in a different area.", "language": "This Circle uses a different language.",
                   "meeting mode": "This Circle's meeting mode doesn't match your preferences.",
                   "excluded topic": "This topic is in your 'never recommend' list."}.get(fail, "Not eligible.")
            raise HTTPException(403, msg)
        status = "pending" if row["visibility"] == "private" else "active"
        c.execute("INSERT INTO memberships VALUES (?,?,?,?,?) ON CONFLICT(circle_id, user_id) DO UPDATE SET "
                  "status = excluded.status, role = 'member', joined_at = excluded.joined_at", (cid, uid, "member", status, now()))
    return {"status": status, "already": False}


def get_profile_c(c, uid):
    p = dict(_require_profile(c, uid))
    for k in ("availability", "activity_prefs", "accessibility", "exclude_topics"):
        p[k] = pl(p[k])
    return p


def leave(uid: str, cid: str) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not m or m["status"] not in ("active", "pending"):
            raise HTTPException(400, "You're not a member of this Circle.")
        c.execute("UPDATE memberships SET status = 'left', role = 'member' WHERE circle_id = ? AND user_id = ?", (cid, uid))
        if m["role"] == "host":
            _transfer_host(c, cid, uid)
        c.execute("DELETE FROM rsvps WHERE user_id = ? AND event_id IN (SELECT id FROM circle_events WHERE circle_id = ?)", (uid, cid))
    return {"left": True}


def moderate_member(uid: str, cid: str, target: str, action: str) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _is_mod(m):
            raise HTTPException(403, "Moderators only.")
        t = _membership(c, cid, target)
        if not t:
            raise HTTPException(404, "Member not found.")
        if t["role"] == "host" or target == uid:
            raise HTTPException(403, "You can't do that to the host or yourself.")
        if action in ("make_moderator", "make_member") and m["role"] != "host":
            raise HTTPException(403, "Only the host can change roles.")
        if action == "approve":
            if t["status"] != "pending":
                raise HTTPException(400, "Not a pending request.")
            n = c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (cid,)).fetchone()[0]
            if n >= row["capacity"]:
                raise HTTPException(409, "Circle is full.")
            c.execute("UPDATE memberships SET status = 'active' WHERE circle_id = ? AND user_id = ?", (cid, target))
        elif action in ("remove", "decline"):
            c.execute("UPDATE memberships SET status = ?, role = 'member' WHERE circle_id = ? AND user_id = ?",
                      ("removed" if action == "remove" else "left", cid, target))
        elif action == "make_moderator":
            c.execute("UPDATE memberships SET role = 'moderator' WHERE circle_id = ? AND user_id = ? AND status = 'active'", (cid, target))
        elif action == "make_member":
            c.execute("UPDATE memberships SET role = 'member' WHERE circle_id = ? AND user_id = ?", (cid, target))
        else:
            raise HTTPException(400, "Unknown action.")
    return {"ok": True}


def members(uid: str, cid: str) -> dict:
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to see its members.")
        rows = c.execute("""SELECT m.user_id, m.role, m.status, m.joined_at, p.alias, p.area, p.show_area, p.share_interests, p.bio
                            FROM memberships m JOIN profiles p ON p.user_id = m.user_id
                            WHERE m.circle_id = ? AND m.status IN ('active','pending') ORDER BY m.joined_at""", (cid,)).fetchall()
        out = []
        for r in rows:
            if r["status"] == "pending" and not _is_mod(m):
                continue
            d = {"user_id": r["user_id"], "alias": r["alias"], "role": r["role"], "status": r["status"],
                 "joined_at": r["joined_at"], "me": r["user_id"] == uid, "bio": r["bio"] if r["share_interests"] else ""}
            if r["show_area"]:
                d["area"] = r["area"]
            if r["share_interests"]:
                d["interests"] = [{"label": i["label"], "intent": i["intent"]} for i in
                                  c.execute("SELECT label, intent FROM profile_interests WHERE user_id = ?", (r["user_id"],))]
            out.append(d)
        return {"members": out, "can_moderate": _is_mod(m), "is_host": m["role"] == "host"}


# ---------------------------------------------------------------- discussion
def list_posts(uid: str, cid: str, before: int | None = None, limit: int = 20) -> dict:
    limit = max(1, min(limit, 50))
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to read its discussion.")
        mod = _is_mod(m)
        blocked = {r[0] for r in c.execute("SELECT blocked_id FROM blocks WHERE blocker_id = ?", (uid,))}
        q = "SELECT p.*, pr.alias FROM posts p LEFT JOIN profiles pr ON pr.user_id = p.user_id WHERE p.circle_id = ? AND p.parent_id IS NULL"
        args = [cid]
        if before:
            q += " AND p.id < ?"
            args.append(before)
        q += " ORDER BY p.id DESC LIMIT ?"
        args.append(limit + 1)
        rows = c.execute(q, args).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]

        def view(r):
            hidden_for_me = r["user_id"] in blocked
            d = {"id": r["id"], "author": r["alias"] if r["user_id"] else "[deleted account]", "author_id": r["user_id"],
                 "mine": r["user_id"] == uid, "created_at": r["created_at"], "edited_at": r["edited_at"],
                 "deleted": bool(r["deleted"]), "hidden": bool(r["hidden"]), "blocked": hidden_for_me,
                 "body": "" if (r["deleted"] or hidden_for_me or (r["hidden"] and not mod)) else r["body"]}
            return d
        posts = []
        for r in rows:
            d = view(r)
            reps = c.execute("SELECT p.*, pr.alias FROM posts p LEFT JOIN profiles pr ON pr.user_id = p.user_id "
                             "WHERE p.parent_id = ? ORDER BY p.id LIMIT 50", (r["id"],)).fetchall()
            d["replies"] = [view(x) for x in reps]
            posts.append(d)
        return {"posts": posts, "next_before": rows[-1]["id"] if more and rows else None, "can_moderate": mod}


def create_post(uid: str, cid: str, body: str, parent_id: int | None) -> dict:
    body = (body or "").strip()
    if not body:
        raise HTTPException(400, "Write something first.")
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to post.")
        if parent_id is not None:
            par = c.execute("SELECT id, parent_id, deleted FROM posts WHERE id = ? AND circle_id = ?", (parent_id, cid)).fetchone()
            if not par or par["parent_id"] is not None:
                raise HTTPException(400, "You can only reply to a top-level post in this Circle.")
        dup = c.execute("SELECT id FROM posts WHERE circle_id = ? AND user_id = ? AND body = ? AND created_at > ?",
                        (cid, uid, body, now() - 30)).fetchone()
        if dup:
            raise HTTPException(409, "Looks like a duplicate of your last post.")
        cur = c.execute("INSERT INTO posts (circle_id, user_id, parent_id, body, created_at) VALUES (?,?,?,?,?)",
                        (cid, uid, parent_id, body, now()))
    return {"id": cur.lastrowid}


def edit_post(uid: str, cid: str, pid: int, body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise HTTPException(400, "Post can't be empty.")
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        p = c.execute("SELECT * FROM posts WHERE id = ? AND circle_id = ?", (pid, cid)).fetchone()
        if not p or p["deleted"]:
            raise HTTPException(404, "Post not found.")
        if p["user_id"] != uid or not _active(m):
            raise HTTPException(403, "You can only edit your own posts.")
        c.execute("UPDATE posts SET body = ?, edited_at = ? WHERE id = ?", (body, now(), pid))
    return {"ok": True}


def delete_post(uid: str, cid: str, pid: int) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        p = c.execute("SELECT * FROM posts WHERE id = ? AND circle_id = ?", (pid, cid)).fetchone()
        if not p:
            raise HTTPException(404, "Post not found.")
        if not (p["user_id"] == uid and _active(m)) and not _is_mod(m):
            raise HTTPException(403, "Not allowed.")
        c.execute("UPDATE posts SET deleted = 1, body = '' WHERE id = ?", (pid,))
    return {"ok": True}


def hide_post(uid: str, cid: str, pid: int, hidden: bool) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _is_mod(m):
            raise HTTPException(403, "Moderators only.")
        n = c.execute("UPDATE posts SET hidden = ? WHERE id = ? AND circle_id = ?", (int(hidden), pid, cid)).rowcount
        if not n:
            raise HTTPException(404, "Post not found.")
    return {"ok": True}


def report(uid: str, cid: str, target_type: str, target_id: str, reason: str) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Only members can report.")
        if target_type == "post":
            ok = c.execute("SELECT 1 FROM posts WHERE id = ? AND circle_id = ?", (target_id, cid)).fetchone()
        else:
            ok = c.execute("SELECT 1 FROM memberships WHERE user_id = ? AND circle_id = ?", (target_id, cid)).fetchone()
        if not ok:
            raise HTTPException(404, "Nothing to report there.")
        try:
            c.execute("INSERT INTO reports (reporter_id, circle_id, target_type, target_id, reason, created_at) VALUES (?,?,?,?,?,?)",
                      (uid, cid, target_type, str(target_id), reason.strip(), now()))
        except sqlite3.IntegrityError:
            return {"ok": True, "already": True}
    return {"ok": True}


def list_reports(uid: str, cid: str) -> list[dict]:
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _is_mod(m):
            raise HTTPException(403, "Moderators only.")
        rows = c.execute("""SELECT r.*, p.body AS post_body, pa.alias AS target_alias FROM reports r
                            LEFT JOIN posts p ON r.target_type = 'post' AND p.id = CAST(r.target_id AS INTEGER)
                            LEFT JOIN profiles pa ON pa.user_id = CASE WHEN r.target_type = 'user' THEN r.target_id ELSE p.user_id END
                            WHERE r.circle_id = ? ORDER BY r.status, r.id DESC LIMIT 100""", (cid,)).fetchall()
        return [{"id": r["id"], "target_type": r["target_type"], "target_id": r["target_id"], "reason": r["reason"],
                 "status": r["status"], "created_at": r["created_at"], "post_body": r["post_body"],
                 "target_alias": r["target_alias"]} for r in rows]


def resolve_report(uid: str, cid: str, rid: int) -> dict:
    with db.tx() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _is_mod(m):
            raise HTTPException(403, "Moderators only.")
        c.execute("UPDATE reports SET status = 'resolved' WHERE id = ? AND circle_id = ?", (rid, cid))
    return {"ok": True}


def block(uid: str, target: str, on: bool) -> dict:
    if target == uid:
        raise HTTPException(400, "You can't block yourself.")
    with db.tx() as c:
        if not c.execute("SELECT 1 FROM users WHERE id = ?", (target,)).fetchone():
            raise HTTPException(404, "User not found.")
        if on:
            c.execute("INSERT OR IGNORE INTO blocks VALUES (?,?,?)", (uid, target, now()))
        else:
            c.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (uid, target))
    return {"blocked": on}


def my_blocks(uid: str) -> list[dict]:
    with db.read() as c:
        return [{"user_id": r["blocked_id"], "alias": r["alias"]} for r in c.execute(
            "SELECT b.blocked_id, p.alias FROM blocks b LEFT JOIN profiles p ON p.user_id = b.blocked_id WHERE b.blocker_id = ?", (uid,))]


def my_circles(uid: str) -> list[dict]:
    with db.read() as c:
        rows = c.execute("""SELECT c.*, m.role, m.status AS mstatus FROM memberships m JOIN circles c ON c.id = m.circle_id
                            WHERE m.user_id = ? AND m.status IN ('active','pending') ORDER BY m.joined_at DESC""", (uid,)).fetchall()
        out = []
        for r in rows:
            s = _summary(c, r)
            s["my_role"], s["my_status"] = r["role"], r["mstatus"]
            out.append(s)
        return out


# ---------------------------------------------------------------- member-led events (reuses the planning agent)
_SLOTS = {"weekday_daytime": lambda d: d.weekday() < 5 and 8 <= d.hour < 17,
          "weekday_evening": lambda d: d.weekday() < 5 and (d.hour >= 17 or d.hour < 8),
          "weekend": lambda d: d.weekday() >= 5}


def _parse_time(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Invalid date/time: {s}")
    return d


def _group_for_planner(c, cid: str, row) -> tuple[dict, list[dict]]:
    rows = c.execute("""SELECT m.user_id, p.* FROM memberships m JOIN profiles p ON p.user_id = m.user_id
                        WHERE m.circle_id = ? AND m.status = 'active' ORDER BY m.joined_at""", (cid,)).fetchall()
    topic_sig = [{"kind": s["kind"], "id": s["qloo_id"], "name": s["name"], "type": s["type"]}
                 for s in c.execute("SELECT * FROM circle_signals WHERE circle_id = ?", (cid,))]
    parts, profs = [], []
    for r in rows:
        p = dict(r)
        for k in ("availability", "activity_prefs", "accessibility"):
            p[k] = pl(p[k])
        profs.append(p)
        # Only Circle-approved data: the Circle topic for everyone, personal interests only if the member opted in.
        ints = [{"label": row["topic_label"], "intent": "share", "resolved": topic_sig}]
        if r["share_interests"]:
            for it in _interests(c, r["user_id"]):
                if norm(it["label"]) == norm(row["topic_label"]):
                    ints[0]["intent"] = {"teach": "teach", "learn": "learn"}.get(it["intent"], "share")
                    continue
                ints.append({"label": it["label"], "intent": {"teach": "teach", "learn": "learn"}.get(it["intent"], "share"),
                             "resolved": [{"kind": s["kind"], "id": s["id"], "name": s["name"], "type": s["type"]} for s in it["signals"]]})
        taste = None
        if r["share_interests"]:
            t = c.execute("SELECT taste FROM user_taste WHERE user_id = ?", (r["user_id"],)).fetchone()
            taste = json.loads(t["taste"]) if t else None
        parts.append({"id": r["user_id"], "name": r["alias"], "interests": ints, "consent": True,
                      "location": r["area"] if r["show_area"] else "",
                      "profile": {"tags": (taste or {}).get("tags", []), "entities": (taste or {}).get("entities", [])}})
    pairs = {}
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            pairs[frozenset((a["id"], b["id"]))] = pair_evidence(a, b)
    return describe_group(cid, parts, pairs), profs


def _checks(concept: dict, cons: dict, row, profs: list[dict], time_options: list[str], capacity: int, confirm: bool) -> list[dict]:
    out = []
    total = sum(int(a.get("minutes") or 0) for a in concept.get("agenda", []))
    out.append({"check": "Duration", "status": "pass" if total == cons["duration_min"] else "fail",
                "note": f"Agenda {total} min vs {cons['duration_min']} min requested"})
    cost = float((concept.get("cost_estimate") or {}).get("amount") or 0)
    out.append({"check": "Budget", "status": "pass" if cost <= cons["budget"] else "fail",
                "note": f"Estimated {cost:g} {cons['currency']} (unverified estimate) vs budget {cons['budget']:g}"})
    caps = [p["budget_max"] for p in profs if p.get("budget_max") is not None]
    if caps:
        per = cost / max(1, len(profs))
        out.append({"check": "Per-person cost", "status": "pass" if per <= min(caps) else "fail",
                    "note": f"~{per:.2f} per person vs lowest personal budget limit (members' limits stay private)"})
    mode = row["meeting_mode"]
    setting = concept.get("setting") or cons["setting"]
    ok_mode = not (mode == "online" and setting not in ("online",)) and not (mode == "in_person" and setting == "online")
    out.append({"check": "Meeting mode", "status": "pass" if ok_mode else "fail", "note": f"Circle meets {mode.replace('_', ' ')}"})
    out.append({"check": "Capacity", "status": "pass" if capacity <= row["capacity"] else "fail",
                "note": f"Event capacity {capacity} vs Circle capacity {row['capacity']}"})
    n = len(profs)
    out.append({"check": "Minimum group size", "status": "pass" if n >= row["min_size"] else ("fail" if confirm else "warn"),
                "note": f"{n} active member(s); Circle minimum is {row['min_size']}"})
    needs = sorted({x for p in profs for x in p["accessibility"]} - {"flexible_participation"})
    if needs:
        missing = [x for x in needs if x not in pl(row["accessibility"]) and not (x == "wheelchair" and mode == "online")]
        out.append({"check": "Accessibility", "status": "warn" if not missing else "fail",
                    "note": ("Needs to confirm on the day: " + ", ".join(needs).replace("_", " ")) if not missing
                    else "Not committed by this Circle: " + ", ".join(missing).replace("_", " ")})
    for i, t in enumerate(time_options):
        d = _parse_time(t)
        avail = sum(1 for p in profs if not p["availability"] or any(_SLOTS[s](d) for s in p["availability"] if s in _SLOTS))
        out.append({"check": f"Time option {i + 1}", "status": "pass" if avail >= min(row["min_size"], n) else "warn",
                    "note": f"{avail} of {n} member(s) list availability that fits this slot"})
    out.append({"check": "Venue & booking", "status": "warn", "note": "Not verified — the host must confirm availability and price directly."})
    return out


def propose_event(uid: str, cid: str, data: dict) -> dict:
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to propose an event.")
        if not row["member_events"] and not _is_mod(m):
            raise HTTPException(403, "In this Circle only hosts and moderators can propose events.")
        times = []
        for t in data.get("time_options") or []:
            d = _parse_time(t)
            ref = datetime.now(d.tzinfo or None) if d.tzinfo else datetime.now()
            if d < ref or d > ref + timedelta(days=365):
                raise HTTPException(400, "Time options must be in the next 12 months.")
            times.append(d.isoformat())
        capacity = data.get("capacity") or row["capacity"]
        if capacity > row["capacity"]:
            raise HTTPException(400, f"Event capacity can't exceed the Circle capacity ({row['capacity']}).")
        group, profs = _group_for_planner(c, cid, row)
    needs = {x for p in profs for x in p["accessibility"]}
    goals = sorted({{"enjoy": "connect", "teach": "learn", "learn": "learn", "discuss": "debate" if row["category"] == "political" else "support",
                     "collaborate": "create"}.get(i, "connect") for i in pl(row["intents"])}) or ["connect"]
    cons = {"duration_min": int(data["duration_min"]), "budget": float(data["budget"]), "currency": data.get("currency") or "USD",
            "setting": "online" if row["meeting_mode"] == "online" else (data.get("setting") or "any"),
            "wheelchair": "wheelchair" in needs, "quiet_space": "quiet_space" in needs, "visual_aids": "visual_aids" in needs,
            "flexible_participation": True, "sensitive_topic": row["category"] != "general", "goals": goals,
            "language": row["language"]}
    plan = planner.run_agent(group, cons, row["area"] if row["meeting_mode"] != "online" else None)
    concepts = plan.get("concepts", [])[:2]
    for k in concepts:
        k["checks"] = _checks(k, cons, row, profs, times, capacity, confirm=False)
        k["unresolved_questions"] = [
            "Where exactly will you meet? Venue availability and access are not verified." if row["meeting_mode"] != "online"
            else "Which video-call link will the host share?",
            "Costs are planning estimates, not quotes — who confirms prices?",
            "Which time works best? Members vote below." if times else "No date proposed yet — the host should add options.",
        ]
    eid = "E" + uuid.uuid4().hex[:10]
    title = (data.get("title") or (concepts[0]["title"] if concepts else f"{row['topic_label']} meetup")).strip()[:100]
    stored = {"concepts": concepts, "evidence": plan.get("evidence", []), "trace": plan.get("trace", []),
              "fallback": plan.get("fallback"), "planner": concepts[0]["generated_by"] if concepts else None}
    with db.tx() as c:
        c.execute("""INSERT INTO circle_events (id, circle_id, proposer_id, title, constraints, plan, time_options, capacity,
                     location_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (eid, cid, uid, title, json.dumps(cons), json.dumps(stored, default=str), json.dumps(times),
                   capacity, (data.get("location_note") or "")[:200], now()))
    return get_event(uid, eid)


def _event(c, eid, uid):
    e = c.execute("SELECT * FROM circle_events WHERE id = ?", (eid,)).fetchone()
    if not e:
        raise HTTPException(404, "Event not found.")
    row, m = _circle_or_404(c, e["circle_id"], uid)
    if not _active(m):
        raise HTTPException(403, "Members only.")
    return e, row, m


def _event_view(c, e, uid, m) -> dict:
    votes = c.execute("SELECT kind, choice, COUNT(*) n FROM event_votes WHERE event_id = ? GROUP BY kind, choice", (e["id"],)).fetchall()
    mine = {r["kind"]: r["choice"] for r in c.execute("SELECT kind, choice FROM event_votes WHERE event_id = ? AND user_id = ?", (e["id"], uid))}
    rs = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM rsvps WHERE event_id = ? GROUP BY status", (e["id"],))}
    my_rsvp = c.execute("SELECT status FROM rsvps WHERE event_id = ? AND user_id = ?", (e["id"], uid)).fetchone()
    prop = c.execute("SELECT alias FROM profiles WHERE user_id = ?", (e["proposer_id"],)).fetchone() if e["proposer_id"] else None
    return {"id": e["id"], "circle_id": e["circle_id"], "title": e["title"], "status": e["status"],
            "proposer": prop["alias"] if prop else "[deleted account]", "mine": e["proposer_id"] == uid,
            "constraints": json.loads(e["constraints"]), "plan": json.loads(e["plan"]),
            "time_options": json.loads(e["time_options"]), "chosen_option": e["chosen_option"], "chosen_time": e["chosen_time"],
            "capacity": e["capacity"], "location_note": e["location_note"], "created_at": e["created_at"],
            "confirmed_at": e["confirmed_at"],
            "votes": {"activity": {r["choice"]: r["n"] for r in votes if r["kind"] == "activity"},
                      "time": {r["choice"]: r["n"] for r in votes if r["kind"] == "time"}},
            "my_votes": mine, "rsvp_counts": rs, "my_rsvp": my_rsvp["status"] if my_rsvp else None,
            "can_manage": _is_mod(m), "can_cancel": _is_mod(m) or e["proposer_id"] == uid}


def get_event(uid: str, eid: str) -> dict:
    with db.read() as c:
        e, row, m = _event(c, eid, uid)
        return _event_view(c, e, uid, m)


def list_events(uid: str, cid: str) -> list[dict]:
    with db.read() as c:
        row, m = _circle_or_404(c, cid, uid)
        if not _active(m):
            raise HTTPException(403, "Join this Circle to see its events.")
        rows = c.execute("SELECT * FROM circle_events WHERE circle_id = ? ORDER BY CASE status WHEN 'confirmed' THEN 0 "
                         "WHEN 'proposed' THEN 1 ELSE 2 END, created_at DESC LIMIT 30", (cid,)).fetchall()
        return [_event_view(c, e, uid, m) for e in rows]


def vote(uid: str, eid: str, kind: str, choice: int) -> dict:
    with db.tx() as c:
        e, row, m = _event(c, eid, uid)
        if e["status"] != "proposed":
            raise HTTPException(409, "Voting is closed for this event.")
        n = len(json.loads(e["plan"]).get("concepts", [])) if kind == "activity" else len(json.loads(e["time_options"]))
        if not 0 <= choice < n:
            raise HTTPException(400, "Invalid choice.")
        c.execute("INSERT OR REPLACE INTO event_votes VALUES (?,?,?,?)", (eid, uid, kind, choice))
    return get_event(uid, eid)


def confirm_event(uid: str, eid: str, option: int, time_index: int | None, location_note: str | None) -> dict:
    with db.tx() as c:
        e, row, m = _event(c, eid, uid)
        if not _is_mod(m):
            raise HTTPException(403, "Only a host or moderator can confirm the final plan.")
        if e["status"] != "proposed":
            raise HTTPException(409, f"Event is already {e['status']}.")
        plan = json.loads(e["plan"])
        concepts = plan.get("concepts", [])
        if not 0 <= option < len(concepts):
            raise HTTPException(400, "Choose one of the proposed activity options.")
        times = json.loads(e["time_options"])
        if time_index is None or not 0 <= time_index < len(times):
            raise HTTPException(400, "Choose one of the proposed times before confirming.")
        if _parse_time(times[time_index]).replace(tzinfo=None) < datetime.now():
            raise HTTPException(400, "That time has already passed.")
        _, profs = _group_for_planner(c, row["id"], row)
        checks = _checks(concepts[option], json.loads(e["constraints"]), row, profs, [times[time_index]], e["capacity"], confirm=True)
        fails = [k for k in checks if k["status"] == "fail"]
        if fails:
            raise HTTPException(409, {"message": "Hard constraints failed — edit or re-propose the event.", "failed": fails})
        concepts[option]["checks"] = checks
        c.execute("""UPDATE circle_events SET status = 'confirmed', chosen_option = ?, chosen_time = ?, plan = ?,
                     location_note = COALESCE(?, location_note), confirmed_by = ?, confirmed_at = ? WHERE id = ?""",
                  (option, times[time_index], json.dumps(plan, default=str), (location_note or None), uid, now(), eid))
    return get_event(uid, eid)


def cancel_event(uid: str, eid: str) -> dict:
    with db.tx() as c:
        e, row, m = _event(c, eid, uid)
        if not (_is_mod(m) or e["proposer_id"] == uid):
            raise HTTPException(403, "Only the proposer or a host can cancel.")
        if e["status"] == "cancelled":
            return {"ok": True}
        c.execute("UPDATE circle_events SET status = 'cancelled' WHERE id = ?", (eid,))
    return get_event(uid, eid)


def rsvp(uid: str, eid: str, status: str) -> dict:
    with db.tx() as c:
        e, row, m = _event(c, eid, uid)
        if e["status"] != "confirmed":
            raise HTTPException(409, "RSVPs open once a host confirms the event.")
        if status == "going":
            going = c.execute("SELECT COUNT(*) FROM rsvps WHERE event_id = ? AND status = 'going' AND user_id <> ?", (eid, uid)).fetchone()[0]
            if going >= e["capacity"]:
                raise HTTPException(409, "This event is full.")
        c.execute("INSERT OR REPLACE INTO rsvps VALUES (?,?,?,?)", (eid, uid, status, now()))
    return get_event(uid, eid)


def my_events(uid: str) -> list[dict]:
    with db.read() as c:
        rows = c.execute("""SELECT e.*, c.name AS circle_name FROM circle_events e
                            JOIN memberships m ON m.circle_id = e.circle_id AND m.user_id = ? AND m.status = 'active'
                            JOIN circles c ON c.id = e.circle_id WHERE e.status <> 'cancelled'
                            ORDER BY CASE e.status WHEN 'confirmed' THEN 0 ELSE 1 END, COALESCE(e.chosen_time, '') , e.created_at DESC
                            LIMIT 50""", (uid,)).fetchall()
        out = []
        for e in rows:
            my = c.execute("SELECT status FROM rsvps WHERE event_id = ? AND user_id = ?", (e["id"], uid)).fetchone()
            out.append({"id": e["id"], "circle_id": e["circle_id"], "circle_name": e["circle_name"], "title": e["title"],
                        "status": e["status"], "chosen_time": e["chosen_time"], "my_rsvp": my["status"] if my else None})
        return out
