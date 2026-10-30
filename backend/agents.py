"""Autonomous, Qloo-powered agent workflows (run by the persistent job queue in jobs.py).

Workflows (each a sequence of recorded, resumable tool steps; the orchestrator below picks the next step from the
run's persisted state and skips steps whose inputs are missing, e.g. no Qloo IDs -> no Qloo insights call):

  discovery          profile saved -> resolve unresolved interests with Qloo -> Qloo Insights taste profile ->
                     match existing Circles (Qloo results re-rank and add matches) -> related interests & activity
                     ideas -> start Circle formation for unmatched interests -> store results + notify
  circle_formation   find consenting compatible people for a topic -> reuse an existing Circle if one fits ->
                     create/update ONE persistent proposal per topic+area -> invite once enough people match ->
                     form the Circle only from people who accepted
  event_planning     Circle active -> Qloo cultural anchors + Qloo place results near the Circle's area ->
                     activity options (planner) -> venue validation -> times from members' stated availability ->
                     constraint checks -> persistent draft (members vote) + notifications
  coordinate_proposal  voting closed -> transparent tally -> publish (auto policy) or ask the host to approve
  event_followup     24h reminder, low-RSVP nudge, completion + optional feedback request

Separation of data (kept distinct everywhere it is stored or shown):
  * "declared"   — what the person typed / chose in their profile
  * "qloo"       — items returned by a real Qloo response (ids, names, request parameters are stored)
  * "app"        — application-computed scores, rules and generated text (never presented as Qloo output)
Deterministic code makes every permission, consent, scoring and database decision. The optional LLM (planner) only
drafts activity wording from the evidence pack.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, time as dtime, timedelta

from fastapi import HTTPException

from . import circles, config, db, jobs, mailer, planner
from . import platform_svc as P
from .circles import area_tokens, jl, norm, pl
from .qloo_client import QlooError

AUTO_RESOLVE_MATCH = 0.8      # only text matches this strong are attached to an interest automatically
MAX_INVITES = 12
MAX_FORMATIONS_PER_RUN = 3

MATCH_RULES = {
    "summary": "Application-computed match score (not a Qloo score). Hard constraints are applied first; "
               "only people who pass every constraint are scored.",
    "hard_constraints": ["discovery consent on", "automation and Circle invites not turned off",
                         "same broad area for in-person Circles (area words overlap)", "online-compatible preferences for online Circles",
                         "same language when both people set one", "topic not in the person's 'never recommend' list",
                         "no block between the person and the initiator"],
    "points": {"declared interest with the same label or the same Qloo ID": 3.0,
               "no declared match, but Qloo Insights for the person's interests returned the topic's Qloo ID": 1.5,
               "each shared availability slot with the initiator": 0.5,
               "complementary intents (teach <-> learn)": 1.0},
}

SLOT_TIMES = {"weekday_daytime": [(12, 30)], "weekday_evening": [(18, 30)], "weekend": [(11, 0), (16, 0)]}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def now() -> float:
    return jobs.now()


# ================================================================ settings & triggers
def get_settings(c, uid: str) -> dict:
    r = c.execute("SELECT * FROM agent_settings WHERE user_id = ?", (uid,)).fetchone()
    return {"automation": bool(r["automation"]) if r else True, "circle_invites": bool(r["circle_invites"]) if r else True,
            "email_notify": bool(r["email_notify"]) if r else False, "email_configured": mailer.enabled()}


def put_settings(uid: str, data: dict) -> dict:
    with db.tx() as c:
        cur = get_settings(c, uid)
        cur.update({k: bool(v) for k, v in data.items() if k in ("automation", "circle_invites", "email_notify") and v is not None})
        c.execute("INSERT INTO agent_settings VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET automation = excluded.automation, "
                  "circle_invites = excluded.circle_invites, email_notify = excluded.email_notify, updated_at = excluded.updated_at",
                  (uid, int(cur["automation"]), int(cur["circle_invites"]), int(cur["email_notify"]), now()))
        if not cur["automation"]:  # pausing stops this person's queued automation immediately
            c.execute("UPDATE agent_runs SET status = 'paused', updated_at = ? WHERE user_id = ? AND status = 'queued'", (now(), uid))
        if not cur["circle_invites"]:  # opting out withdraws them from proposals that haven't formed
            c.execute("""UPDATE circle_proposal_members SET status = 'withdrawn', updated_at = ? WHERE user_id = ? AND status IN
                         ('candidate','invited') AND proposal_id IN (SELECT id FROM circle_proposals WHERE status IN ('gathering','open'))""",
                      (now(), uid))
        return get_settings(c, uid)


def _open_agent_draft(c, cid):
    return c.execute("SELECT id FROM circle_events WHERE circle_id = ? AND source = 'agent' AND status = 'proposed'", (cid,)).fetchone()


def _upcoming_event(c, cid) -> bool:
    for e in c.execute("SELECT * FROM events WHERE circle_id = ? AND status = 'published'", (cid,)).fetchall():
        if not P._is_past(e):
            return True
    return False


def on_membership_changed(cid: str, trigger: str = "membership changed", force: bool = False) -> str | None:
    """A Circle that reaches its minimum size (or a host's 'plan now') triggers the Event Planning Agent."""
    with db.read() as c:
        row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
        if not row or row["status"] != "active":
            return None
        if not force and not row["auto_plan"]:
            return None
        n = c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (cid,)).fetchone()[0]
        if n < row["min_size"] or _open_agent_draft(c, cid) or (not force and _upcoming_event(c, cid)):
            return None
    return jobs.enqueue("event_planning", subject_type="circle", subject_id=cid, circle_id=cid, trigger=trigger,
                        payload={"force": force}, dedupe_key=f"plan:{cid}")


def after_vote(pid: str):
    """If every active member has voted on both activity and time, close voting without waiting for the deadline."""
    with db.read() as c:
        e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
        if not e or e["source"] != "agent" or e["status"] != "proposed" or e["selection"]:
            return None
        n = c.execute("SELECT COUNT(*) FROM memberships WHERE circle_id = ? AND status = 'active'", (e["circle_id"],)).fetchone()[0]
        voted = c.execute("SELECT COUNT(DISTINCT user_id) FROM event_votes WHERE event_id = ? AND kind = 'activity' AND user_id IN "
                          "(SELECT user_id FROM event_votes WHERE event_id = ? AND kind = 'time')", (pid, pid)).fetchone()[0]
    if n and voted >= n:
        return jobs.enqueue("coordinate_proposal", subject_type="proposal", subject_id=pid, circle_id=e["circle_id"],
                            trigger="all members voted", once_key=f"tally:{pid}")
    return None


# ================================================================ notifications (+ email when configured & opted in)
def _notify(c, uid: str, key: str, kind: str, title: str, body: str, link: str, outbox: list) -> bool:
    if P.notify_once(c, uid, key, kind, title, body, link):
        outbox.append((uid, title, body, link))
        return True
    return False


def _deliver(outbox: list) -> dict:
    """In-app notifications are already stored. Email goes only to people who opted in, and only via configured SMTP."""
    res = {"in_app": len(outbox), "email_sent": 0, "email": "SMTP not configured" if not mailer.enabled() else "configured"}
    if not outbox or not mailer.enabled():
        return res
    with db.read() as c:
        rows = {r["user_id"]: r["email"] for r in c.execute(
            "SELECT a.user_id, a.email FROM accounts a JOIN agent_settings s ON s.user_id = a.user_id WHERE s.email_notify = 1")}
    for uid, title, body, link in outbox:
        if uid in rows and mailer.send(rows[uid], title, f"{body}\n\nOpen: {config.APP_BASE_URL}/{link}\n\n"
                                       "You get this because you turned on agent emails in Culture Connect."):
            res["email_sent"] += 1
    return res


# ================================================================ personalised discovery workflow
# ACCOUNT_CREATED -> ONBOARDING_COMPLETED -> PROFILE_SAVED -> QLOO_RESOLUTION -> CULTURAL_INSIGHTS -> CIRCLE_MATCHING
# -> EVENT_MATCHING -> RANKING -> RECOMMENDATIONS_READY   (each run step's `tool` is the stage key)
STAGES = [("account_created", "Account created"), ("onboarding_completed", "Onboarding completed"),
          ("profile_saved", "Preferences & consent saved"), ("qloo_resolution", "Qloo interest resolution"),
          ("cultural_insights", "Qloo cultural insights"), ("circle_matching", "Circle matching"),
          ("event_matching", "Event matching"), ("ranking", "Ranking"), ("recommendations_ready", "Recommendations ready")]
MAX_DEGRADED_RETRIES = 3
EVENT_RULES = ("Application rank points (not a Qloo score): mentions one of your interests or is hosted by a Circle with the same "
               "Qloo topic +3 · a Qloo interest you saved +2 · linked through your Qloo taste insights +1.5 (max 3) · your own Circle +1 · "
               "near your stated area +1 (elsewhere −0.5) · fits your stated availability +0.5 · verified organisation +0.5. "
               "Past, cancelled, full, closed-RSVP and members-only events you can't see are never recommended.")


def _ideas(entities: list[dict]) -> list[dict]:
    verb = {"book": "Read & discuss", "movie": "Watch & talk about", "tv_show": "Watch & talk about", "podcast": "Listen to",
            "artist": "Listening session:", "place": "Visit", "videogame": "Play together:", "brand": "Explore", "person": "Learn about"}
    out = []
    for e in entities[:6]:
        t = (e.get("type") or "").split(":")[-1]
        out.append({"qloo": {"id": e["id"], "name": e["name"], "type": e.get("type")},
                    "idea": f"{verb.get(t, 'Explore')} {e['name']}",
                    "idea_source": "app (generated text built around a Qloo recommendation)"})
    return out


def _feedback(c, uid) -> tuple[set, list[dict]]:
    rows = c.execute("SELECT * FROM recommendation_feedback WHERE user_id = ?", (uid,)).fetchall()
    dismissed = {(r["item_type"], r["item_id"]) for r in rows if r["action"] == "dismissed"}
    saved = [{"id": r["item_id"], "name": r["label"], "kind": r["kind"]} for r in rows if r["item_type"] == "interest" and r["action"] == "saved"]
    return dismissed, saved


def dismissed_interests(c, uid) -> list[dict]:
    return [{"id": r["item_id"], "name": r["label"]} for r in c.execute(
        "SELECT item_id, label FROM recommendation_feedback WHERE user_id = ? AND item_type = 'interest' AND action = 'dismissed' ORDER BY created_at",
        (uid,)) if r["label"]]


def _cached_taste(uid):
    with db.read() as c:
        r = c.execute("SELECT taste, retrieved_at FROM user_taste WHERE user_id = ?", (uid,)).fetchone()
    return (json.loads(r["taste"]), r["retrieved_at"]) if r else (None, None)


def _words(s: str) -> str:
    return f" {norm(s)} "


def _slot(dt: datetime) -> str:
    return "weekend" if dt.weekday() >= 5 else ("weekday_daytime" if 8 <= dt.hour < 17 else "weekday_evening")


def match_events(c, uid: str, prof: dict, taste: dict | None, saved: list[dict], dismissed: set) -> list[dict]:
    """Real, upcoming, visible, joinable events only — scored with explainable evidence (EVENT_RULES)."""
    interests = prof["interests"]
    my_ids = {s["id"]: it for it in interests for s in it["signals"]}
    labels = {norm(it["label"]): it for it in interests if len(norm(it["label"])) >= 3}
    tnames = {}
    for t in (taste or {}).get("tags", []) + (taste or {}).get("entities", []):
        if t.get("name") and len(norm(t["name"])) >= 3 and norm(t["name"]) not in labels:
            tnames[norm(t["name"])] = t
    tids = {t["id"] for t in (taste or {}).get("tags", []) + (taste or {}).get("entities", []) if t.get("id")}
    saved_names = {norm(s["name"]): s for s in saved if s.get("name")}
    saved_ids = {s["id"] for s in saved}
    member = set(_my_circles(c, uid))
    prefs = set(prof["activity_prefs"])
    out = []
    for e in c.execute("SELECT * FROM events WHERE status = 'published' ORDER BY starts_at LIMIT 500").fetchall():
        if ("event", e["id"]) in dismissed or not P._can_view(c, e, uid) or P._is_past(e):
            continue
        try:
            start, _ = P._abs(e)
        except HTTPException:
            continue
        if e["rsvp_deadline"]:
            try:
                if P._local(e["rsvp_deadline"], "deadline").replace(tzinfo=start.tzinfo) < datetime.now(start.tzinfo):
                    continue
            except HTTPException:
                pass
        card = P._event_card(c, e)
        mine = c.execute("SELECT status FROM event_rsvps WHERE event_id = ? AND user_id = ?", (e["id"], uid)).fetchone()
        if card["display_status"] == "full" and not (mine and mine["status"] == "going"):
            continue
        if prefs and prefs <= {"online"} and e["location_status"] != "online":
            continue
        hay = _words(" ".join(str(e[k] or "") for k in ("title", "description", "category", "purpose")))
        csig, ctopic = [], ""
        if e["circle_id"]:
            csig = [r["qloo_id"] for r in c.execute("SELECT qloo_id FROM circle_signals WHERE circle_id = ?", (e["circle_id"],))]
            ct = c.execute("SELECT topic_label FROM circles WHERE id = ?", (e["circle_id"],)).fetchone()
            ctopic = norm(ct["topic_label"]) if ct else ""
        reasons, score, tags = [], 0.0, []
        hits = [lab for lab in labels if f" {lab} " in hay] or ([ctopic] if ctopic in labels else [])
        sig = next((s for s in csig if s in my_ids), None)
        if hits or sig:
            its = [labels[h] for h in hits] if hits else [my_ids[sig]]
            tags += [it["label"] for it in its]
            names = " and ".join(f"“{it['label']}”" for it in its[:2])
            reasons.append({"source": "declared", "text": (f"Hosted by a Circle whose Qloo topic matches your interest {names}." if sig and not hits
                                                           else f"About {names} — {'one of your interests' if len(its) == 1 else 'your interests'}.")})
            score += 3
        sv = next((s for s in csig if s in saved_ids), None) or next((n for n in saved_names if f" {n} " in hay), None)
        if sv:
            s = next((x for x in saved if x["id"] == sv), None) or saved_names[sv]
            tags.append(s["name"])
            reasons.append({"source": "qloo", "text": f"Matches “{s['name']}”, a Qloo discovery you saved."})
            score += 2
        q = 0.0
        for n, t in tnames.items():
            if f" {n} " in hay and q < 3:
                reasons.append({"source": "qloo", "text": f"Qloo Insights linked your interests to “{t['name']}”, which this event is about."})
                tags.append(t["name"])
                q += 1.5
        for s in csig:
            if s in tids and s not in my_ids and q < 3:
                reasons.append({"source": "qloo", "text": "Qloo Insights for your interests returned this Circle's topic."})
                q += 1.5
        score += q
        if e["circle_id"] in member:
            reasons.append({"source": "app", "text": "From a Circle you belong to."})
            score += 1
        if score <= 0:
            continue
        if e["location_status"] == "online":
            reasons.append({"source": "app", "text": "Online — no travel needed."})
        elif e["location_status"] == "confirmed" and prof["area"]:
            if area_tokens(prof["area"]) & area_tokens(e["address"] + " " + e["venue_name"]):
                reasons.append({"source": "app", "text": f"Near your area ({prof['area']})."})
                score += 1
            else:
                reasons.append({"source": "app", "text": "Not in your stated area — check the address."})
                score -= 0.5
        elif not prof["area"] and e["location_status"] == "confirmed":
            reasons.append({"source": "app", "text": "Add your broad area in your profile to rank nearby events higher."})
        if _slot(start) in prof["availability"]:
            reasons.append({"source": "app", "text": f"Fits your availability ({_slot(start).replace('_', ' ')})."})
            score += 0.5
        own = card["owner"] or {}
        if own.get("kind") == "org" and own.get("verification_status") == "verified":
            reasons.append({"source": "app", "text": "Organised by a verified organisation."})
            score += 0.5
        out.append({"type": "event", "id": e["id"], "title": e["title"], "starts_at": e["starts_at"], "ends_at": e["ends_at"],
                    "timezone": e["timezone"], "location_status": e["location_status"], "venue_name": e["venue_name"] if e["location_status"] != "tbc" else "",
                    "address": card["address"], "owner": card["owner"], "going": card["going"], "capacity": e["capacity"],
                    "display_status": card["display_status"], "my_rsvp": mine["status"] if mine else None,
                    "source": "Culture Connect event", "origin": "organisation" if e["owner_kind"] == "org" else "circle",
                    "reasons": reasons, "score": round(score, 2), "interest_tags": list(dict.fromkeys(tags))[:4], "link": f"#/e/{e['id']}"})
    out.sort(key=lambda x: (-x["score"], x["starts_at"]))
    return out[:30]


def _proposals(c, uid) -> list[dict]:
    mine = _my_circles(c, uid)
    if not mine:
        return []
    rows = c.execute(f"""SELECT e.*, ci.name AS circle_name FROM circle_events e JOIN circles ci ON ci.id = e.circle_id
                         WHERE e.status = 'proposed' AND e.circle_id IN ({','.join('?' * len(mine))}) ORDER BY e.created_at DESC LIMIT 10""",
                      mine).fetchall()
    return [{"type": "proposal", "id": r["id"], "circle_id": r["circle_id"], "circle_name": r["circle_name"], "title": r["title"],
             "by": "planning agent" if r["source"] == "agent" else "a member", "vote_deadline": r["vote_deadline"],
             "label": "Proposal — not a confirmed event", "link": f"#/c/{r['circle_id']}/events"} for r in rows]


def _enqueue_discovery(uid: str, trigger: str, scope: str, force: bool = False, delay: float = 0, retry: int = 0, key: str | None = None):
    return jobs.enqueue("discovery", subject_type="user", subject_id=uid, user_id=uid, trigger=trigger,
                        payload={"force": force, "scope": scope, "retry": retry},
                        dedupe_key=key or (f"discovery:{uid}" if scope == "full" else f"discovery-rerank:{uid}"), delay=delay)


def _can_discover(uid: str, force: bool = False) -> bool:
    with db.read() as c:
        p = circles._profile_row(c, uid)
        s = get_settings(c, uid)
    return bool(p and p["discoverable"] and (s["automation"] or force))


def on_profile_saved(uid: str, trigger: str = "profile saved", force: bool = False) -> str | None:
    """Onboarding / interest or location changes / consent: full discovery (Qloo resolution + insights + matching)."""
    return _enqueue_discovery(uid, trigger, "full", force) if _can_discover(uid, force) else None


def refresh_user(uid: str, trigger: str, delay: float = 0) -> str | None:
    """Targeted refresh: re-match and re-rank with cached Qloo insights (no new Qloo calls)."""
    return _enqueue_discovery(uid, trigger, "rerank", delay=delay) if _can_discover(uid) else None


def _interested_users(c, ids: set, labels: set, text: str, limit: int = 200) -> list[str]:
    hay = _words(text)
    out = []
    for p in c.execute("""SELECT p.user_id FROM profiles p LEFT JOIN agent_settings s ON s.user_id = p.user_id
                          WHERE p.discoverable = 1 AND COALESCE(s.automation, 1) = 1""").fetchall():
        u = p["user_id"]
        ints = circles._interests(c, u)
        hit = any(s["id"] in ids for it in ints for s in it["signals"]) or any(
            norm(it["label"]) in labels or (len(norm(it["label"])) >= 3 and f" {norm(it['label'])} " in hay) for it in ints)
        if not hit:
            t = c.execute("SELECT taste FROM user_taste WHERE user_id = ?", (u,)).fetchone()
            tt = json.loads(t["taste"]) if t else {}
            hit = any(x.get("id") in ids for x in tt.get("tags", []) + tt.get("entities", []))
        if hit:
            out.append(u)
            if len(out) >= limit:
                break
    return out


def on_circle_changed(cid: str, why: str) -> int:
    """A Circle was created/activated: refresh only people whose interests (or Qloo taste) match its topic."""
    with db.read() as c:
        row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
        if not row or row["status"] != "active" or row["visibility"] != "public":
            return 0
        ids = {r["qloo_id"] for r in c.execute("SELECT qloo_id FROM circle_signals WHERE circle_id = ?", (cid,))}
        members = set(r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ?", (cid,)))
        users = [u for u in _interested_users(c, ids, {norm(row["topic_label"])}, row["name"]) if u not in members]
    for u in users:
        refresh_user(u, why)
    return len(users)


def on_event_changed(eid: str, why: str) -> int:
    """Published / updated / cancelled / completed / full: refresh people who already see it, plus newly matching people."""
    with db.read() as c:
        e = c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        if not e:
            return 0
        users = {r[0] for r in c.execute("SELECT user_id FROM user_discovery WHERE payload LIKE ?", (f'%"{eid}"%',))}
        if e["status"] == "published":
            ids, lab = set(), set()
            if e["circle_id"]:
                ids = {r["qloo_id"] for r in c.execute("SELECT qloo_id FROM circle_signals WHERE circle_id = ?", (e["circle_id"],))}
                ct = c.execute("SELECT topic_label FROM circles WHERE id = ?", (e["circle_id"],)).fetchone()
                lab = {norm(ct["topic_label"])} if ct else set()
            users |= set(_interested_users(c, ids, lab, " ".join(str(e[k] or "") for k in ("title", "description", "category", "purpose"))))
    for u in users:
        refresh_user(u, why)
    return len(users)


@jobs.handler("discovery")
def run_discovery(ctx: jobs.Ctx) -> dict:
    uid = ctx.run["user_id"]
    force = bool(ctx.input.get("force"))
    scope = ctx.input.get("scope", "full")

    def profile():
        with db.read() as c:
            p = circles._profile_row(c, uid)
            s = get_settings(c, uid)
        if not p:
            raise jobs.Skip("Onboarding not completed yet — nothing to discover.")
        if not p["discoverable"]:
            raise jobs.Skip("Discovery consent is off — none of your data was processed.")
        if not s["automation"] and not force:
            raise jobs.Skip("Automation is paused in your agent settings.")
        return {"result": True, "message": f"Using the preferences and consent you saved ({'full discovery' if scope == 'full' else 'targeted refresh'}).",
                "sources": [{"type": "database", "detail": "your saved profile (interests, area, availability, budget, preferences, consent)"}]}
    ctx.step("profile", "profile_saved", profile)

    def resolve():
        if scope != "full":
            return {"result": {"added": [], "failed": 0}, "status": "skipped", "message": "Interests unchanged since the last discovery — nothing to resolve."}
        prof = circles.get_profile(uid)
        todo = [it for it in prof["interests"] if not it["signals"]]
        if not todo:
            return {"result": {"added": [], "failed": 0}, "status": "skipped",
                    "message": f"All {len(prof['interests'])} interest(s) already have Qloo IDs (from onboarding or an earlier run)."}
        added, unmatched, failed, sources = [], [], [], []
        for it in todo[:8]:
            try:
                res = circles.resolve_interest(it["label"], None)
            except QlooError as exc:
                failed.append(f"{it['label']}: {exc.status or 'error'}")
                continue
            sources.append({"type": "qloo", "detail": "GET /search + GET /v2/tags + GET /v2/audiences",
                            "query": it["label"], "candidates_returned": len(res.get("candidates", []))})
            cands = {x["id"]: x for x in res.get("candidates", [])}
            picks = [cands[i] for i in res.get("suggested_ids", []) if i in cands and (cands[i].get("match") or 0) >= AUTO_RESOLVE_MATCH][:2]
            if not picks:
                unmatched.append(it["label"])  # ambiguous or no result: kept as a declared interest, nothing invented
                continue
            with db.tx() as c:
                if not c.execute("SELECT 1 FROM profile_interests WHERE id = ? AND user_id = ?", (it["id"], uid)).fetchone():
                    continue
                for k in picks:
                    c.execute("INSERT OR IGNORE INTO interest_signals VALUES (?,?,?,?,?,?,?)",
                              (it["id"], k["id"], k["kind"], k.get("name") or it["label"], k.get("type") or "",
                               f"{k.get('source') or 'Qloo'} · auto-resolved by discovery agent (text match {k['match']:.2f})", now()))
            added.append({"label": it["label"], "qloo": [{"id": k["id"], "kind": k["kind"], "name": k.get("name")} for k in picks]})
        msg = f"Resolved {len(added)} of {len(todo)} interest(s) to Qloo IDs (only text matches ≥ {AUTO_RESOLVE_MATCH})."
        if unmatched:
            msg += f" No confident Qloo match for: {', '.join(unmatched)} — kept as declared interests."
        if failed:
            msg += f" Qloo unavailable for: {', '.join(failed)} (will retry)."
        return {"result": {"added": added, "unmatched": unmatched, "failed": len(failed)}, "message": msg, "sources": sources,
                "status": "warn" if failed or unmatched else "ok"}
    resolved = ctx.step("resolve", "qloo_resolution", resolve)

    def insights():
        prof = circles.get_profile(uid)
        cached, cached_at = _cached_taste(uid)
        if scope != "full" and cached:
            return {"result": {"taste": cached, "degraded": False, "retrieved_at": cached_at}, "status": "skipped",
                    "message": "Reused Qloo insights already retrieved for your interests (no new Qloo call).",
                    "sources": [{"type": "database", "detail": "cached Qloo taste profile"}]}
        before = prof.get("taste_retrieved_at")
        taste, warn = circles._taste(uid, prof["interests"])
        if not taste:
            if warn and cached:  # Qloo down: fall back to the last valid response, clearly marked as degraded
                return {"result": {"taste": cached, "degraded": True, "retrieved_at": cached_at}, "status": "warn",
                        "message": f"{warn} Using Qloo insights cached earlier (degraded); this step will be retried.",
                        "sources": [{"type": "database", "detail": "previously cached Qloo taste profile"}]}
            return {"result": {"taste": None, "degraded": bool(warn), "retrieved_at": None}, "status": "warn",
                    "message": (warn + " No cached Qloo data exists, so recommendations use your declared interests only (degraded); will retry.")
                    if warn else "None of your interests has a Qloo ID, so no Qloo Insights call was made. Recommendations use declared interests."}
        with db.read() as c:
            t = c.execute("SELECT retrieved_at FROM user_taste WHERE user_id = ?", (uid,)).fetchone()
        reused = bool(before and t and t["retrieved_at"] == before)
        srcs = [{"type": "qloo", "detail": "GET /v2/insights" + (" (valid cached response, < 24 h old)" if reused else ""), "params": r}
                for r in taste.get("requests", [])]
        return {"result": {"taste": taste, "degraded": bool(warn), "retrieved_at": t["retrieved_at"] if t else now()},
                "status": "warn" if warn else "ok", "sources": srcs,
                "message": f"Qloo Insights returned {len(taste['tags'])} taste tag(s) and {len(taste['entities'])} cross-category item(s)."
                           + (f" {warn}" if warn else "")}
    ins = ctx.step("insights", "cultural_insights", insights)
    taste = ins["taste"]

    def match_circles():
        with db.read() as c:
            dismissed, saved = _feedback(c, uid)
        rec = circles.recommend(uid, taste_override=(taste, None), extra_signals=saved)
        recs = [r for r in rec["recommendations"] if ("circle", r["id"]) not in dismissed]
        q = sum(1 for r in recs if any(x["source"] == "qloo" for x in r["reasons"]))
        slim = [{"type": "circle", "id": r["id"], "name": r["name"], "topic_label": r["topic_label"], "member_count": r["member_count"],
                 "capacity": r["capacity"], "area": r["area"], "meeting_mode": r["meeting_mode"], "category": r["category"],
                 "join_mode": r.get("join_mode", "direct"), "signals": r["signals"][:3], "reasons": r["reasons"], "score": r.get("score", 0),
                 "org": r.get("org"), "link": f"#/c/{r['id']}"} for r in recs]
        return {"result": {"circles": slim, "create": rec["create_suggestions"], "excluded": rec["excluded"]},
                "message": f"{len(slim)} joinable Circle(s) matched after hard constraints ({sum(rec['excluded'].values())} excluded, "
                           f"{len(rec['recommendations']) - len(slim)} dismissed by you); {q} matched or ranked using Qloo evidence.",
                "sources": [{"type": "database", "detail": "active public Circles, memberships, capacity, blocks"},
                            {"type": "app", "detail": "hard constraints, then declared ×3 · Qloo-linked ×1.5 · saved Qloo interest ×2 · intent · area"}]}
    circ = ctx.step("circles", "circle_matching", match_circles)

    def match_ev():
        prof = circles.get_profile(uid)
        with db.read() as c:
            dismissed, saved = _feedback(c, uid)
            prof_c = circles.get_profile_c(c, uid)
            prof_c["interests"] = prof["interests"]
            evs = match_events(c, uid, prof_c, taste, saved, dismissed)
            props = _proposals(c, uid)
        q = sum(1 for e in evs if any(r["source"] == "qloo" for r in e["reasons"]))
        return {"result": {"events": evs, "proposals": props},
                "message": f"{len(evs)} upcoming Culture Connect event(s) match ({q} through Qloo evidence); {len(props)} activity proposal(s) "
                           "open in your Circles. No external event provider is connected, so no outside listings were added.",
                "sources": [{"type": "database", "detail": "published events you can see, RSVP counts, RSVP deadlines, organisation verification"},
                            {"type": "app", "detail": EVENT_RULES}]}
    ev = ctx.step("events", "event_matching", match_ev)

    def formation():
        if scope != "full":
            return {"result": [], "status": "skipped", "message": "Targeted refresh — Circle formation unchanged."}
        started = []
        for s in circ["create"][:MAX_FORMATIONS_PER_RUN]:
            rid = jobs.enqueue("circle_formation", subject_type="interest", subject_id=str(s["interest_id"]), user_id=uid,
                               trigger=f"discovery found no Circle for “{s['label']}”", payload={"initiator": uid, "label": s["label"]},
                               dedupe_key=f"formation:{uid}:{norm(s['label'])}")
            started.append({"label": s["label"], "run_id": rid})
        return {"result": started, "status": "ok" if started else "skipped",
                "message": ("Started Circle formation for: " + ", ".join(x["label"] for x in started)) if started
                else "Every interest already has a matching Circle."}
    started = ctx.step("formation", "circle_formation_trigger", formation)

    def rank():
        with db.read() as c:
            dismissed, saved = _feedback(c, uid)
        prof = circles.get_profile(uid)
        top = sorted(circ["circles"] + ev["events"], key=lambda x: (-x["score"], x.get("starts_at") or "9999"))
        picked, n = [], {"circle": 0, "event": 0}
        for x in top:
            if n[x["type"]] < 4:
                picked.append({"type": x["type"], "id": x["id"]})
                n[x["type"]] += 1
            if len(picked) == 6:
                break
        declared = {norm(it["label"]) for it in prof["interests"]}
        with_ids = [it["label"] for it in prof["interests"] if it["signals"]]
        saved_ids = {s["id"] for s in saved}
        new = []
        for t in (taste or {}).get("tags", []) + (taste or {}).get("entities", []):
            if not t.get("id") or not t.get("name") or norm(t["name"]) in declared or ("interest", t["id"]) in dismissed:
                continue
            new.append({"id": t["id"], "name": t["name"], "kind": "tag" if t["id"].startswith("urn:tag") or "type" not in t else "entity",
                        "type": t.get("type"), "saved": t["id"] in saved_ids,
                        "because": f"Qloo Insights returned this for your interests: {', '.join(with_ids[:3])}" if with_ids else "Returned by Qloo Insights"})
            if len(new) >= 10:
                break
        with db.read() as c:
            gone = dismissed_interests(c, uid)
        return {"result": {"top": picked, "discover_new": new, "not_interested": gone},
                "message": f"Ranked {len(top)} item(s); {len(picked)} shown in “Recommended for you”, {len(new)} new Qloo interests to explore.",
                "sources": [{"type": "app", "detail": "merge Circles and events by rank points (max 4 of each type), sooner events first on ties"}]}
    ranked = ctx.step("rank", "ranking", rank)

    def ready():
        degraded = bool(ins["degraded"]) or bool(resolved.get("failed"))
        prev = discovery(uid) or {}
        lookup = {(x["type"], x["id"]): x for x in circ["circles"] + ev["events"]}
        top = [lookup[(p["type"], p["id"])] for p in ranked["top"] if (p["type"], p["id"]) in lookup]
        notified = set(prev.get("notified", []))
        fresh = [f"{x['type']}:{x['id']}" for x in top if f"{x['type']}:{x['id']}" not in notified]
        payload = {"top": top, "circles": circ["circles"], "events": ev["events"], "proposals": ev["proposals"],
                   "discover_new": ranked["discover_new"], "not_interested": ranked.get("not_interested", []), "activity_ideas": _ideas((taste or {}).get("entities", [])),
                   "qloo": {"tags": (taste or {}).get("tags", []), "entities": (taste or {}).get("entities", []),
                            "retrieved_at": ins["retrieved_at"]},
                   "formation": started, "degraded": degraded, "scope": scope, "run_id": ctx.id, "generated_at": now(),
                   "external_events": {"configured": False, "note": "No external event provider is connected."},
                   "event_rules": EVENT_RULES, "notified": sorted(notified | set(fresh)),
                   "recommendations": circ["circles"]}  # kept for older clients
        outbox = []
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO user_discovery VALUES (?,?,?,?)", (uid, ctx.id, json.dumps(payload, default=str), now()))
            if fresh:
                _notify(c, uid, f"recs:{uid}:{'|'.join(sorted(fresh))}"[:200], "agent",
                        "New recommendations for you" if prev else "Your personalised recommendations are ready",
                        f"{len(fresh)} new Circle/event match{'es' if len(fresh) != 1 else ''}" + (" (some Qloo data unavailable)" if degraded else ""),
                        "#/dashboard", outbox)
        d = _deliver(outbox)
        retry = None
        if degraded and ctx.input.get("retry", 0) < MAX_DEGRADED_RETRIES:
            retry = _enqueue_discovery(uid, "retry after Qloo was unavailable", "full", delay=300 * (ctx.input.get("retry", 0) + 1),
                                       retry=ctx.input.get("retry", 0) + 1, key=f"discovery-retry:{uid}")
        return {"result": True, "status": "warn" if degraded else "ok",
                "message": f"Saved {len(top)} top picks, {len(circ['circles'])} Circles, {len(ev['events'])} events. "
                           + (f"Notified you about {len(fresh)} new item(s) (in-app; email: {d['email']}). " if fresh else "No new items, so no notification. ")
                           + ("Degraded: some Qloo data was unavailable — a retry is scheduled." if retry else ""),
                "sources": [{"type": "database", "detail": "user_discovery (persisted), notifications"}]}
    ctx.step("ready", "recommendations_ready", ready)
    return {"top": len(ranked["top"]), "circles": len(circ["circles"]), "events": len(ev["events"])}


def discovery_status(uid: str) -> dict:
    with db.read() as c:
        acct = c.execute("SELECT created_at FROM accounts WHERE user_id = ?", (uid,)).fetchone()
        prof = circles._profile_row(c, uid)
        # a scheduled retry (queued for later) doesn't hide the result of the run that just finished
        run = c.execute("""SELECT * FROM agent_runs WHERE user_id = ? AND kind = 'discovery' AND NOT (status = 'queued' AND next_run_at > ?)
                           ORDER BY created_at DESC LIMIT 1""", (uid, now())).fetchone()
        retry = c.execute("SELECT next_run_at FROM agent_runs WHERE user_id = ? AND kind = 'discovery' AND status = 'queued' AND next_run_at > ?",
                          (uid, now())).fetchone()
        steps = {s["tool"]: s for s in c.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY id", (run["id"],))} if run else {}
    stages = [{"key": "account_created", "label": STAGES[0][1], "state": "done" if acct else "pending", "at": acct["created_at"] if acct else None},
              {"key": "onboarding_completed", "label": STAGES[1][1], "state": "done" if prof else "pending", "at": prof["updated_at"] if prof else None}]
    for key, label in STAGES[2:]:
        s = steps.get(key)
        st = {"ok": "done", "warn": "warning", "skipped": "skipped", "error": "failed", "running": "running"}.get(s["status"]) if s else \
            ("pending" if run and run["status"] in ("queued", "running") else "not_run")
        stages.append({"key": key, "label": label, "state": st, "at": s["finished_at"] if s else None, "message": s["message"] if s else ""})
    if not prof:
        state = "onboarding"
    elif not prof["discoverable"]:
        state = "consent_off"
    elif not run:
        state = "not_started"
    else:
        state = {"queued": "running", "running": "running", "failed": "failed", "paused": "paused", "skipped": "skipped",
                 "cancelled": "failed"}.get(run["status"], "ready")
    return {"state": state, "run_id": run["id"] if run else None, "trigger": run["trigger"] if run else None,
            "error": run["error"] if run else "", "attempts": run["attempts"] if run else 0, "stages": stages,
            "updated_at": run["updated_at"] if run else None, "retry_at": retry["next_run_at"] if retry else None}


def record_feedback(uid: str, item_type: str, item_id: str, action: str) -> dict:
    """Save / dismiss a recommendation (or 'clear' it). Saved interests must be ones Qloo actually returned for this person."""
    label, kind = "", ""
    with db.tx() as c:
        if action == "clear":
            c.execute("DELETE FROM recommendation_feedback WHERE user_id = ? AND item_type = ? AND item_id = ?", (uid, item_type, item_id))
        else:
            if item_type == "interest":
                prev = c.execute("SELECT label, kind FROM recommendation_feedback WHERE user_id = ? AND item_type = 'interest' AND item_id = ?",
                                 (uid, item_id)).fetchone()
                t = c.execute("SELECT taste FROM user_taste WHERE user_id = ?", (uid,)).fetchone()
                items = (json.loads(t["taste"]) if t else {})
                hit = next((x for x in items.get("tags", []) + items.get("entities", []) if x.get("id") == item_id), None)
                if not hit and prev:  # moving an item you already saved/dismissed between groups
                    hit = {"id": item_id, "name": prev["label"]}
                    items = {"tags": [hit]} if prev["kind"] == "tag" else {"entities": [hit]}
                if not hit:
                    raise HTTPException(404, "That interest wasn't in your Qloo discoveries.")
                label, kind = hit["name"], "tag" if hit in items.get("tags", []) else "entity"
            elif item_type == "circle" and not c.execute("SELECT 1 FROM circles WHERE id = ?", (item_id,)).fetchone():
                raise HTTPException(404, "Circle not found.")
            elif item_type == "event" and not c.execute("SELECT 1 FROM events WHERE id = ?", (item_id,)).fetchone():
                raise HTTPException(404, "Event not found.")
            c.execute("INSERT OR REPLACE INTO recommendation_feedback VALUES (?,?,?,?,?,?,?)", (uid, item_type, item_id, action, label, kind, now()))
    rid = refresh_user(uid, f"you {action if action != 'clear' else 'reset'} a recommendation")
    return {"ok": True, "run_id": rid}


# ================================================================ circle formation workflow
def _mode_area(p) -> tuple[str, str, str]:
    prefs = set(pl(p["activity_prefs"]))
    if not p["area"].strip() or (prefs and prefs <= {"online"}):
        return "online", "", "online"
    return "either", p["area"].strip()[:60], " ".join(sorted(area_tokens(p["area"])))


def _blocked(c, a, b) -> bool:
    return bool(c.execute("SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)",
                          (a, b, b, a)).fetchone())


def find_candidates(c, init_uid: str, topic: dict) -> tuple[list[dict], dict]:
    """Deterministic, documented matching (MATCH_RULES). Returns (eligible people, counts of exclusions by reason)."""
    init = circles.get_profile_c(c, init_uid)
    ids = {s["id"] for s in topic["signals"]}
    out, excluded = [], {}

    def ex(k):
        excluded[k] = excluded.get(k, 0) + 1
    rows = c.execute("""SELECT p.user_id, COALESCE(s.automation, 1) AS automation, COALESCE(s.circle_invites, 1) AS invites
                        FROM profiles p LEFT JOIN agent_settings s ON s.user_id = p.user_id WHERE p.discoverable = 1""").fetchall()
    for r in rows:
        u = r["user_id"]
        me = u == init_uid
        if not me and (not r["automation"] or not r["invites"]):
            ex("opted out of agent invites")
            continue
        prof = circles.get_profile_c(c, u)
        ints = circles._interests(c, u)
        reasons, score = [], 0.0
        decl = next((it for it in ints if norm(it["label"]) == norm(topic["label"]) or any(s["id"] in ids for s in it["signals"])), None)
        if decl:
            same_id = next((s for s in decl["signals"] if s["id"] in ids), None)
            reasons.append({"source": "declared", "text": f"You listed “{decl['label']}”"
                            + (f" — the same Qloo {same_id['kind']} “{same_id['name']}” as this topic." if same_id else ", the topic of this Circle.")})
            score += 3
        else:
            t = c.execute("SELECT taste FROM user_taste WHERE user_id = ?", (u,)).fetchone()
            taste = json.loads(t["taste"]) if t else {}
            hit = next((x for x in taste.get("tags", []) + taste.get("entities", []) if x.get("id") in ids), None)
            if not hit:
                continue
            reasons.append({"source": "qloo", "text": f"Qloo Insights for your interests returned “{hit['name']}”, which is this Circle's topic."})
            score += 1.5
        if not me:
            if topic["mode"] != "online" and not (area_tokens(prof["area"]) & area_tokens(topic["area"])):
                ex("different area")
                continue
            prefs = set(prof["activity_prefs"])
            if topic["mode"] == "online" and prefs and "online" not in prefs:
                ex("prefers in-person only")
                continue
            if init["language"] and prof["language"] and norm(init["language"]) != norm(prof["language"]):
                ex("different language")
                continue
            if any(norm(x) and norm(x) in norm(topic["label"]) for x in prof["exclude_topics"]):
                ex("topic excluded by the person")
                continue
            if _blocked(c, init_uid, u):
                ex("blocked")
                continue
            shared = sorted(set(prof["availability"]) & set(init["availability"]))
            if shared:
                score += 0.5 * len(shared)
                reasons.append({"source": "app", "text": "Overlapping availability: " + ", ".join(s.replace("_", " ") for s in shared) + "."})
            mine = next((it for it in circles._interests(c, init_uid) if norm(it["label"]) == norm(topic["label"])), None)
            if decl and mine and {decl["intent"], mine["intent"]} == {"teach", "learn"}:
                score += 1
                reasons.append({"source": "app", "text": "Complementary goals: someone wants to teach and someone wants to learn."})
        out.append({"user_id": u, "score": round(score, 2), "reasons": reasons, "initiator": me,
                    "intent": decl["intent"] if decl else "enjoy"})
    out.sort(key=lambda x: (not x["initiator"], -x["score"], x["user_id"]))
    return out[:MAX_INVITES], excluded


def _existing_circle(c, topic: dict):
    ids = [s["id"] for s in topic["signals"]]
    return c.execute("SELECT id, name FROM circles WHERE status = 'active' AND visibility = 'public' AND area_key = ? AND "
                     "(topic_key = ? OR id IN (SELECT circle_id FROM circle_signals WHERE qloo_id IN (%s)))" % (",".join("?" * len(ids)) or "''"),
                     (topic["area_key"], topic["topic_key"], *ids)).fetchone()


@jobs.handler("circle_formation")
def run_formation(ctx: jobs.Ctx) -> dict:
    uid = ctx.input["initiator"]
    label = ctx.input["label"]

    def load():
        with db.read() as c:
            p = circles._profile_row(c, uid)
            if not p or not p["discoverable"]:
                raise jobs.Skip("Initiator's discovery consent is off.")
            it = next((x for x in circles._interests(c, uid) if norm(x["label"]) == norm(label)), None)
        if not it:
            raise jobs.Skip(f"“{label}” is no longer in the profile.")
        mode, area, akey = _mode_area(p)
        topic = {"label": it["label"], "topic_key": "label:" + norm(it["label"]), "area_key": akey, "area": area, "mode": mode,
                 "language": p["language"], "intent": it["intent"],
                 "signals": [{"id": s["id"], "kind": s["kind"], "name": s["name"], "type": s["type"]} for s in it["signals"]],
                 "category": circles.suggest_category(it["label"], it["signals"])}
        return {"result": topic, "message": f"Topic “{topic['label']}” · {'online' if mode == 'online' else 'in person or online around ' + area}"
                + (f" · {len(topic['signals'])} Qloo ID(s)" if topic["signals"] else " · no Qloo ID (label match only)"),
                "sources": [{"type": "database", "detail": "initiator's saved interest and preferences"}]}
    topic = ctx.step("load", "load_topic", load)

    def reuse():
        with db.read() as c:
            ex = _existing_circle(c, topic)
        if not ex:
            return {"result": None, "status": "skipped", "message": "No existing public Circle for this topic and area."}
        outbox = []
        with db.tx() as c:
            _notify(c, uid, f"reuse:{ex['id']}:{uid}", "agent", f"A Circle for “{topic['label']}” already exists",
                    f"{ex['name']} — the agent didn't create a duplicate.", f"#/c/{ex['id']}", outbox)
        _deliver(outbox)
        return {"result": {"circle_id": ex["id"], "name": ex["name"]},
                "message": f"Reused existing Circle “{ex['name']}” instead of creating a duplicate; it appears in your recommendations "
                           "if you meet its constraints.", "sources": [{"type": "database", "detail": "circles (duplicate check by topic + area)"}]}
    existing = ctx.step("reuse", "check_duplicates", reuse)
    if existing:
        return {"reused_circle": existing["circle_id"]}

    def candidates():
        with db.read() as c:
            people, excluded = find_candidates(c, uid, topic)
        q = sum(1 for p in people if any(r["source"] == "qloo" for r in p["reasons"]))
        return {"result": people,
                "message": f"{len(people)} consenting, eligible people match (including you); {q} matched through Qloo Insights evidence. "
                           f"Excluded by hard constraints: {json.dumps(excluded) if excluded else 'none'}.",
                "sources": [{"type": "database", "detail": "profiles with discovery consent, declared interests, cached Qloo taste profiles"},
                            {"type": "app", "detail": "MATCH_RULES (deterministic, documented in the Activity Centre)"}],
                "data": {"eligible": len(people), "qloo_matched": q, "excluded": excluded}}  # counts only — never other people's ids
    people = ctx.step("candidates", "match_members", candidates)

    def upsert():
        outbox = []
        min_size = config.AGENT_MIN_CIRCLE
        with db.tx() as c:
            p = c.execute("SELECT * FROM circle_proposals WHERE topic_key = ? AND area_key = ? AND status IN ('gathering','open')",
                          (topic["topic_key"], topic["area_key"])).fetchone()
            if not p:
                pid = "P" + uuid.uuid4().hex[:10]
                name = (f"{topic['label']} Circle" + (f" · {topic['area']}" if topic["area"] else " · Online"))[:80]
                desc = (f"People nearby who share an interest in {topic['label']}." if topic["mode"] != "online"
                        else f"An online Circle for people who share an interest in {topic['label']}.")
                c.execute("""INSERT INTO circle_proposals (id, topic_key, area_key, topic_label, name, description, category, meeting_mode,
                             area, language, signals, min_size, status, created_by_run, created_at, updated_at)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'gathering', ?, ?, ?)""",
                          (pid, topic["topic_key"], topic["area_key"], topic["label"], name if len(name) >= 3 else name + " Circle", desc,
                           topic["category"], topic["mode"], topic["area"], topic["language"], json.dumps(topic["signals"]), min_size,
                           ctx.id, now(), now()))
                p = c.execute("SELECT * FROM circle_proposals WHERE id = ?", (pid,)).fetchone()
                created = True
            else:
                created = False
            for x in people:
                c.execute("""INSERT INTO circle_proposal_members (proposal_id, user_id, role, status, score, reasons, created_at, updated_at)
                             VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id, user_id) DO UPDATE SET score = excluded.score,
                             reasons = excluded.reasons, updated_at = excluded.updated_at""",
                          (p["id"], x["user_id"], "initiator" if x["initiator"] else "invitee",
                           "invited" if p["status"] == "open" else "candidate", x["score"], json.dumps(x["reasons"]), now(), now()))
            live = c.execute("SELECT COUNT(*) FROM circle_proposal_members WHERE proposal_id = ? AND status IN ('candidate','invited','accepted')",
                             (p["id"],)).fetchone()[0]
            invited = 0
            if live >= p["min_size"]:
                c.execute("UPDATE circle_proposals SET status = 'open', updated_at = ? WHERE id = ? AND status = 'gathering'", (now(), p["id"]))
                c.execute("UPDATE circle_proposal_members SET status = 'invited', updated_at = ? WHERE proposal_id = ? AND status = 'candidate'",
                          (now(), p["id"]))
                for m in c.execute("SELECT user_id FROM circle_proposal_members WHERE proposal_id = ? AND status = 'invited'", (p["id"],)).fetchall():
                    if _notify(c, m["user_id"], f"cprop-invite:{p['id']}:{m['user_id']}", "agent",
                               f"You're invited to a new Circle: {p['name']}",
                               "The Circle agent matched you with people who share this interest. Accept or decline — "
                               "nobody is added without accepting.", "#/agent", outbox):
                        invited += 1
            status = c.execute("SELECT status FROM circle_proposals WHERE id = ?", (p["id"],)).fetchone()["status"]
        d = _deliver(outbox)
        msg = (f"{'Created' if created else 'Updated'} Circle proposal “{p['name']}” ({live} eligible, minimum {p['min_size']}). "
               + (f"Status: open — {invited} new invitation(s) sent (in-app; email: {d['email']})." if status == "open"
                  else f"Status: gathering — waiting for {p['min_size'] - live} more matching person(s) before inviting anyone."))
        return {"result": {"proposal_id": p["id"], "status": status, "eligible": live}, "message": msg,
                "sources": [{"type": "database", "detail": "circle_proposals (one open proposal per topic + area)"}]}
    res = ctx.step("proposal", "upsert_circle_proposal", upsert)
    return res


def _form_circle(c, prop, outbox: list) -> str:
    """Create the Circle from members who ACCEPTED (inside the caller's transaction). Reuses a Circle created meanwhile."""
    acc = c.execute("SELECT * FROM circle_proposal_members WHERE proposal_id = ? AND status = 'accepted' ORDER BY updated_at",
                    (prop["id"],)).fetchall()
    topic = {"topic_key": prop["topic_key"], "area_key": prop["area_key"], "signals": json.loads(prop["signals"])}
    ex = _existing_circle(c, topic)
    if ex:
        cid = ex["id"]
    else:
        cid = "C" + uuid.uuid4().hex[:10]
        intents = ["discuss", "enjoy"]
        c.execute("""INSERT INTO circles (id, name, purpose, topic_label, topic_key, category, visibility, meeting_mode, area, area_key,
                     language, intents, accessibility, capacity, min_size, member_events, host_id, created_at, updated_at)
                     VALUES (?,?,?,?,?,?, 'public', ?,?,?,?,?,?, 12, ?, 1, ?, ?, ?)""",
                  (cid, prop["name"], prop["description"] + " Formed by the Circle agent from members who accepted an invitation.",
                   prop["topic_label"], prop["topic_key"], prop["category"], prop["meeting_mode"], prop["area"], prop["area_key"],
                   prop["language"], jl(intents), jl(["flexible_participation"]), max(2, min(prop["min_size"], 10)), acc[0]["user_id"], now(), now()))
        for s in topic["signals"]:
            c.execute("INSERT OR IGNORE INTO circle_signals VALUES (?,?,?,?,?)", (cid, s["id"], s["kind"], s["name"], s.get("type") or ""))
    for i, m in enumerate(acc):
        role = "host" if (not ex and i == 0) else "member"
        c.execute("INSERT INTO memberships VALUES (?,?,?,?,?) ON CONFLICT(circle_id, user_id) DO UPDATE SET status = 'active'",
                  (cid, m["user_id"], role, "active", now()))
        _notify(c, m["user_id"], f"cprop-formed:{prop['id']}:{m['user_id']}", "agent", f"Your Circle is ready: {prop['name']}",
                f"{len(acc)} people accepted. The planning agent will now draft a first activity.", f"#/c/{cid}", outbox)
    c.execute("UPDATE circle_proposals SET status = 'formed', circle_id = ?, updated_at = ? WHERE id = ?", (cid, now(), prop["id"]))
    return cid


def respond_invite(uid: str, pid: str, action: str) -> dict:
    outbox, formed, join_cid = [], None, None
    with db.tx() as c:
        prop = c.execute("SELECT * FROM circle_proposals WHERE id = ?", (pid,)).fetchone()
        m = c.execute("SELECT * FROM circle_proposal_members WHERE proposal_id = ? AND user_id = ?", (pid, uid)).fetchone() if prop else None
        if not prop or not m or m["status"] == "candidate":
            raise HTTPException(404, "Invitation not found.")
        if action == "accept":
            if prop["status"] == "cancelled":
                raise HTTPException(409, "This proposal was cancelled.")
            if m["status"] == "accepted":
                return invite_view(uid, pid)
            if prop["status"] == "formed":
                join_cid = prop["circle_id"]
            else:
                c.execute("UPDATE circle_proposal_members SET status = 'accepted', updated_at = ? WHERE proposal_id = ? AND user_id = ?",
                          (now(), pid, uid))
                n = c.execute("SELECT COUNT(*) FROM circle_proposal_members WHERE proposal_id = ? AND status = 'accepted'", (pid,)).fetchone()[0]
                if n >= prop["min_size"]:
                    formed = _form_circle(c, prop, outbox)
        elif action in ("decline", "withdraw"):
            if prop["status"] == "formed" and m["status"] == "accepted":
                raise HTTPException(409, "The Circle has formed — leave it from the Circle page instead.")
            c.execute("UPDATE circle_proposal_members SET status = ?, updated_at = ? WHERE proposal_id = ? AND user_id = ?",
                      ("declined" if action == "decline" else "withdrawn", now(), pid, uid))
        else:
            raise HTTPException(400, "Unknown action.")
    if join_cid:  # Circle already formed: join through the normal path (hard constraints, capacity, blocks apply)
        circles.join(uid, join_cid)
        with db.tx() as c:
            c.execute("UPDATE circle_proposal_members SET status = 'accepted', updated_at = ? WHERE proposal_id = ? AND user_id = ?",
                      (now(), pid, uid))
        on_membership_changed(join_cid, "member accepted an agent invitation")
    _deliver(outbox)
    if formed:
        on_membership_changed(formed, "Circle formed from accepted invitations")
        on_circle_changed(formed, "a new Circle matching your interests was formed")
    refresh_user(uid, f"you {action}ed a Circle invitation" if action != "decline" else "you declined a Circle invitation")
    return invite_view(uid, pid)


def invite_view(uid: str, pid: str) -> dict:
    with db.read() as c:
        p = c.execute("SELECT * FROM circle_proposals WHERE id = ?", (pid,)).fetchone()
        m = c.execute("SELECT * FROM circle_proposal_members WHERE proposal_id = ? AND user_id = ?", (pid, uid)).fetchone()
        if not p or not m or m["status"] == "candidate" and m["role"] != "initiator":
            raise HTTPException(404, "Invitation not found.")
        counts = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM circle_proposal_members WHERE proposal_id = ? GROUP BY status", (pid,))}
    return {"id": p["id"], "name": p["name"], "description": p["description"], "topic_label": p["topic_label"],
            "meeting_mode": p["meeting_mode"], "area": p["area"], "category": p["category"], "notice": circles.NOTICES.get(p["category"]),
            "signals": json.loads(p["signals"]), "status": p["status"], "circle_id": p["circle_id"], "min_size": p["min_size"],
            "my_status": m["status"], "my_role": m["role"], "my_reasons": json.loads(m["reasons"]),
            "counts": {"accepted": counts.get("accepted", 0), "invited": counts.get("invited", 0) + counts.get("accepted", 0),
                       "eligible": counts.get("candidate", 0) + counts.get("invited", 0) + counts.get("accepted", 0)},
            "description_source": "app (generated by the Circle agent)", "match_rules": MATCH_RULES}


def my_invites(uid: str) -> list[dict]:
    with db.read() as c:
        rows = c.execute("""SELECT p.id FROM circle_proposal_members m JOIN circle_proposals p ON p.id = m.proposal_id
                            WHERE m.user_id = ? AND p.status <> 'cancelled' AND (m.status IN ('invited','accepted','declined','withdrawn')
                            OR (m.role = 'initiator' AND p.status = 'gathering')) ORDER BY p.updated_at DESC LIMIT 20""", (uid,)).fetchall()
    return [invite_view(uid, r["id"]) for r in rows]


# ================================================================ event planning workflow
def _hours_for(hours, day: str):
    """Qloo place 'hours' -> list of (open, close) times for a weekday, or None if the format isn't recognised."""
    if not isinstance(hours, dict):
        return None
    for k, v in hours.items():
        if str(k).strip().lower()[:3] != day[:3]:
            continue
        out = []
        for slot in (v if isinstance(v, list) else [v]):
            if isinstance(slot, dict):
                if slot.get("closed") is True:
                    continue
                a = re.search(r"(\d{1,2}):(\d{2})", str(slot.get("opens") or slot.get("open") or ""))
                b = re.search(r"(\d{1,2}):(\d{2})", str(slot.get("closes") or slot.get("close") or ""))
                if a and b:
                    out.append((dtime(int(a[1]) % 24, int(a[2])), dtime(int(b[1]) % 24, int(b[2]))))
        return out
    return None


def _open_at(hours, dt: datetime, minutes: int):
    slots = _hours_for(hours, DAYS[dt.weekday()])
    if slots is None:
        return None  # unknown
    end = (dt + timedelta(minutes=minutes)).time()
    return any(o <= dt.time() and (end <= cl or cl <= o) for o, cl in slots)


def schedule_options(profs: list[dict], tz, start_days: int = 3, horizon: int = 14, n: int = 3) -> list[dict]:
    """Rank concrete slots by how many members STATED availability for them (unstated availability is reported, never assumed)."""
    today = datetime.now(tz).date()
    cands = []
    for d in range(start_days, start_days + horizon):
        day = today + timedelta(days=d)
        for slot, times in SLOT_TIMES.items():
            if (slot == "weekend") != (day.weekday() >= 5):
                continue
            for hh, mm in times:
                avail = sum(1 for p in profs if slot in p["availability"])
                cands.append({"time": datetime.combine(day, dtime(hh, mm)).isoformat(timespec="minutes"), "slot": slot,
                              "available": avail, "unknown": sum(1 for p in profs if not p["availability"]), "members": len(profs)})
    cands.sort(key=lambda x: (-x["available"], x["time"]))
    chosen, days = [], set()
    for x in cands:
        if x["time"][:10] in days:
            continue
        chosen.append(x)
        days.add(x["time"][:10])
        if len(chosen) == n:
            break
    return sorted(chosen, key=lambda x: x["time"])


def validate_venue(v: dict, times: list[str], minutes: int, needs: set) -> dict:
    fields = {"name": "verified · Qloo place result" if v.get("name") else "missing",
              "address": "verified · returned by Qloo" if v.get("address") else "missing — not provided by Qloo",
              "coordinates": "verified · returned by Qloo" if v.get("lat") is not None else "missing — no map pin",
              "hours": "listed by Qloo" if _hours_for(v.get("hours"), "monday") is not None else "not provided — check with the venue",
              "operating_status": "permanently closed (Qloo)" if v.get("is_closed") is True else
                                  ("open (Qloo)" if v.get("is_closed") is False else "not provided"),
              "capacity_and_booking": "not verified — no booking provider is connected; contact the venue",
              "price": f"Qloo price level {v['price_level']}" if v.get("price_level") not in (None, "") else "not provided"}
    if "wheelchair" in needs:
        fields["wheelchair_access"] = "not verified by any provider — confirm with the venue"
    open_at = {}
    for t in times:
        o = _open_at(v.get("hours"), datetime.fromisoformat(t), minutes)
        open_at[t] = "open" if o else ("closed" if o is False else "unknown")
    if v.get("is_closed") is True:
        status = "rejected"
    elif v.get("address") and v.get("lat") is not None:
        status = "verified"
    else:
        status = "partial"
    return {"status": status, "fields": fields, "open_at": open_at, "qloo_id": v.get("id"),
            "unresolved": [k for k, s in fields.items() if s.startswith(("missing", "not"))]}


def _feedback_inputs(c, cid) -> dict:
    names = {f["name"]: k for k, f in planner.FORMATS.items()}
    rows = c.execute("""SELECT e.category, AVG(f.rating) avg, COUNT(*) n FROM events e JOIN event_feedback f ON f.event_id = e.id
                        WHERE e.circle_id = ? GROUP BY e.category""", (cid,)).fetchall()
    low = [names[r["category"]] for r in rows if r["category"] in names and r["n"] >= 2 and r["avg"] <= 2.5]
    return {"excluded_formats": low, "ratings": [{"format": r["category"], "avg": round(r["avg"], 2), "n": r["n"]} for r in rows]}


@jobs.handler("event_planning")
def run_planning(ctx: jobs.Ctx) -> dict:
    cid = ctx.run["circle_id"]
    force = bool(ctx.input.get("force"))

    def load():
        with db.read() as c:
            row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
            if not row or row["status"] != "active":
                raise jobs.Skip("Circle is not active.")
            if not row["auto_plan"] and not force:
                raise jobs.Skip("Automatic planning is turned off for this Circle.")
            if _open_agent_draft(c, cid):
                raise jobs.Skip("An agent-drafted activity is already open for voting.")
            _, profs = circles._group_for_planner(c, cid, row)
            if len(profs) < row["min_size"]:
                raise jobs.Skip(f"Only {len(profs)} active member(s); planning starts at {row['min_size']}.")
            host = c.execute("SELECT timezone FROM profiles WHERE user_id = ?", (row["host_id"],)).fetchone() if row["host_id"] else None
            fb = _feedback_inputs(c, cid)
        try:
            tzname = P._tz((host["timezone"] if host else "") or "UTC").key
        except HTTPException:
            tzname = "UTC"
        caps = [p["budget_max"] for p in profs if p.get("budget_max") is not None]
        needs = sorted({x for p in profs for x in p["accessibility"]})
        goals = sorted({{"enjoy": "connect", "teach": "learn", "learn": "learn", "discuss": "debate" if row["category"] == "political" else "support",
                         "collaborate": "create"}.get(i, "connect") for i in pl(row["intents"])}) or ["connect"]
        cons = {"duration_min": 90, "budget": round(min(caps) * len(profs), 2) if caps else 50.0, "currency": "USD",
                "setting": "online" if row["meeting_mode"] == "online" else "any", "wheelchair": "wheelchair" in needs,
                "quiet_space": "quiet_space" in needs, "visual_aids": "visual_aids" in needs, "flexible_participation": True,
                "sensitive_topic": row["category"] != "general", "goals": goals, "language": row["language"], "timezone": tzname}
        return {"result": {"cons": cons, "members": len(profs), "needs": needs, "feedback": fb,
                           "location": row["area"] if row["meeting_mode"] != "online" else None},
                "message": f"{len(profs)} active members · budget {'from the lowest personal limit' if caps else 'not stated by members — application default 50 total'}"
                           f" · {row['meeting_mode'].replace('_', ' ')}" + (f" around {row['area']}" if row["area"] else "")
                           + (f" · past feedback excludes: {', '.join(fb['excluded_formats'])}" if fb["excluded_formats"] else "")
                           + f" · timezone {tzname}",
                "sources": [{"type": "database", "detail": "Circle settings, members' private constraints (aggregated only), past event feedback"}],
                "data": {"feedback": fb["ratings"]}}
    base = ctx.step("load", "read_circle", load)

    def culture():
        with db.read() as c:
            row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
            group, _ = circles._group_for_planner(c, cid, row)
        plan = planner.run_agent(group, base["cons"], base["location"], excluded={"themes": [], "formats": base["feedback"]["excluded_formats"]})
        anchors = plan.get("anchors") or {}
        concepts = plan.get("concepts", [])[:3]
        if not concepts:
            raise jobs.Skip(plan.get("fallback") or "The planner found no evidence-backed activity; nothing was invented.")
        srcs = [{"type": "qloo", "detail": "GET /v2/insights (explainability on)", "params": r} for r in anchors.get("requests", [])]
        warns = anchors.get("warnings", [])
        return {"result": {"concepts": concepts, "evidence": plan.get("evidence", []), "trace": plan.get("trace", []),
                           "venues": anchors.get("venues", []), "anchors": [{"id": a["id"], "name": a["name"], "type": a.get("type"),
                                                                              "driven_by_count": len(a.get("driven_by") or [])}
                                                                             for a in anchors.get("anchors", [])]},
                "status": "warn" if warns else "ok",
                "message": f"Qloo returned {len(anchors.get('anchors', []))} cultural anchor(s) and {len(anchors.get('venues', []))} place result(s); "
                           f"{concepts[0]['generated_by']} drafted {len(concepts)} distinct option(s)."
                           + (f" Qloo warnings: {'; '.join(map(str, warns))[:300]}" if warns else ""),
                "sources": srcs + [{"type": "app", "detail": "planner: " + concepts[0]["generated_by"]}],
                "data": {"titles": [k["title"] for k in concepts]}}
    plan = ctx.step("culture", "qloo_cultural_plan", culture)

    def schedule():
        with db.read() as c:
            row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
            _, profs = circles._group_for_planner(c, cid, row)
        opts = schedule_options(profs, P._tz(base["cons"]["timezone"]))
        unknown = opts[0]["unknown"] if opts else 0
        return {"result": opts,
                "message": "Proposed times: " + "; ".join(f"{o['time'].replace('T', ' ')} ({o['available']}/{o['members']} stated availability)" for o in opts)
                           + (f". {unknown} member(s) haven't stated availability — counted as unknown, not available." if unknown else "."),
                "sources": [{"type": "database", "detail": "members' stated availability (aggregated counts only)"}],
                "status": "warn" if opts and opts[0]["available"] == 0 else "ok"}
    times = ctx.step("schedule", "find_time_options", schedule)

    def venues():
        if base["location"] is None:
            return {"result": [], "status": "skipped", "message": "Online Circle — no venue needed; the host shares a call link."}
        ts = [t["time"] for t in times]
        checked = []
        for v in plan["venues"][:6]:
            v = dict(v, address=v["address"].strip() if isinstance(v.get("address"), str) else None,
                     name=v["name"].strip() if isinstance(v.get("name"), str) else None)
            val = validate_venue(v, ts, base["cons"]["duration_min"], set(base["needs"]))
            checked.append({"name": v.get("name"), "address": v.get("address"), "lat": v.get("lat"), "lon": v.get("lon"),
                            "website": v.get("website"), "price_level": v.get("price_level"), "qloo_id": v.get("id"), "validation": val})
        usable = [x for x in checked if x["validation"]["status"] != "rejected" and len(x["address"] or "") >= 3
                  and 2 <= len(x["name"] or "") <= 120]
        msg = (f"Checked {len(checked)} Qloo place result(s) near {base['location']}: "
               f"{sum(x['validation']['status'] == 'verified' for x in checked)} with address + coordinates, "
               f"{sum(x['validation']['status'] == 'partial' for x in checked)} partial, "
               f"{sum(x['validation']['status'] == 'rejected' for x in checked)} rejected (closed). "
               if checked else f"Qloo returned no place results near {base['location']}. ")
        msg += "Booking and capacity are never verified automatically — the venue must be contacted."
        return {"result": usable[:4], "status": "ok" if usable else "warn", "message": msg,
                "sources": [{"type": "qloo", "detail": f"GET /v2/insights filter.type=urn:entity:place filter.location.query={base['location']}"}],
                "data": {"checked": [{"name": x["name"], "status": x["validation"]["status"], "unresolved": x["validation"]["unresolved"]} for x in checked]}}
    places = ctx.step("venues", "validate_venues", venues)

    def persist():
        outbox = []
        with db.tx() as c:
            row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
            _, profs = circles._group_for_planner(c, cid, row)
            ts = [t["time"] for t in times]
            concepts = plan["concepts"]
            for k in concepts:
                k["checks"] = circles._checks(k, base["cons"], row, profs, ts, row["capacity"], confirm=False)
                k["checks"] = [x for x in k["checks"] if not x["check"].startswith("Time option")]  # replaced by stated-availability counts
                for i, t in enumerate(times):
                    k["checks"].append({"check": f"Time option {i + 1}", "status": "pass" if t["available"] >= min(row["min_size"], t["members"]) else "warn",
                                        "note": f"{t['available']} of {t['members']} member(s) stated availability for this slot"
                                                + (f"; {t['unknown']} unknown" if t["unknown"] else "")})
                k["unresolved_questions"] = (["Meeting place: vote on the verified Qloo places below, or add one."] if places
                                             else ["Meeting place not resolved — no verified venue was found; members can add one."]) \
                    if row["meeting_mode"] != "online" else ["Which video-call link will the host share?"]
                k["unresolved_questions"].append("Costs are planning estimates, not quotes.")
            pid = "E" + uuid.uuid4().hex[:10]
            stored = {"concepts": concepts, "evidence": plan["evidence"], "trace": plan["trace"], "fallback": None,
                      "planner": concepts[0]["generated_by"], "agent": {"run_id": ctx.id, "schedule": times, "venues": places,
                                                                         "anchors": plan["anchors"]}}
            try:
                c.execute("""INSERT INTO circle_events (id, circle_id, proposer_id, title, constraints, plan, time_options, capacity,
                             location_note, created_at, source, run_id, vote_deadline) VALUES (?,?,NULL,?,?,?,?,?,?,?, 'agent', ?, ?)""",
                          (pid, cid, concepts[0]["title"][:100], json.dumps(base["cons"]), json.dumps(stored, default=str), json.dumps(ts),
                           row["capacity"], "", now(), ctx.id, now() + config.AGENT_VOTE_HOURS * 3600))
            except sqlite3.IntegrityError:
                raise jobs.Skip("Another agent draft was created for this Circle meanwhile — no duplicate made.")
            for v in places:
                c.execute("""INSERT OR IGNORE INTO place_candidates (proposal_id, proposer_id, name, address, lat, lon, geo_source, url, cost_note,
                             accessibility_note, created_at, source_ref, validation) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (pid, v["name"][:120], v["address"][:300], v["lat"], v["lon"], "qloo" if v["lat"] is not None else "",
                           P._safe_url(v.get("website") or ""), v["validation"]["fields"]["price"],
                           v["validation"]["fields"].get("wheelchair_access", ""), now(), v["qloo_id"] or "", json.dumps(v["validation"])))
            members = [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active'", (cid,))]
            for u in members:
                _notify(c, u, f"draft:{pid}:{u}", "agent", f"New activity draft in {row['name']}",
                        f"{len(concepts)} options · {len(ts)} times" + (f" · {len(places)} places" if places else "") +
                        f". Vote within {int(config.AGENT_VOTE_HOURS)}h.", f"#/c/{cid}/events", outbox)
        d = _deliver(outbox)
        return {"result": pid, "message": f"Saved draft {pid} with {len(plan['concepts'])} option(s), {len(times)} time(s), {len(places)} verified place(s); "
                                          f"voting closes in {int(config.AGENT_VOTE_HOURS)}h. Notified {d['in_app']} member(s) in-app (email: {d['email']}).",
                "sources": [{"type": "database", "detail": "circle_events (agent draft), place_candidates, notifications"}]}
    pid = ctx.step("persist", "persist_draft_and_notify", persist)
    return {"proposal_id": pid}


# ================================================================ coordination
def tally(c, e) -> dict:
    plan = json.loads(e["plan"])
    times = json.loads(e["time_options"])
    sched = {x["time"]: x for x in (plan.get("agent") or {}).get("schedule", [])}
    av = {r["choice"]: r["n"] for r in c.execute("SELECT choice, COUNT(*) n FROM event_votes WHERE event_id = ? AND kind = 'activity' GROUP BY choice", (e["id"],))}
    tv = {r["choice"]: r["n"] for r in c.execute("SELECT choice, COUNT(*) n FROM event_votes WHERE event_id = ? AND kind = 'time' GROUP BY choice", (e["id"],))}
    option = min(range(len(plan["concepts"])), key=lambda i: (-av.get(i, 0), i))
    time_index = min(range(len(times)), key=lambda i: (-tv.get(i, 0), -(sched.get(times[i], {}).get("available", 0)), times[i])) if times else None
    pl_rows = c.execute("""SELECT pc.id, pc.name, pc.validation, COUNT(v.user_id) votes FROM place_candidates pc
                           LEFT JOIN place_votes v ON v.place_id = pc.id WHERE pc.proposal_id = ? GROUP BY pc.id""", (e["id"],)).fetchall()
    ok = [r for r in pl_rows if not r["validation"] or json.loads(r["validation"]).get("status") == "verified"]
    place = min(ok, key=lambda r: (-r["votes"], r["id"])) if ok else None
    return {"option": option, "time_index": time_index, "place_id": place["id"] if place else None,
            "place_name": place["name"] if place else None,
            "votes": {"activity": av, "time": tv, "place": {r["id"]: r["votes"] for r in pl_rows}},
            "rule": "Most votes wins. Ties: activity -> planner's order; time -> more members with stated availability, then earlier; "
                    "place -> verified places only, then the earlier suggestion. Computed by the application.",
            "decided_at": now()}


@jobs.handler("coordinate_proposal")
def run_coordinate(ctx: jobs.Ctx) -> dict:
    pid = ctx.run["subject_id"]

    def do_tally():
        with db.tx() as c:
            e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
            if not e or e["status"] != "proposed":
                raise jobs.Skip("Proposal is no longer open.")
            sel = json.loads(e["selection"]) if e["selection"] else tally(c, e)
            c.execute("UPDATE circle_events SET selection = ? WHERE id = ?", (json.dumps(sel), pid))
        return {"result": sel, "message": f"Voting closed ({ctx.run['trigger']}). Selected option {sel['option'] + 1}"
                + (f", time {sel['time_index'] + 1}" if sel["time_index"] is not None else "")
                + (f", place “{sel['place_name']}”" if sel["place_name"] else ", place unresolved") + ". " + sel["rule"],
                "sources": [{"type": "database", "detail": "event_votes, place_votes"}, {"type": "app", "detail": "transparent tally rule"}],
                "data": {"votes": sel["votes"]}}
    sel = ctx.step("tally", "tally_votes", do_tally)

    def decide():
        outbox = []
        with db.tx() as c:
            e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
            row = c.execute("SELECT * FROM circles WHERE id = ?", (e["circle_id"],)).fetchone()
            if e["status"] != "proposed":
                raise jobs.Skip("Proposal is no longer open.")
            plan = json.loads(e["plan"])
            times = json.loads(e["time_options"])
            cons = json.loads(e["constraints"])
            _, profs = circles._group_for_planner(c, row["id"], row)
            fails = []
            if sel["time_index"] is None:
                fails.append("no time option")
            else:
                if circles._parse_time(times[sel["time_index"]]).replace(tzinfo=None) < datetime.now():
                    fails.append("chosen time has passed")
                chk = circles._checks(plan["concepts"][sel["option"]], cons, row, profs, [times[sel["time_index"]]], e["capacity"], confirm=True)
                fails += [k["check"] for k in chk if k["status"] == "fail"]
            if row["approval_policy"] == "auto" and not fails and row["host_id"]:
                place = c.execute("SELECT * FROM place_candidates WHERE id = ?", (sel["place_id"],)).fetchone() if sel["place_id"] else None
                real = P.event_from_proposal(c, row["host_id"], e, plan["concepts"][sel["option"]], times[sel["time_index"]],
                                             cons.get("timezone") or "UTC", place, e["capacity"], row, location_confirmed=False,
                                             note="Auto-published by the planning agent under this Circle's auto-approval policy. "
                                                  "The voted venue is a suggestion: nothing is booked.")
                c.execute("""UPDATE circle_events SET status = 'confirmed', chosen_option = ?, chosen_time = ?, confirmed_at = ?, event_id = ?
                             WHERE id = ?""", (sel["option"], times[sel["time_index"]], now(), real, pid))
                result, msg = {"published": real}, f"Published event {real} (Circle policy: auto). Venue left 'to be confirmed' — not booked."
            else:
                mods = [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active' AND role IN ('host','moderator')",
                                                 (row["id"],))]
                for u in mods:
                    _notify(c, u, f"approve:{pid}:{u}", "agent", f"Activity ready for your approval: {e['title']}",
                            "Voting closed. Review the selected option and approve or reject." + (f" Blocked: {', '.join(fails)}." if fails else ""),
                            "#/agent", outbox)
                result = {"awaiting_approval": True, "blocked_by": fails}
                msg = ("Hard constraints failed: " + ", ".join(fails) + ". " if fails else "") + \
                      f"Asked {len(mods)} host/moderator(s) to approve (Circle policy: {row['approval_policy']})."
        d = _deliver(outbox)
        if result.get("published"):
            on_event_changed(result["published"], "a new event matching your interests was published")
        return {"result": result, "message": msg + f" Notifications: {d['in_app']} in-app.", "status": "warn" if result.get("blocked_by") else "ok",
                "sources": [{"type": "database", "detail": "circle settings (approval policy), constraint checks"}]}
    return ctx.step("decide", "publish_or_request_approval", decide)


def _event_start_end(e):
    return P._abs(e)


@jobs.handler("event_followup")
def run_followup(ctx: jobs.Ctx) -> dict:
    eid, phase = ctx.run["subject_id"], ctx.input["phase"]

    def act():
        outbox = []
        with db.tx() as c:
            e = c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
            if not e or e["status"] != "published":
                raise jobs.Skip("Event is no longer published.")
            link = f"#/e/{eid}"
            if phase == "remind24":
                users = P._rsvp_users(c, eid)
                for u in users:
                    _notify(c, u, f"remind24:{eid}:{u}", "event_reminder", f"Reminder: {e['title']} is coming up",
                            f"Starts {e['starts_at'].replace('T', ' ')} ({e['timezone']}).", link, outbox)
                msg = f"Sent the 24-hour reminder to {len(outbox)} person(s) who are going or maybe."
            elif phase == "rsvp_nudge":
                responded = {r[0] for r in c.execute("SELECT user_id FROM event_rsvps WHERE event_id = ?", (eid,))}
                members = [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active'", (e["circle_id"],))]
                for u in [m for m in members if m not in responded]:
                    _notify(c, u, f"rsvp-nudge:{eid}:{u}", "event_reminder", f"Will you join {e['title']}?",
                            "Not enough people have replied yet — please RSVP so the host can plan.", link, outbox)
                msg = f"Too few RSVPs: nudged {len(outbox)} member(s) who haven't replied."
            elif phase == "complete":
                if not P._is_past(e):
                    raise jobs.Skip("Event hasn't ended yet.")
                c.execute("UPDATE events SET status = 'completed', updated_at = ? WHERE id = ? AND status = 'published'", (now(), eid))
                c.execute("INSERT INTO event_updates (event_id, author_id, kind, message, created_at) VALUES (?, NULL, 'completed', ?, ?)",
                          (eid, "Marked completed automatically after its end time (coordination agent)", now()))
                for u in P._rsvp_users(c, eid, ("going",)):
                    _notify(c, u, f"feedback:{eid}:{u}", "feedback", f"How was {e['title']}?",
                            "Optional: rate it — your feedback shapes the next activity the agent plans.", link, outbox)
                msg = f"Event completed; asked {len(outbox)} attendee(s) for optional feedback."
            else:
                raise jobs.Skip(f"Unknown phase {phase}")
        d = _deliver(outbox)
        if phase == "complete":
            on_event_changed(eid, "an event you were recommended has finished")
        return {"result": {"notified": d["in_app"]}, "message": msg + f" Email: {d['email']}.",
                "sources": [{"type": "database", "detail": "events, event_rsvps, notifications"}]}
    return ctx.step(phase, "event_" + phase, act)


def sweep() -> dict:
    """Deterministic, cheap scan run by the worker every AGENT_SWEEP_SECONDS. Creates runs only when there is work;
    once_key guarantees each reminder / tally / completion happens at most once."""
    made = {"tally": 0, "remind24": 0, "rsvp_nudge": 0, "complete": 0, "vote_nudge": 0}
    t = now()
    with db.read() as c:
        drafts = c.execute("SELECT * FROM circle_events WHERE source = 'agent' AND status = 'proposed' AND selection IS NULL").fetchall()
        evs = c.execute("""SELECT e.*, ci.min_size FROM events e JOIN circles ci ON ci.id = e.circle_id
                           WHERE e.owner_kind = 'circle' AND e.status = 'published'""").fetchall()
        going = {r["event_id"]: r["n"] for r in c.execute("SELECT event_id, COUNT(*) n FROM event_rsvps WHERE status = 'going' GROUP BY event_id")}
    for d in drafts:
        if d["vote_deadline"] and d["vote_deadline"] <= t:
            if jobs.enqueue("coordinate_proposal", subject_type="proposal", subject_id=d["id"], circle_id=d["circle_id"],
                            trigger="voting deadline reached", once_key=f"tally:{d['id']}"):
                made["tally"] += 1
        elif d["vote_deadline"] and d["vote_deadline"] - t <= config.AGENT_VOTE_HOURS * 1800:
            if jobs.enqueue("event_followup_votes", subject_type="proposal", subject_id=d["id"], circle_id=d["circle_id"],
                            trigger="half of the voting window passed", once_key=f"vote-nudge:{d['id']}"):
                made["vote_nudge"] += 1
    for e in evs:
        try:
            start, end = _event_start_end(e)
        except HTTPException:
            continue
        left = (start - datetime.now(start.tzinfo)).total_seconds()
        if end < datetime.now(end.tzinfo):
            phase = "complete"
        elif 0 < left <= 24 * 3600:
            phase = "remind24"
        elif 0 < left <= 72 * 3600 and going.get(e["id"], 0) < e["min_size"]:
            phase = "rsvp_nudge"
        else:
            continue
        if jobs.enqueue("event_followup", subject_type="event", subject_id=e["id"], circle_id=e["circle_id"], trigger=phase.replace("_", " "),
                        payload={"phase": phase}, once_key=f"{phase}:{e['id']}"):
            made[phase] += 1
    return made


@jobs.handler("event_followup_votes")
def run_vote_nudge(ctx: jobs.Ctx) -> dict:
    pid = ctx.run["subject_id"]

    def act():
        outbox = []
        with db.tx() as c:
            e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
            if not e or e["status"] != "proposed" or e["selection"]:
                raise jobs.Skip("Voting already closed.")
            voted = {r[0] for r in c.execute("SELECT DISTINCT user_id FROM event_votes WHERE event_id = ?", (pid,))}
            for u in [r[0] for r in c.execute("SELECT user_id FROM memberships WHERE circle_id = ? AND status = 'active'", (e["circle_id"],))]:
                if u not in voted:
                    _notify(c, u, f"vote-nudge:{pid}:{u}", "agent", f"Vote on: {e['title']}",
                            "Half of the voting window has passed — pick an option and a time.", f"#/c/{e['circle_id']}/events", outbox)
        d = _deliver(outbox)
        return {"result": d["in_app"], "message": f"Reminded {d['in_app']} member(s) who haven't voted yet.",
                "sources": [{"type": "database", "detail": "event_votes, notifications"}]}
    return ctx.step("vote_nudge", "remind_non_voters", act)


# ================================================================ Activity Centre read models + permissions
def _my_circles(c, uid) -> list[str]:
    return [r[0] for r in c.execute("SELECT circle_id FROM memberships WHERE user_id = ? AND status = 'active'", (uid,))]


def _is_circle_mod(c, cid, uid) -> bool:
    return bool(c.execute("SELECT 1 FROM memberships WHERE circle_id = ? AND user_id = ? AND status = 'active' AND role IN ('host','moderator')",
                          (cid, uid)).fetchone())


def _run_view(c, r, steps=True) -> dict:
    d = {k: r[k] for k in ("id", "kind", "subject_type", "subject_id", "circle_id", "trigger", "status", "attempts", "max_attempts",
                           "error", "created_at", "started_at", "finished_at", "updated_at", "next_run_at")}
    d["output"] = json.loads(r["output"] or "{}")
    if r["circle_id"]:
        ci = c.execute("SELECT name FROM circles WHERE id = ?", (r["circle_id"],)).fetchone()
        d["circle_name"] = ci["name"] if ci else None
    if steps:
        d["steps"] = [{"name": s["name"], "tool": s["tool"], "status": s["status"], "message": s["message"], "attempt": s["attempt"],
                       "sources": json.loads(s["sources"] or "[]"), "data": json.loads(s["data"] or "{}"),
                       "started_at": s["started_at"], "finished_at": s["finished_at"]}
                      for s in c.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY id", (r["id"],))]
    return d


def can_view_run(c, r, uid) -> bool:
    return r["user_id"] == uid or (r["circle_id"] is not None and r["circle_id"] in _my_circles(c, uid))


def can_control_run(c, r, uid) -> bool:
    return r["user_id"] == uid or (r["circle_id"] is not None and r["user_id"] is None and _is_circle_mod(c, r["circle_id"], uid))


def list_runs(uid: str, limit: int = 30) -> list[dict]:
    with db.read() as c:
        mine = _my_circles(c, uid)
        q = "SELECT * FROM agent_runs WHERE user_id = ?" + (f" OR circle_id IN ({','.join('?' * len(mine))})" if mine else "") + \
            " ORDER BY created_at DESC LIMIT ?"
        rows = c.execute(q, (uid, *mine, min(limit, 100))).fetchall()
        return [dict(_run_view(c, r), can_control=can_control_run(c, r, uid)) for r in rows]


def run_detail(uid: str, rid: str) -> dict:
    with db.read() as c:
        r = c.execute("SELECT * FROM agent_runs WHERE id = ?", (rid,)).fetchone()
        if not r or not can_view_run(c, r, uid):
            raise HTTPException(404, "Run not found.")
        return dict(_run_view(c, r), can_control=can_control_run(c, r, uid))


def control_run(uid: str, rid: str, action: str) -> dict:
    with db.read() as c:
        r = c.execute("SELECT * FROM agent_runs WHERE id = ?", (rid,)).fetchone()
        if not r or not can_view_run(c, r, uid):
            raise HTTPException(404, "Run not found.")
        if not can_control_run(c, r, uid):
            raise HTTPException(403, "Only the person this run acts for (or a Circle host) can control it.")
    try:
        jobs.control(rid, action)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return run_detail(uid, rid)


def discovery(uid: str) -> dict | None:
    with db.read() as c:
        r = c.execute("SELECT * FROM user_discovery WHERE user_id = ?", (uid,)).fetchone()
    return json.loads(r["payload"]) if r else None


def approvals(uid: str) -> list[dict]:
    """Agent drafts in Circles I moderate: voting still open, or tallied and waiting for approval."""
    out = []
    with db.read() as c:
        for cid in _my_circles(c, uid):
            for e in c.execute("SELECT * FROM circle_events WHERE circle_id = ? AND source = 'agent' AND status = 'proposed'", (cid,)).fetchall():
                plan = json.loads(e["plan"])
                sel = json.loads(e["selection"]) if e["selection"] else None
                row = c.execute("SELECT name, approval_policy FROM circles WHERE id = ?", (cid,)).fetchone()
                times = json.loads(e["time_options"])
                place = c.execute("SELECT name, address, validation FROM place_candidates WHERE id = ?", (sel["place_id"],)).fetchone() \
                    if sel and sel.get("place_id") else None
                out.append({"id": e["id"], "circle_id": cid, "circle_name": row["name"], "title": e["title"],
                            "stage": "awaiting_approval" if sel else "voting", "vote_deadline": e["vote_deadline"],
                            "can_approve": bool(sel) and _is_circle_mod(c, cid, uid), "policy": row["approval_policy"],
                            "options": [{"title": k["title"], "format": k.get("format_name"), "generated_by": k.get("generated_by")} for k in plan["concepts"]],
                            "times": times, "selection": sel,
                            "selected": {"option": plan["concepts"][sel["option"]]["title"] if sel else None,
                                         "time": times[sel["time_index"]] if sel and sel["time_index"] is not None else None,
                                         "place": {"name": place["name"], "address": place["address"],
                                                   "validation": json.loads(place["validation"]) if place["validation"] else None} if place else None, "timezone": json.loads(e["constraints"]).get("timezone", "UTC")}})
    return out


def approve(uid: str, pid: str, timezone: str | None = None) -> dict:
    with db.read() as c:
        e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
    if not e or e["source"] != "agent" or not e["selection"]:
        raise HTTPException(409, "This draft hasn't finished voting yet.")
    sel = json.loads(e["selection"])
    tz = timezone or json.loads(e["constraints"]).get("timezone") or "UTC"
    return circles.confirm_event(uid, pid, sel["option"], sel["time_index"], None, sel.get("place_id"), tz)


def approve_now(uid: str, pid: str, timezone: str | None = None) -> dict:
    """Planning board: a host moves a proposal to 'Approved'. Votes so far are tallied with the same transparent rule,
    then the normal confirm path runs every hard check (permissions, time in future, capacity, budget...)."""
    with db.tx() as c:
        e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
        if not e or not _is_circle_mod(c, e["circle_id"], uid):
            raise HTTPException(403, "Only a host or moderator can approve an activity.")
        if e["status"] != "proposed":
            raise HTTPException(409, f"This activity is already {e['status']}.")
        if not json.loads(e["time_options"]):
            raise HTTPException(409, "Add at least one time option before approving.")
        sel = json.loads(e["selection"]) if e["selection"] else tally(c, e)
        c.execute("UPDATE circle_events SET selection = ? WHERE id = ?", (json.dumps(sel), pid))
    tz = timezone or json.loads(e["constraints"]).get("timezone") or "UTC"
    out = circles.confirm_event(uid, pid, sel["option"], sel["time_index"], None, sel.get("place_id"), tz)
    if out.get("event_id"):
        on_event_changed(out["event_id"], "a new event matching your interests was published")
    return out


def reject(uid: str, pid: str) -> dict:
    with db.read() as c:
        e = c.execute("SELECT * FROM circle_events WHERE id = ?", (pid,)).fetchone()
        if not e or e["source"] != "agent" or not _is_circle_mod(c, e["circle_id"], uid):
            raise HTTPException(403, "Only a host or moderator can reject an agent draft.")
    return circles.cancel_event(uid, pid)


def circle_settings(uid: str, cid: str, data: dict) -> dict:
    with db.tx() as c:
        row = c.execute("SELECT * FROM circles WHERE id = ?", (cid,)).fetchone()
        m = c.execute("SELECT role FROM memberships WHERE circle_id = ? AND user_id = ? AND status = 'active'", (cid, uid)).fetchone()
        if not row or not m or m["role"] != "host":
            raise HTTPException(403, "Only the Circle host can change automation settings.")
        auto_plan = int(data["auto_plan"]) if data.get("auto_plan") is not None else row["auto_plan"]
        policy = data.get("approval_policy") or row["approval_policy"]
        if policy not in ("host", "auto"):
            raise HTTPException(422, "approval_policy must be 'host' or 'auto'.")
        c.execute("UPDATE circles SET auto_plan = ?, approval_policy = ? WHERE id = ?", (auto_plan, policy, cid))
    return {"auto_plan": bool(auto_plan), "approval_policy": policy}


def summary(uid: str) -> dict:
    with db.read() as c:
        s = get_settings(c, uid)
        running = c.execute("SELECT COUNT(*) FROM agent_runs WHERE user_id = ? AND status IN ('queued','running')", (uid,)).fetchone()[0]
        last = c.execute("SELECT status, finished_at, created_at FROM agent_runs WHERE user_id = ? AND kind = 'discovery' ORDER BY created_at DESC LIMIT 1",
                         (uid,)).fetchone()
        mods = [cid for cid in _my_circles(c, uid) if _is_circle_mod(c, cid, uid)]
        circ = []
        for cid in mods:
            r = c.execute("SELECT id, name, auto_plan, approval_policy, host_id FROM circles WHERE id = ?", (cid,)).fetchone()
            circ.append({"id": r["id"], "name": r["name"], "auto_plan": bool(r["auto_plan"]), "approval_policy": r["approval_policy"],
                         "is_host": r["host_id"] == uid})
    inv = my_invites(uid)
    appr = approvals(uid)
    return {"settings": s, "running": running, "last_discovery": dict(last) if last else None,
            "invites_pending": sum(1 for i in inv if i["my_status"] == "invited" and i["status"] in ("open", "formed")),
            "approvals_pending": sum(1 for a in appr if a["can_approve"]), "voting": sum(1 for a in appr if a["stage"] == "voting"),
            "moderated_circles": circ, "match_rules": MATCH_RULES}
