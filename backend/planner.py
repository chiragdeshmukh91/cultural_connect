"""Bounded agentic planner: discover -> bridge -> draft -> review -> (auto-fix) -> organizer feedback -> revise.

Tools are plain functions; the agent can only call them in a fixed loop with a step limit, so it can
never invent Qloo calls. Every claim in a plan cites an evidence id (E1, E2...) that maps to either a
participant-provided input or a real Qloo response item. Uncited / unknown ids are stripped.
"""
from __future__ import annotations

import copy
import json
import time
import uuid

from . import config, llm
from .qloo_client import QlooError
from .qloo_service import group_anchors, pretty_type

FORMATS = {
    "skill_swap": dict(name="Skill-Swap Session", title="{theme} Skill-Swap", cost_pp=1.0, fixed=5,
                       settings={"indoor", "outdoor", "online"},
                       materials=["Practice kits/equipment for {theme} (borrowed or shared)", "Name tags", "Simple feedback cards"],
                       segments=[("Welcome & name game", .12, "Everyone shares why {theme} matters to them."),
                                 ("Mentor demo", .2, "{mentors} demonstrate the basics and one favourite trick."),
                                 ("Paired practice", .4, "Mentor–learner pairs practise; others rotate between pairs."),
                                 ("Show & tell", .15, "Learners show one thing they picked up."),
                                 ("Next meet-up & wrap", .13, "Agree (opt-in) on a follow-up session.")]),
    "interest_circle": dict(name="Interest Circle", title="{theme} Circle", cost_pp=1.5, fixed=5,
                            settings={"indoor", "outdoor", "online"},
                            materials=["Prompt cards about {theme}", "Snacks/water", "Name tags"],
                            segments=[("Icebreaker", .15, "Two truths and a wish about {theme}."),
                                      ("Shared activity", .45, "Hands-on or discussion activity built around {theme}."),
                                      ("Cross-generational swap", .25, "Each person shares how they first discovered it."),
                                      ("Wrap & opt-in contacts", .15, "Swap contacts only if both people agree.")]),
    "dialogue_circle": dict(name="Respectful Dialogue Circle", title="Conversations on {theme}", cost_pp=1.0, fixed=0,
                            settings={"indoor", "online"},
                            materials=["Ground-rules poster (listen, no personal attacks)", "Talking piece", "Timer"],
                            segments=[("Ground rules", .12, "Facilitator sets listening-first norms."),
                                      ("Personal stories", .3, "Each person shares a lived experience related to {theme}."),
                                      ("Facilitated dialogue", .38, "Explore agreements, differences and open questions."),
                                      ("Common ground", .2, "Group notes 2–3 shared values or next actions.")]),
    "action_sprint": dict(name="Community Action Sprint", title="{theme} Action Sprint", cost_pp=2.0, fixed=10,
                          settings={"indoor", "outdoor", "online"},
                          materials=["Chart paper & markers", "Laptop for research (optional)", "Sign-up sheet"],
                          segments=[("Why we care", .15, "Members share what draws them to {theme}."),
                                    ("Learn", .25, "Quick primer from the most experienced member or a guest."),
                                    ("Build", .4, "Make one tangible output: a poster, plan, letter or guide."),
                                    ("Commit", .2, "Pick one small opt-in action for the next two weeks.")]),
    "story_circle": dict(name="Book & Story Circle", title="Story Circle: {anchor}", cost_pp=1.0, fixed=0,
                         settings={"indoor", "outdoor", "online"},
                         materials=["Library copy / excerpt of {anchor}", "Large-print excerpts", "Sticky notes"],
                         segments=[("Welcome", .12, "Share a favourite story from your own life."),
                                   ("Read-aloud", .28, "Take turns reading an excerpt of {anchor}."),
                                   ("Discussion", .4, "Connect the story to each member's own interests."),
                                   ("Create & share", .2, "Write or draw a one-page response.")]),
    "screening": dict(name="Screening & Conversation", title="Watch & Talk: {anchor}", cost_pp=1.5, fixed=0,
                      settings={"indoor", "online"},
                      materials=["Projector/TV or shared stream of {anchor} (check licence)", "Subtitles on", "Snacks"],
                      segments=[("Intro", .1, "Why Qloo surfaced {anchor} for this group."),
                                ("Watch (clips or full)", .5, "Screen {anchor} or selected scenes."),
                                ("Conversation", .3, "What did each generation notice differently?"),
                                ("Wrap", .1, "Pick the next title together.")]),
    "listening_lounge": dict(name="Listening Lounge", title="Listening Lounge: {anchor}", cost_pp=0.5, fixed=0,
                             settings={"indoor", "outdoor", "online"},
                             materials=["Speaker + playlist/episode of {anchor}", "Lyric/transcript printouts"],
                             segments=[("Welcome", .12, "Everyone names a sound that reminds them of home."),
                                       ("Listen together", .38, "Play {anchor}."),
                                       ("Respond", .35, "Discuss, hum, play along or sketch what you heard."),
                                       ("Swap picks", .15, "Each member adds one track/episode to a shared list.")]),
    "play_session": dict(name="Play Session", title="Play Together: {anchor}", cost_pp=1.0, fixed=0,
                         settings={"indoor", "online"},
                         materials=["Console/PC or board-game version of {anchor}", "Accessible controllers"],
                         segments=[("Warm-up", .15, "Quick rules/controls walkthrough."),
                                   ("Mixed-team play", .55, "Teams mix ages and experience levels."),
                                   ("Debrief", .3, "What strategies did each person bring?")]),
    "venue_meetup": dict(name="Venue Meet-up", title="Meet at {venue}", cost_pp=4.0, fixed=0,
                         settings={"indoor", "outdoor"},
                         materials=["Venue booking confirmation (organizer)", "Meeting-point sign"],
                         segments=[("Meet & greet", .2, "Gather at {venue}; buddy pairs formed."),
                                   ("Shared experience", .55, "Explore/enjoy {venue} together around {theme}."),
                                   ("Reflection", .25, "Short circle: what connected you today?")]),
    "creative_jam": dict(name="Creative Jam", title="{theme} Creative Jam", cost_pp=2.5, fixed=5,
                         settings={"indoor", "outdoor", "online"},
                         materials=["Paper, colours, craft supplies", "Phone/tablet for digital makers (optional)"],
                         segments=[("Spark", .15, "Everyone brings one image/idea linked to {theme}."),
                                   ("Make", .5, "Small mixed groups co-create a piece."),
                                   ("Gallery walk", .25, "Each piece is presented by its makers."),
                                   ("Wrap", .1, "Opt-in photo consent and next steps.")]),
}
ANCHOR_FORMAT = {"urn:entity:book": "story_circle", "urn:entity:movie": "screening", "urn:entity:tv_show": "screening",
                 "urn:entity:podcast": "listening_lounge", "urn:entity:artist": "listening_lounge",
                 "urn:entity:videogame": "play_session", "urn:entity:place": "venue_meetup"}
ISSUE_AUDIENCES = ("global_issues", "political", "lifestyle_preferences_beliefs", "communities")

DEFAULT_CONSTRAINTS = {"duration_min": 90, "budget": 50, "currency": "USD", "setting": "any", "wheelchair": False,
                       "quiet_space": False, "visual_aids": False, "flexible_participation": True,
                       "sensitive_topic": False, "goals": ["connect"], "language": ""}


# ---------------------------------------------------------------- evidence pack
def evidence_pack(group: dict, anchors: dict | None, use_qloo: bool = True) -> list[dict]:
    pack, seen = [], set()

    def add(source, kind, label, detail, qloo_id=None, extra=None):
        key = (kind, label, qloo_id)
        if key in seen or not label:
            return
        seen.add(key)
        pack.append({"eid": f"E{len(pack) + 1}", "source": source, "kind": kind, "label": label,
                     "detail": detail, "qloo_id": qloo_id, **(extra or {})})

    for e in group.get("evidence", []):
        if not use_qloo and e["source"] == "qloo":
            continue
        src = "participant" if e["source"].startswith("participant") else "qloo"
        add(src, e["kind"], e["label"], e["detail"], e.get("ref"), {"between": e.get("between"), "ref_type": e.get("ref_type")})
    if use_qloo and anchors:
        for a in anchors.get("anchors", []):
            who = ", ".join(a.get("driven_by") or []) or "the group's combined signals"
            add("qloo", "anchor", a["name"], f"Qloo Insights ({pretty_type(a['type'])}) recommended this for {who}.",
                a["id"], {"type": a["type"], "driven_by": a.get("driven_by"), "image": a.get("image"),
                          "affinity": a.get("affinity")})
        for v in anchors.get("venues", []):
            add("qloo", "venue", v["name"], f"Qloo place result near the chosen area{(' — ' + v['address']) if v.get('address') else ''}.",
                v["id"], {"type": v["type"], "address": v.get("address")})
    return pack


# ---------------------------------------------------------------- rule-based generator
def _scale(segments, duration, ctx):
    out, total = [], 0
    for title, frac, detail in segments:
        m = max(5, int(round(duration * frac / 5.0)) * 5)
        out.append({"title": title, "minutes": m, "detail": detail.format(**ctx)})
        total += m
    out[-1]["minutes"] += duration - total
    if out[-1]["minutes"] < 5:
        out[-1]["minutes"] = 5
    return out


def _theme_mentorships(group, theme):
    return [e for e in group.get("mentorships", []) if e["label"] and e["label"].lower() in (theme or "").lower()]


def _roles(group, theme, fmt, pack_refs, anchor=None):
    roles = []
    ms = _theme_mentorships(group, theme)
    teaches = {}
    learns = {}
    for e in ms:
        teaches.setdefault(e.get("teacher"), []).append(e["label"])
        learns.setdefault(e.get("learner"), []).append(e["label"])
    for m in group["members"]:
        labels = [i["label"] for i in m["interests"]]
        if m["name"] in teaches:
            r = f"Mentor — leads the {' & '.join(dict.fromkeys(teaches[m['name']]))} demo"
            if m["name"] in learns:
                r += f", then learns {' & '.join(dict.fromkeys(learns[m['name']]))}"
        elif m["name"] in learns:
            r = f"Learner — practises {' & '.join(dict.fromkeys(learns[m['name']]))} with a mentor"
        elif fmt == "skill_swap":
            r = f"Rotating partner — joins a practice pair and offers a taster of {labels[0] if labels else 'their own skill'}"
        elif any(i["label"].lower() in (theme or "").lower() or (theme or "").lower() in i["label"].lower() for i in m["interests"]):
            r = f"Co-host — shares their own experience of {theme}"
        elif anchor and m["name"] in (anchor.get("driven_by") or []):
            r = f"Context-giver — Qloo linked their interest in {labels[0] if labels else 'their picks'} to {anchor['label']}"
        else:
            r = f"Contributor — brings their love of {labels[0] if labels else 'the theme'}"
        roles.append({"member": m["name"], "role": r})
    return roles


def _checklist(c, group):
    items = ["Opt-out alternative for every activity", "Photo/recording only with explicit consent",
             "Contact details shared only when both people opt in"]
    if c.get("wheelchair"):
        items.append("Step-free / wheelchair-accessible venue (organizer to confirm)")
    if c.get("quiet_space"):
        items.append("Quiet break space available")
    if c.get("visual_aids"):
        items.append("Large-print & visual aids prepared")
    if c.get("flexible_participation"):
        items.append("Flexible participation: listening, drawing or voting count as taking part")
    if c.get("language"):
        items.append(f"Session language / interpretation: {c['language']}")
    return items


def _safeguards(c, group):
    out = []
    if any(m.get("age_band") == "under_18" for m in group["members"]):
        out.append("Minors present: run through an authorized organization, guardian consent, two-adult rule, no private 1:1 contact.")
    if c.get("sensitive_topic"):
        out.append("Sensitive topic: trained facilitator; information shared is not medical/legal advice; signpost to professionals.")
    if any(e.get("ref_type", "") and any(k in (e.get("ref_type") or "") for k in ISSUE_AUDIENCES) for e in group.get("evidence", [])):
        out.append("Values-based topic: agree respectful-dialogue ground rules up front.")
    return out


def _cost(fmt, n, budget):
    f = FORMATS[fmt]
    est = round(f["fixed"] + f["cost_pp"] * n, 2)
    note = "Estimate from format defaults (organizer to verify)."
    if est > budget:
        note = f"Low-cost variant: reuse/borrow materials to stay within {budget}."
        est = float(budget)
    return {"amount": est, "notes": note}


def _candidates(group, pack, c, excluded):
    cands = []
    setting = c.get("setting", "any")
    goals = set(c.get("goals") or [])

    def ok(fmt):
        return setting == "any" or setting in FORMATS[fmt]["settings"]

    ment = [p for p in pack if p["kind"] == "mentorship"]
    if ment:
        labels = list(dict.fromkeys(p["label"] for p in ment))[:2]
        cands.append(("skill_swap", " & ".join(labels), None, [p["eid"] for p in ment][:4]))
    direct = [p for p in pack if p["kind"] in ("same_signal", "same_label", "crossover")]
    taste = [p for p in pack if p["kind"] in ("qloo_taste", "qloo_recs")]
    for p in (direct + taste)[:3]:
        rt = p.get("ref_type") or ""
        if any(k in rt for k in ISSUE_AUDIENCES):
            fmt = "action_sprint" if goals & {"act", "support"} else "dialogue_circle"
        elif "create" in goals:
            fmt = "creative_jam"
        else:
            fmt = "interest_circle"
        label = p["label"].split(",")[0].strip()
        cands.append((fmt, label, None, [p["eid"]] + [t["eid"] for t in taste[:1] if t is not p]))
    anchors = sorted([p for p in pack if p["kind"] == "anchor"], key=lambda p: -len(p.get("driven_by") or []))
    for p in anchors[:4]:
        fmt = ANCHOR_FORMAT.get(p.get("type"), "interest_circle")
        theme = group.get("primary_theme") or p["label"]
        cands.append((fmt, theme, p, [p["eid"]] + [d["eid"] for d in direct[:1]]))
    venues = [p for p in pack if p["kind"] == "venue"]
    if venues and setting != "online":
        theme = group.get("primary_theme") or venues[0]["label"]
        cands.append(("venue_meetup", theme, venues[0], [venues[0]["eid"]] + [d["eid"] for d in direct[:1]]))
    if not cands and group.get("primary_theme"):
        cands.append(("interest_circle", group["primary_theme"], None, []))
    return [x for x in cands if ok(x[0]) and x[1] not in excluded.get("themes", [])
            and x[0] not in excluded.get("formats", []) and (not x[2] or x[2]["label"] not in excluded.get("themes", []))]


def rule_generate(group, pack, c, excluded, n=2):
    cands = _candidates(group, pack, c, excluded)
    scored = []
    by_eid = {p["eid"]: p for p in pack}
    for fmt, theme, anchor, refs in cands:
        q = sum(1.5 if by_eid[r]["source"] == "qloo" else 1 for r in refs if r in by_eid)
        cover = len(anchor.get("driven_by") or []) / max(1, len(group["members"])) if anchor else 0.5
        goal_bonus = 0.5 if (fmt in ("skill_swap", "action_sprint") and set(c.get("goals") or []) & {"learn", "act", "support"}) else 0
        if fmt == "skill_swap":
            goal_bonus += 2.0  # a teach<->learn match is the strongest, most actionable bridge
        scored.append((round(q + cover + goal_bonus, 2), fmt, theme, anchor, refs))
    scored.sort(key=lambda x: -x[0])
    chosen, used = [], set()
    for s in scored:
        if s[1] in used:
            continue
        chosen.append(s)
        used.add(s[1])
        if len(chosen) == n:
            break
    return [_build_concept(group, pack, c, fmt, theme, anchor, refs, score) for score, fmt, theme, anchor, refs in chosen]


def _build_concept(group, pack, c, fmt, theme, anchor, refs, score=None, generated_by="rule-based planner"):
    f = FORMATS[fmt]
    mentors = ", ".join(dict.fromkeys(e.get("teacher") for e in _theme_mentorships(group, theme) if e.get("teacher"))) or "Experienced members"
    ctx = {"theme": theme, "anchor": anchor["label"] if anchor else theme, "venue": anchor["label"] if anchor else "a local venue",
           "mentors": mentors}
    n = len(group["members"])
    return {
        "id": "C" + uuid.uuid4().hex[:6], "format": fmt, "format_name": f["name"], "title": f["title"].format(**ctx),
        "theme": theme, "anchor": anchor["label"] if anchor else None, "anchor_image": anchor.get("image") if anchor else None,
        "summary": f"{'An' if f['name'][0] in 'AEIOU' else 'A'} {f['name'].lower()} for {n} people connected through {theme}"
                   + (f", anchored on Qloo's pick “{anchor['label']}”." if anchor and fmt != "venue_meetup" else "."),
        "duration_min": c["duration_min"], "group_size": n,
        "agenda": _scale(f["segments"], int(c["duration_min"]), ctx),
        "materials": [m.format(**ctx) for m in f["materials"]],
        "roles": _roles(group, theme, fmt, refs, anchor),
        "cost_estimate": _cost(fmt, n, float(c.get("budget", 0) or 0)),
        "venue": (anchor["label"] + (f" — {anchor.get('address')}" if anchor.get("address") else "")) if fmt == "venue_meetup" and anchor
        else ("Online call (organizer link)" if c.get("setting") == "online" else "Organizer-chosen community space"),
        "accessibility": _checklist(c, group), "safeguards": _safeguards(c, group),
        "evidence_refs": refs, "rank_score": score, "generated_by": generated_by, "setting": c.get("setting", "any"),
    }


# ---------------------------------------------------------------- LLM generator
SYSTEM = """You are the planning agent of Culture Connect, an app that helps people who don't know each other
connect as a small group around shared interests, using Qloo cultural-intelligence evidence.
Rules: use ONLY the provided evidence; cite evidence ids (E1..) in evidence_refs for every concept; never invent
Qloo results, statistics or relationships; respect constraints exactly (agenda minutes must sum to duration_min,
cost within budget); do not infer health, loneliness, personality or other sensitive traits; include an opt-out.
Return JSON: {"concepts":[{"title","summary","format","theme","anchor","agenda":[{"title","minutes","detail"}],
"materials":[],"roles":[{"member","role"}],"cost_estimate":{"amount","notes"},"venue","accessibility":[],
"safeguards":[],"evidence_refs":[]}]}"""


def llm_generate(group, pack, c, excluded, feedback=None, previous=None, use_qloo=True):
    members = [{"name": m["name"], "age_band": m.get("age_band"), "interests": m["interests"]} for m in group["members"]]
    scaffold = rule_generate(group, pack, c, excluded) if pack else []
    user = json.dumps({
        "task": "Draft 2 distinct, practical group activity concepts." if not feedback else "Revise the plan using the organizer feedback.",
        "members": members, "constraints": c, "excluded": excluded,
        "evidence": [{k: p[k] for k in ("eid", "source", "kind", "label", "detail")} for p in pack],
        "format_library": {k: v["name"] for k, v in FORMATS.items()},
        "rule_based_drafts": [{k: s[k] for k in ("title", "format", "theme", "anchor", "evidence_refs")} for s in scaffold],
        "previous_plan": previous, "organizer_feedback": feedback,
        "note": "" if use_qloo else "Baseline mode: no Qloo evidence available, use only participant-provided interests.",
    }, default=str)
    data = llm.complete_json(SYSTEM, user)
    if not isinstance(data, dict) or not isinstance(data.get("concepts"), list):
        return None
    valid = {p["eid"] for p in pack}
    out = []
    for raw in data["concepts"][:2]:
        if not isinstance(raw, dict) or not raw.get("agenda"):
            continue
        refs = [r for r in raw.get("evidence_refs") or [] if r in valid]
        dropped = [r for r in raw.get("evidence_refs") or [] if r not in valid]
        fmt = raw.get("format") if raw.get("format") in FORMATS else "interest_circle"
        concept = {
            "id": "C" + uuid.uuid4().hex[:6], "format": fmt, "format_name": FORMATS[fmt]["name"],
            "title": raw.get("title") or "Untitled", "theme": raw.get("theme") or group.get("primary_theme"),
            "anchor": raw.get("anchor"), "summary": raw.get("summary", ""), "duration_min": c["duration_min"],
            "group_size": len(group["members"]),
            "agenda": [{"title": a.get("title", ""), "minutes": int(a.get("minutes") or 0), "detail": a.get("detail", "")}
                       for a in raw["agenda"] if isinstance(a, dict)],
            "materials": raw.get("materials") or [], "roles": raw.get("roles") or [],
            "cost_estimate": raw.get("cost_estimate") or {"amount": 0, "notes": ""},
            "venue": raw.get("venue") or "Organizer-chosen", "setting": c.get("setting", "any"),
            "accessibility": list(dict.fromkeys((raw.get("accessibility") or []) + _checklist(c, group))),
            "safeguards": list(dict.fromkeys((raw.get("safeguards") or []) + _safeguards(c, group))),
            "evidence_refs": refs, "generated_by": f"LLM ({llm.describe()})",
        }
        if dropped:
            concept["warnings"] = [f"Removed uncited/unknown evidence ids: {', '.join(map(str, dropped))}"]
        anchor = next((p for p in pack if p["label"] == concept["anchor"] and p["kind"] == "anchor"), None)
        concept["anchor_image"] = anchor.get("image") if anchor else None
        out.append(concept)
    return out or None


# ---------------------------------------------------------------- review + auto-fix
def review(concept, c, pack):
    checks = []
    total = sum(int(a.get("minutes") or 0) for a in concept["agenda"])
    checks.append({"check": "Duration", "status": "pass" if total == int(c["duration_min"]) else "fail",
                   "note": f"Agenda {total} min vs target {c['duration_min']} min"})
    amt = float((concept.get("cost_estimate") or {}).get("amount") or 0)
    checks.append({"check": "Budget", "status": "pass" if amt <= float(c.get("budget") or 0) else "fail",
                   "note": f"Estimated {amt:g} {c.get('currency', '')} vs budget {c.get('budget')}"})
    s = c.get("setting", "any")
    fmt_ok = s == "any" or s in FORMATS.get(concept["format"], {}).get("settings", {s})
    checks.append({"check": "Setting", "status": "pass" if fmt_ok else "fail", "note": f"Requested: {s}"})
    by_eid = {p["eid"]: p for p in pack}
    q = [r for r in concept.get("evidence_refs", []) if by_eid.get(r, {}).get("source") == "qloo"]
    checks.append({"check": "Evidence traceability", "status": "pass" if concept.get("evidence_refs") else "warn",
                   "note": f"{len(concept.get('evidence_refs', []))} cited item(s), {len(q)} from real Qloo responses"})
    if c.get("wheelchair"):
        checks.append({"check": "Wheelchair access", "status": "warn", "note": "Organizer must confirm step-free venue."})
    if concept.get("safeguards"):
        checks.append({"check": "Safeguarding", "status": "warn", "note": "; ".join(concept["safeguards"])})
    checks.append({"check": "Consent & opt-out", "status": "pass", "note": "Opt-out and opt-in contact sharing included."})
    return checks


def auto_fix(concept, c):
    total = sum(int(a.get("minutes") or 0) for a in concept["agenda"])
    target = int(c["duration_min"])
    if total != target and concept["agenda"]:
        factor = target / max(1, total)
        for a in concept["agenda"]:
            a["minutes"] = max(5, int(round(a["minutes"] * factor / 5.0)) * 5)
        concept["agenda"][-1]["minutes"] += target - sum(a["minutes"] for a in concept["agenda"])
        concept["agenda"][-1]["minutes"] = max(1, concept["agenda"][-1]["minutes"])
    if float(concept["cost_estimate"].get("amount") or 0) > float(c.get("budget") or 0):
        concept["cost_estimate"] = {"amount": float(c.get("budget") or 0),
                                    "notes": "Auto-adjusted: low-cost variant with borrowed/shared materials."}
    concept["duration_min"] = target
    return concept


# ---------------------------------------------------------------- agent loop
def run_agent(group, constraints, location=None, excluded=None, feedback=None, previous=None, use_qloo=True,
              anchors=None):
    c = {**DEFAULT_CONSTRAINTS, **(constraints or {})}
    excluded = excluded or {"themes": [], "formats": []}
    trace, steps = [], 0

    def log(tool, msg, **kw):
        nonlocal steps
        steps += 1
        trace.append({"step": steps, "tool": tool, "message": msg, **kw})
        if steps > config.AGENT_MAX_STEPS:
            raise RuntimeError("Agent step limit reached")

    if use_qloo and anchors is None:
        log("discover_culture", "Querying Qloo Insights with the group's combined signals (explainability on).")
        try:
            anchors = group_anchors(group["members"], location if c.get("setting") != "online" else None)
            log("discover_culture", f"{len(anchors['anchors'])} anchors, {len(anchors['venues'])} venues returned.",
                warnings=anchors["warnings"])
        except QlooError as exc:
            anchors = {"anchors": [], "venues": [], "requests": [], "warnings": [str(exc)]}
            log("discover_culture", f"Qloo error — continuing with bridge evidence only: {exc}")
    pack = evidence_pack(group, anchors if use_qloo else None, use_qloo)
    log("build_bridges", f"Evidence pack: {len(pack)} items ({sum(p['source'] == 'qloo' for p in pack)} from Qloo).")
    if not pack:
        log("build_bridges", "No traceable bridge — honest fallback, nothing fabricated.")
        return {"concepts": [], "evidence": [], "trace": trace, "anchors": anchors, "constraints": c,
                "fallback": "No shared or Qloo-linked evidence for this group. Add/confirm interests or try another category."}

    concepts = None
    if llm.enabled():
        log("generate_event", "Drafting with LLM using only the evidence pack.")
        concepts = llm_generate(group, pack, c, excluded, feedback, previous, use_qloo)
        if not concepts:
            log("generate_event", "LLM unavailable/invalid JSON — falling back to rule-based planner.")
    if not concepts:
        concepts = rule_generate(group, pack, c, excluded)
        log("generate_event", f"Rule-based planner produced {len(concepts)} concept(s).")

    for con in concepts:
        for attempt in range(2):
            checks = review(con, c, pack)
            fails = [k for k in checks if k["status"] == "fail"]
            log("review_event", f"{con['title']}: {len(fails)} failing check(s).", checks=[k["check"] for k in fails])
            if not fails:
                break
            if any(k["check"] == "Setting" for k in fails):
                con["format"], con["format_name"] = "interest_circle", FORMATS["interest_circle"]["name"]
            auto_fix(con, c)
            log("revise_event", f"Auto-fixed {', '.join(k['check'] for k in fails)}.")
        con["review"] = review(con, c, pack)
    return {"concepts": concepts, "evidence": pack, "trace": trace, "anchors": anchors, "constraints": c,
            "excluded": excluded, "generated_at": time.time()}


def parse_feedback(text: str, c: dict) -> tuple[dict, list[str]]:
    """Lightweight intent parsing so revision works without an LLM."""
    t = (text or "").lower()
    c = copy.deepcopy(c)
    notes = []
    if any(w in t for w in ("shorter", "less time", "quicker")):
        c["duration_min"] = max(30, int(c["duration_min"] * 0.67) // 5 * 5); notes.append(f"duration → {c['duration_min']} min")
    if any(w in t for w in ("longer", "more time")):
        c["duration_min"] = int(c["duration_min"] * 1.5) // 5 * 5; notes.append(f"duration → {c['duration_min']} min")
    if any(w in t for w in ("free", "no cost", "zero budget")):
        c["budget"] = 0; notes.append("budget → 0")
    elif "cheaper" in t or "lower budget" in t:
        c["budget"] = round(float(c.get("budget") or 0) / 2, 2); notes.append(f"budget → {c['budget']}")
    for s in ("online", "outdoor", "indoor"):
        if s in t:
            c["setting"] = s; notes.append(f"setting → {s}")
    if "quiet" in t:
        c["quiet_space"] = True; notes.append("quiet space required")
    if "wheelchair" in t or "accessible" in t:
        c["wheelchair"] = True; notes.append("wheelchair access required")
    if "large print" in t or "visual" in t:
        c["visual_aids"] = True; notes.append("visual aids required")
    return c, notes
