"""Qloo-facing tools: resolve free-text interests, build taste profiles, find group anchors.

Every object returned here is a *normalized copy of a real Qloo response*; nothing is invented.
Each item carries `source` (the Qloo route that returned it) so the UI can label evidence.
"""
from __future__ import annotations

import difflib
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import config
from .qloo_client import QlooError, get

_pool = ThreadPoolExecutor(max_workers=8)


# ---------------------------------------------------------------- normalizers
def _first(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _results(data: Any, key: str) -> list:
    """Qloo returns either {results: [...]} or {results: {key: [...]}}."""
    if not isinstance(data, dict):
        return []
    res = data.get("results", data)
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        v = res.get(key)
        if isinstance(v, list):
            return v
        for v in res.values():
            if isinstance(v, list):
                return v
    return []


def _affinity(item: dict):
    q = item.get("query") or {}
    return q.get("affinity") if isinstance(q, dict) else None


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _place_fields(e: dict, props: dict) -> dict:
    """Operational details Qloo returns for place entities, copied as-is (None when Qloo did not return them)."""
    loc = e.get("location") if isinstance(e.get("location"), dict) else (props.get("location") if isinstance(props.get("location"), dict) else {})
    lat = _num(loc.get("lat", loc.get("latitude")))
    lon = _num(loc.get("lon", loc.get("lng", loc.get("longitude"))))
    if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    closed = props.get("is_closed", props.get("closed"))
    return {"lat": lat, "lon": lon,
            "hours": props.get("hours") if isinstance(props.get("hours"), (dict, list)) else None,
            "website": props.get("website") if isinstance(props.get("website"), str) else None,
            "phone": props.get("phone") if isinstance(props.get("phone"), str) else None,
            "price_level": props.get("price_level"),
            "is_closed": closed if isinstance(closed, bool) else None}


def norm_entity(e: dict, source: str) -> dict:
    props = e.get("properties") or {}
    types = e.get("types") or []
    etype = _first(e, "subtype", default=None) or (types[0] if types else e.get("type", "urn:entity"))
    img = props.get("image")
    tags = []
    for t in (e.get("tags") or [])[:12]:
        if isinstance(t, dict):
            tags.append({"id": _first(t, "id", "tag_id"), "name": t.get("name"), "type": t.get("type")})
    return {
        "kind": "entity", "id": _first(e, "entity_id", "id"), "name": e.get("name"),
        "type": etype, "types": types,
        "description": _first(props, "short_description", "description", default=""),
        "image": img.get("url") if isinstance(img, dict) else img,
        "address": props.get("address"),
        **_place_fields(e, props),
        "popularity": e.get("popularity"), "affinity": _affinity(e),
        "explainability": (e.get("query") or {}).get("explainability") if isinstance(e.get("query"), dict) else None,
        "tags": tags, "source": source,
    }


def norm_tag(t: dict, source: str) -> dict:
    return {
        "kind": "tag", "id": _first(t, "tag_id", "id", "tag_value"), "name": t.get("name"),
        "type": _first(t, "subtype", "type", default="urn:tag"), "parents": t.get("types") or t.get("parents"),
        "popularity": t.get("popularity"), "affinity": _affinity(t), "source": source,
    }


def norm_audience(a: dict, source: str) -> dict:
    parents = a.get("parents") or a.get("types") or []
    return {
        "kind": "audience", "id": _first(a, "id", "entity_id", "audience_id"), "name": a.get("name"),
        "type": _first(a, "parent_type", "type", default=(parents[0] if parents else "urn:audience")),
        "popularity": a.get("popularity"), "affinity": _affinity(a), "source": source,
    }


def pretty_type(urn: str | None) -> str:
    if not urn:
        return ""
    last = urn.split(":")[-1] if urn.count(":") < 4 else urn.split(":")[2]
    return last.replace("_", " ").title()


# ---------------------------------------------------------------- resolution
def _score_match(label: str, name: str | None) -> float:
    if not name:
        return 0.0
    a, b = label.lower().strip(), name.lower().strip()
    if a == b:
        return 1.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        r = max(r, 0.8)
    return r


def search_entities(query: str, types: list[str] | None = None, take: int = 6) -> list[dict]:
    params = {"query": query, "take": take}
    if types:
        params["types"] = types
    data = get("/search", params)
    return [norm_entity(e, "GET /search") for e in _results(data, "entities") if isinstance(e, dict)]


def search_tags(query: str, take: int = 8) -> list[dict]:
    data = get("/v2/tags", {"filter.query": query, "take": take, "feature.typo_tolerance": "true"})
    return [norm_tag(t, "GET /v2/tags") for t in _results(data, "tags") if isinstance(t, dict)]


_aud_catalog: list[dict] | None = None
_aud_lock = threading.Lock()


def audience_catalog() -> list[dict]:
    """/v2/audiences has no free-text filter, so we page each parent type once and cache it."""
    global _aud_catalog
    with _aud_lock:
        if _aud_catalog is not None:
            return _aud_catalog

        def fetch(ptype):
            out = []
            for page in (1, 2, 3):
                try:
                    data = get("/v2/audiences", {"filter.parents.types": ptype, "take": 50, "page": page})
                except QlooError:
                    break
                rows = _results(data, "audiences")
                for a in rows:
                    if isinstance(a, dict):
                        n = norm_audience(a, "GET /v2/audiences")
                        n["type"] = n["type"] if n["type"] != "urn:audience" else ptype
                        out.append(n)
                if len(rows) < 50:
                    break
            return out

        cat: list[dict] = []
        for rows in _pool.map(fetch, config.AUDIENCE_PARENT_TYPES):
            cat.extend(rows)
        _aud_catalog = cat
        return cat


def search_audiences(query: str, take: int = 5) -> list[dict]:
    q = query.lower()
    toks = set(re.findall(r"[a-z0-9]+", q))
    scored = []
    for a in audience_catalog():
        name = (a.get("name") or "").lower()
        ntoks = set(re.findall(r"[a-z0-9]+", name))
        overlap = len(toks & ntoks) / max(1, len(toks))
        s = max(overlap, difflib.SequenceMatcher(None, q, name).ratio() * 0.9)
        if s >= 0.5:
            scored.append((s, a))
    scored.sort(key=lambda x: -x[0])
    return [dict(a, match=round(s, 3)) for s, a in scored[:take]]


def resolve_interest(label: str, category: str | None = None) -> dict:
    """Return candidate Qloo entities / tags / audiences for one typed interest."""
    types = [category] if category and category.startswith("urn:entity") else None
    jobs = {
        "entities": _pool.submit(search_entities, label, types, 6),
        "tags": _pool.submit(search_tags, label, 8),
        "audiences": _pool.submit(search_audiences, label, 5),
    }
    out: dict[str, Any] = {"label": label, "candidates": [], "warnings": []}
    for kind, fut in jobs.items():
        try:
            rows = fut.result()
        except QlooError as exc:
            out["warnings"].append(f"{kind}: {exc}")
            continue
        for r in rows:
            r["match"] = r.get("match") or round(_score_match(label, r.get("name")), 3)
            out["candidates"].append(r)
    # rank: textual match first, then popularity
    out["candidates"].sort(key=lambda c: (-(c.get("match") or 0), -(c.get("popularity") or 0)))
    out["candidates"] = [c for c in out["candidates"] if c.get("id")][:14]
    # Pre-select (organizer can change): best entity + best tag/audience when they clearly match the text.
    picks = []
    for kinds in (("entity",), ("tag", "audience")):
        best = next((c for c in out["candidates"] if c["kind"] in kinds and c["match"] >= 0.8), None)
        if best:
            picks.append(best["id"])
    if not picks and out["candidates"] and out["candidates"][0]["match"] >= 0.6:
        picks = [out["candidates"][0]["id"]]
    out["suggested_ids"] = picks
    out["suggested"] = picks[0] if picks else None
    return out


# ---------------------------------------------------------------- insights
def _signals(entity_ids, tag_ids, audience_ids) -> dict:
    p = {}
    if entity_ids:
        p["signal.interests.entities"] = list(dict.fromkeys(entity_ids))[:20]
    if tag_ids:
        p["signal.interests.tags"] = list(dict.fromkeys(tag_ids))[:20]
    if audience_ids:
        p["signal.demographics.audiences"] = list(dict.fromkeys(audience_ids))[:10]
    return p


def insights(filter_type: str, entity_ids=(), tag_ids=(), audience_ids=(), take: int = 10,
             explain: bool = False, location_query: str | None = None, extra: dict | None = None) -> dict:
    params = {"filter.type": filter_type, "take": take, **_signals(entity_ids, tag_ids, audience_ids)}
    if explain and entity_ids:
        params["feature.explainability"] = "true"
    if location_query:
        params["filter.location.query"] = location_query
    if extra:
        params.update(extra)
    data = get("/v2/insights", params)
    src = f"GET /v2/insights filter.type={filter_type}"
    if filter_type == "urn:tag":
        items = [norm_tag(t, src) for t in _results(data, "tags") if isinstance(t, dict)]
    else:
        items = [norm_entity(e, src) for e in _results(data, "entities") if isinstance(e, dict)]
    q = data.get("query") if isinstance(data, dict) else None
    return {"items": items, "request": {k: v for k, v in params.items()},
            "aggregate_explainability": (q or {}).get("explainability") if isinstance(q, dict) else None}


def split_signals(resolved: list[dict]):
    e = [r["id"] for r in resolved if r.get("kind") == "entity"]
    t = [r["id"] for r in resolved if r.get("kind") == "tag"]
    a = [r["id"] for r in resolved if r.get("kind") == "audience"]
    return e, t, a


def taste_profile(resolved: list[dict], discovery_types: list[str] | None = None) -> dict:
    """Taste analysis (urn:tag) + cross-domain recommendations for one participant's confirmed signals."""
    e, t, a = split_signals(resolved)
    profile = {"tags": [], "entities": [], "requests": [], "warnings": []}
    if not (e or t or a):
        profile["warnings"].append("No confirmed Qloo signals for this participant.")
        return profile
    jobs = {"urn:tag": _pool.submit(insights, "urn:tag", e, t, a, 25)}
    for ft in (discovery_types or config.DISCOVERY_TYPES):
        jobs[ft] = _pool.submit(insights, ft, e, t, a, 8)
    for ft, fut in jobs.items():
        try:
            r = fut.result()
        except QlooError as exc:
            profile["warnings"].append(f"{pretty_type(ft)}: {exc}")
            continue
        profile["requests"].append(r["request"])
        (profile["tags"] if ft == "urn:tag" else profile["entities"]).extend(r["items"])
    return profile


def _explain_sources(item: dict) -> list[dict]:
    """Pull (input entity id, score) pairs out of whatever explainability structure Qloo returned."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            eid = x.get("entity_id") or x.get("id")
            score = x.get("score")
            if eid and isinstance(score, (int, float)):
                out.append({"id": eid, "score": score})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(item.get("explainability"))
    return out


def group_anchors(members: list[dict], location: str | None, discovery_types: list[str] | None = None,
                  take: int = 5) -> dict:
    """One combined Qloo query per output category, with explainability -> which member drove each anchor."""
    owner: dict[str, set] = {}
    all_res = []
    for m in members:
        for r in m.get("resolved", []):
            all_res.append(r)
            owner.setdefault(r["id"], set()).add(m["name"])
    e, t, a = split_signals(all_res)
    out = {"anchors": [], "venues": [], "requests": [], "warnings": []}
    if not (e or t or a):
        out["warnings"].append("Group has no confirmed Qloo signals.")
        return out
    jobs = {ft: _pool.submit(insights, ft, e, t, a, take, True) for ft in (discovery_types or config.DISCOVERY_TYPES)}
    if location:
        jobs["venue"] = _pool.submit(insights, "urn:entity:place", e, t, a, 6, False, location)
    for ft, fut in jobs.items():
        try:
            r = fut.result()
        except QlooError as exc:
            out["warnings"].append(f"{'Venues' if ft == 'venue' else pretty_type(ft)}: {exc}")
            continue
        out["requests"].append(r["request"])
        for it in r["items"]:
            srcs = _explain_sources(it)
            it["driven_by"] = sorted({n for s in srcs for n in owner.get(s["id"], [])})
            it["explain_scores"] = srcs[:6]
        (out["venues"] if ft == "venue" else out["anchors"]).extend(r["items"])
    return out
