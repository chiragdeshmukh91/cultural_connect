"""Shared Culture Discovery Engine.

Turns participant-provided interests + real Qloo evidence into *transparent* connection hypotheses
and small groups. This is a configurable heuristic, NOT a validated compatibility score, and Qloo is
never claimed to compute interpersonal compatibility — Qloo supplies the cultural signals; this module
only counts and weights traceable overlaps between them.
"""
from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict

from .qloo_service import pretty_type

WEIGHTS = {
    "same_signal": 3.0,       # both chose the same Qloo-resolved entity/tag/audience
    "mentorship": 5.0,        # one offers to teach what the other wants to learn
    "same_label": 2.0,        # same typed interest that was not resolved in Qloo
    "qloo_taste_cap": 2.0,    # overlap in Qloo taste-analysis tags
    "qloo_recs_cap": 1.5,     # overlap in Qloo cross-domain recommendations
    "crossover": 1.5,         # one person's explicit interest appears in the other's Qloo results
    "crossover_cap": 3.0,
    "location": 1.0,
}
THRESHOLD = 1.5


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _signals(p: dict) -> list[dict]:
    out = []
    for it in p.get("interests", []):
        for r in it.get("resolved", []) or []:
            out.append({**r, "label": it.get("label"), "intent": it.get("intent", "share")})
    return out


def _ranked(items: list[dict]) -> dict:
    """id -> weight in (0,1]; uses Qloo affinity when present, otherwise rank order."""
    out = {}
    n = max(1, len(items))
    for i, it in enumerate(items):
        if not it.get("id"):
            continue
        aff = it.get("affinity")
        w = float(aff) if isinstance(aff, (int, float)) else 1 - i / (n + 1)
        out[it["id"]] = max(out.get(it["id"], 0), w)
    return out


def pair_evidence(a: dict, b: dict) -> dict:
    ev: list[dict] = []
    sa, sb = _signals(a), _signals(b)
    ids_b = {s["id"]: s for s in sb}
    seen = set()
    for s in sa:
        o = ids_b.get(s["id"])
        if not o or s["id"] in seen:
            continue
        seen.add(s["id"])
        intents = {s["intent"], o["intent"]}
        if intents == {"teach", "learn"}:
            teacher, learner = (a, b) if s["intent"] == "teach" else (b, a)
            ev.append({"kind": "mentorship", "weight": WEIGHTS["mentorship"], "source": "participant+qloo-id",
                       "label": s["name"], "ref": s["id"], "ref_type": s.get("type"),
                       "teacher": teacher["name"], "learner": learner["name"],
                       "detail": f"{teacher['name']} offers to teach {s['name']}; {learner['name']} wants to learn it."})
        else:
            ev.append({"kind": "same_signal", "weight": WEIGHTS["same_signal"], "source": "participant+qloo-id",
                       "label": s["name"], "ref": s["id"], "ref_type": s.get("type"),
                       "detail": f"Both chose {s['name']} ({pretty_type(s.get('type'))}, confirmed Qloo ID)."})

    # same typed label, unresolved on at least one side
    la = {_norm(i["label"]): i for i in a.get("interests", []) if i.get("label")}
    for i in b.get("interests", []):
        k = _norm(i.get("label", ""))
        if k and k in la and not any(e["label"] and _norm(e["label"]) == k for e in ev):
            ia = la[k]
            kind = "mentorship" if {ia.get("intent"), i.get("intent")} == {"teach", "learn"} else "same_label"
            extra = {}
            if kind == "mentorship":
                t, l = (a, b) if ia.get("intent") == "teach" else (b, a)
                extra = {"teacher": t["name"], "learner": l["name"]}
            ev.append({"kind": kind, "weight": WEIGHTS[kind], "source": "participant", "label": i["label"],
                       "ref": None, "detail": f"Both typed “{i['label']}” (participant-provided overlap).", **extra})

    pa, pb = a.get("profile") or {}, b.get("profile") or {}
    ta, tb = _ranked(pa.get("tags", [])), _ranked(pb.get("tags", []))
    shared_tags = sorted(set(ta) & set(tb), key=lambda k: -(ta[k] + tb[k]))
    if shared_tags:
        names = {t["id"]: t["name"] for t in pa.get("tags", [])}
        w = min(WEIGHTS["qloo_taste_cap"], sum(min(ta[k], tb[k]) for k in shared_tags))
        ev.append({"kind": "qloo_taste", "weight": round(w, 2), "source": "qloo",
                   "label": ", ".join(names.get(k, k) for k in shared_tags[:4]), "refs": shared_tags[:8],
                   "detail": f"Qloo taste analysis returned {len(shared_tags)} tag(s) for both people's signals."})
    ea, eb = _ranked(pa.get("entities", [])), _ranked(pb.get("entities", []))
    shared_e = sorted(set(ea) & set(eb), key=lambda k: -(ea[k] + eb[k]))
    if shared_e:
        names = {e["id"]: e["name"] for e in pa.get("entities", [])}
        w = min(WEIGHTS["qloo_recs_cap"], sum(min(ea[k], eb[k]) for k in shared_e))
        ev.append({"kind": "qloo_recs", "weight": round(w, 2), "source": "qloo",
                   "label": ", ".join(names.get(k, k) for k in shared_e[:3]), "refs": shared_e[:6],
                   "detail": f"Qloo Insights recommended the same {len(shared_e)} title(s)/entity(ies) to both."})

    # crossover: my explicit interest shows up in your Qloo results
    cross_w = 0.0
    for me, other, prof in ((a, b, pb), (b, a, pa)):
        pool = {x["id"] for x in prof.get("tags", []) + prof.get("entities", [])}
        for s in _signals(me):
            if s["id"] in pool and s["id"] not in seen and cross_w < WEIGHTS["crossover_cap"]:
                cross_w += WEIGHTS["crossover"]
                ev.append({"kind": "crossover", "weight": WEIGHTS["crossover"], "source": "qloo",
                           "label": s["name"], "ref": s["id"],
                           "detail": f"Qloo links {other['name']}'s interests to {me['name']}'s pick “{s['name']}”."})

    if a.get("location") and b.get("location"):
        ta_, tb_ = set(_norm(a["location"]).split()), set(_norm(b["location"]).split())
        if ta_ & tb_:
            ev.append({"kind": "location", "weight": WEIGHTS["location"], "source": "participant",
                       "label": a["location"], "ref": None, "detail": "Same or overlapping area."})

    score = round(sum(e["weight"] for e in ev), 2)
    return {"a": a["id"], "b": b["id"], "score": score, "evidence": ev}


def build_groups(participants: list[dict], min_size: int = 2, max_size: int = 6,
                 same_area_only: bool = False) -> dict:
    people = [p for p in participants if p.get("consent", True)]
    by_id = {p["id"]: p for p in people}
    pairs = {}
    for a, b in itertools.combinations(people, 2):
        pe = pair_evidence(a, b)
        if same_area_only and not any(e["kind"] == "location" for e in pe["evidence"]):
            pe["score"] = 0.0
            pe["blocked"] = "different area"
        pairs[frozenset((a["id"], b["id"]))] = pe

    def s(x, y):
        return pairs[frozenset((x, y))]["score"] if x != y else 0

    unassigned = set(by_id)
    groups: list[list[str]] = []
    while True:
        cands = [(pairs[frozenset((x, y))]["score"], x, y) for x, y in itertools.combinations(sorted(unassigned), 2)]
        cands = [c for c in cands if c[0] >= THRESHOLD]
        if not cands:
            break
        _, x, y = max(cands)
        g = [x, y]
        unassigned -= {x, y}
        while len(g) < max_size:
            best = max(((sum(s(u, m) for m in g) / len(g), u) for u in unassigned), default=None)
            if not best or best[0] < THRESHOLD:
                break
            g.append(best[1])
            unassigned.discard(best[1])
        groups.append(g)

    # attach leftovers where they have any traceable bridge
    for u in sorted(unassigned.copy()):
        opts = [(sum(s(u, m) for m in g) / len(g), i) for i, g in enumerate(groups) if len(g) < max_size]
        opts = [o for o in opts if o[0] > 0]
        if opts:
            groups[max(opts)[1]].append(u)
            unassigned.discard(u)

    # merge undersized groups into their best neighbour
    for g in [g for g in groups if len(g) < min_size]:
        others = [(sum(s(u, m) for u in g for m in h), i) for i, h in enumerate(groups) if h is not g and len(h) + len(g) <= max_size]
        if others and max(others)[0] > 0:
            groups[max(others)[1]].extend(g)
            groups.remove(g)

    result = []
    for i, g in enumerate(groups, 1):
        members = [by_id[m] for m in g]
        result.append(describe_group(f"G{i}", members, pairs))
    return {
        "groups": result,
        "unmatched": [{"id": u, "name": by_id[u]["name"],
                       "hint": "No traceable bridge yet — add or confirm more interests, or try another category."}
                      for u in sorted(unassigned)],
        "excluded_no_consent": [p["name"] for p in participants if not p.get("consent", True)],
        "pairs": [dict(v, a_name=by_id[v["a"]]["name"], b_name=by_id[v["b"]]["name"]) for v in pairs.values() if v["score"] > 0],
        "method": "Transparent heuristic: " + ", ".join(f"{k}={v}" for k, v in WEIGHTS.items()) + f"; group threshold {THRESHOLD}. Not a validated compatibility score.",
    }


def describe_group(gid: str, members: list[dict], pairs: dict) -> dict:
    ev = []
    for a, b in itertools.combinations(members, 2):
        pe = pairs[frozenset((a["id"], b["id"]))]
        for e in pe["evidence"]:
            ev.append(dict(e, between=[a["name"], b["name"]]))
    theme_count = Counter()
    theme_w = defaultdict(float)
    for e in ev:
        if e["kind"] == "location":
            continue
        for lbl in [x.strip() for x in (e["label"] or "").split(",") if x.strip()][:2]:
            theme_count[lbl] += 1
            # explicit, participant-chosen bridges outrank broad Qloo overlap when naming the theme
            theme_w[lbl] += e["weight"] * (0.5 if e["kind"] in ("qloo_taste", "qloo_recs") else 1.0)
    themes = sorted(theme_w, key=lambda k: -theme_w[k])[:6]
    kinds = Counter(e["kind"] for e in ev)
    scores = [pairs[frozenset((a["id"], b["id"]))]["score"] for a, b in itertools.combinations(members, 2)]
    return {
        "id": gid,
        "members": [{"id": m["id"], "name": m["name"], "age_band": m.get("age_band"), "location": m.get("location"),
                     "interests": [{"label": i["label"], "intent": i.get("intent", "share")} for i in m.get("interests", [])],
                     "resolved": _signals(m)} for m in members],
        "themes": [{"label": t, "weight": round(theme_w[t], 2), "mentions": theme_count[t]} for t in themes],
        "primary_theme": themes[0] if themes else None,
        "evidence": ev,
        "evidence_kinds": dict(kinds),
        "cohesion": round(sum(scores) / max(1, len(scores)), 2),
        "mentorships": [e for e in ev if e["kind"] == "mentorship"],
    }
