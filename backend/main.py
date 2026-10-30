"""Culture Connect API — the browser talks only to these routes; only this server talks to Qloo."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, llm, planner, store
from . import platform_svc
from .auth import optional_user
from . import agents, jobs
from .agents_api import router as agents_router
from .circles_api import router as circles_router
from .platform_api import router as platform_router
from .bridges import build_groups
from .qloo_client import AUDIT, QlooError, get as qget
from .qloo_service import audience_catalog, resolve_interest, taste_profile

log = logging.getLogger("culture_connect")
app = FastAPI(title="Culture Connect", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
_exec = ThreadPoolExecutor(max_workers=4)
db.migrate()  # apply pending, reversible SQL migrations (backend/migrations) before serving
app.include_router(circles_router)  # individuals + Circles (/api/me, /api/circles/*, /api/circle-events/*)
app.include_router(platform_router)  # accounts, organisations, events, places, chat, notifications
app.include_router(agents_router)    # Agent Activity Centre (runs, steps, invites, approvals, settings)


@app.on_event("startup")
def _start_agent_worker():
    # Persistent background worker: runs queued agent jobs and the coordination sweep; resumes interrupted runs.
    if config.AGENT_WORKER:
        jobs.start_worker(tick=agents.sweep, tick_every=config.AGENT_SWEEP_SECONDS)


@app.on_event("shutdown")
def _stop_agent_worker():
    jobs.stop_worker()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; "
       "frame-src https://www.openstreetmap.org; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ---------------------------------------------------------------- models
class ResolveIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    category: Optional[str] = None


class ProgramRef(BaseModel):
    program_id: str
    group_id: Optional[str] = None


class ReviseIn(ProgramRef):
    reject_concept_id: Optional[str] = None
    reject_theme: Optional[str] = None
    constraints: Optional[dict[str, Any]] = None
    text: Optional[str] = Field(default=None, max_length=1000)


class ApproveIn(ProgramRef):
    concept_id: str


def _program(pid: str, uid: Optional[str] = None) -> dict:
    p = store.get(pid)
    # Organisation programmes are visible only to that organisation's team (404 avoids leaking existence).
    if not p or not platform_svc.can_access_program(p, uid):
        raise HTTPException(404, "Program not found")
    return p


def _qloo_guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except QlooError as exc:
        log.warning("Qloo error: %s", exc)
        raise HTTPException(exc.status if exc.status and 400 <= exc.status < 600 else 502, str(exc))


# ---------------------------------------------------------------- meta / health
@app.get("/api/health")
def health():
    return {"ok": True, "qloo_key_configured": bool(config.QLOO_API_KEY), "qloo_base_url": config.QLOO_BASE_URL,
            "planner": llm.describe(), "discovery_types": config.DISCOVERY_TYPES}


@app.get("/api/qloo/check")
def qloo_check():
    t0 = time.time()
    # Same request shape that was verified manually with curl (Insights needs a signal on the hackathon key).
    data = _qloo_guard(qget, "/v2/insights", {"filter.type": "urn:entity:artist", "take": 1,
                                              "signal.interests.entities": "B8BEE72B-B321-481F-B81A-A44881D094D6"}, False)
    return {"ok": True, "ms": int((time.time() - t0) * 1000), "keys": list(data.keys()) if isinstance(data, dict) else []}


@app.get("/api/meta")
def meta():
    return {
        "entity_types": [{"id": t, "label": t.split(":")[-1].replace("_", " ").title()} for t in config.ENTITY_TYPES],
        "intents": [{"id": "share", "label": "Enjoys / shares"}, {"id": "teach", "label": "Can teach / mentor"},
                    {"id": "learn", "label": "Wants to learn"}],
        "goals": ["connect", "learn", "create", "play", "debate", "support", "act"],
        "age_bands": ["", "under_18", "18_24", "25_44", "45_64", "65_plus"],
        "formats": {k: v["name"] for k, v in planner.FORMATS.items()},
        "default_constraints": planner.DEFAULT_CONSTRAINTS,
    }


@app.get("/api/audit")
def audit(limit: int = 60):
    return list(AUDIT)[:limit]


@app.get("/api/audiences/warm")
def warm_audiences():
    return {"count": len(_qloo_guard(audience_catalog))}


# ---------------------------------------------------------------- programs
@app.get("/api/programs")
def programs(uid: Optional[str] = Depends(optional_user)):
    return [p for p in store.list_programs() if platform_svc.can_access_program(store.get(p["id"]) or {}, uid)]


@app.post("/api/programs")
def create_program(doc: dict):
    doc.pop("id", None)
    doc.pop("org_id", None)  # organisation programmes are created via /api/orgs/{id}/programs (team only)
    return store.save(doc)


@app.get("/api/programs/{pid}")
def read_program(pid: str, uid: Optional[str] = Depends(optional_user)):
    return _program(pid, uid)


@app.put("/api/programs/{pid}")
def update_program(pid: str, doc: dict, uid: Optional[str] = Depends(optional_user)):
    old = _program(pid, uid)
    doc["id"] = pid
    for k in ("org_id", "circles"):  # never let a client move a programme between organisations
        if k in old:
            doc[k] = old[k]
        else:
            doc.pop(k, None)
    for k in ("bridges", "plans"):  # server-computed fields survive client saves unless explicitly sent
        if k not in doc and k in old:
            doc[k] = old[k]
    return store.save(doc)


@app.delete("/api/programs/{pid}")
def delete_program(pid: str, uid: Optional[str] = Depends(optional_user)):
    _program(pid, uid)
    store.delete(pid)
    return {"ok": True}


# ---------------------------------------------------------------- pipeline
@app.post("/api/interests/resolve")
def resolve(body: ResolveIn):
    return _qloo_guard(resolve_interest, body.label.strip(), body.category)


@app.post("/api/discovery/run")
def discovery(ref: ProgramRef, uid: Optional[str] = Depends(optional_user)):
    p = _program(ref.program_id, uid)
    people = [x for x in p.get("participants", []) if x.get("consent", True)]

    def run(person):
        resolved = [r for i in person.get("interests", []) for r in (i.get("resolved") or [])]
        try:
            return person["id"], taste_profile(resolved)
        except QlooError as exc:
            return person["id"], {"tags": [], "entities": [], "requests": [], "warnings": [str(exc)]}

    results = dict(_exec.map(run, people))
    for person in p["participants"]:
        if person["id"] in results:
            person["profile"] = results[person["id"]]
    p.pop("bridges", None)
    return store.save(p)


@app.post("/api/bridges/build")
def bridges(ref: ProgramRef, uid: Optional[str] = Depends(optional_user)):
    p = _program(ref.program_id, uid)
    g = p.get("grouping") or {}
    p["bridges"] = build_groups(p.get("participants", []), int(g.get("min_size", 2)), int(g.get("max_size", 6)),
                                bool(g.get("same_area_only", False)))
    p["plans"] = {}
    return store.save(p)


def _group(p, gid):
    for g in (p.get("bridges") or {}).get("groups", []):
        if g["id"] == gid:
            return g
    raise HTTPException(404, "Group not found — build bridges first")


@app.post("/api/events/generate")
def generate(ref: ProgramRef, uid: Optional[str] = Depends(optional_user)):
    p = _program(ref.program_id, uid)
    g = _group(p, ref.group_id)
    plan = planner.run_agent(g, p.get("constraints"), p.get("location"))
    p.setdefault("plans", {})[g["id"]] = {"current": plan, "history": [], "approved": None}
    store.save(p)
    return plan


@app.post("/api/events/revise")
def revise(body: ReviseIn, uid: Optional[str] = Depends(optional_user)):
    p = _program(body.program_id, uid)
    g = _group(p, body.group_id)
    state = p.setdefault("plans", {}).get(g["id"])
    if not state:
        raise HTTPException(400, "Generate a plan first")
    cur = state["current"]
    c = dict(cur.get("constraints") or p.get("constraints") or {})
    excluded = cur.get("excluded") or {"themes": [], "formats": []}
    notes = []
    if body.reject_concept_id:
        rej = next((x for x in cur["concepts"] if x["id"] == body.reject_concept_id), None)
        if rej:
            excluded["formats"].append(rej["format"])
            notes.append(f"rejected “{rej['title']}”")
    if body.reject_theme:
        excluded["themes"].append(body.reject_theme)
        notes.append(f"excluded theme {body.reject_theme}")
    if body.constraints:
        c.update(body.constraints)
        notes.append("constraints updated")
    if body.text:
        c, n2 = planner.parse_feedback(body.text, c)
        notes += n2 or ["free-text feedback passed to planner"]
    previous = [{k: x.get(k) for k in ("title", "format", "theme", "agenda")} for x in cur["concepts"]]
    new = planner.run_agent(g, c, p.get("location"), excluded, body.text, previous, True, cur.get("anchors"))
    new["revision_notes"] = notes
    state["history"].append({"at": time.time(), "notes": notes, "titles": [x["title"] for x in cur["concepts"]]})
    state["current"] = new
    p["constraints"] = {**(p.get("constraints") or {}), **c}
    store.save(p)
    return new


@app.post("/api/events/approve")
def approve(body: ApproveIn, uid: Optional[str] = Depends(optional_user)):
    p = _program(body.program_id, uid)
    g = _group(p, body.group_id)
    state = (p.get("plans") or {}).get(g["id"])
    if not state:
        raise HTTPException(400, "Generate a plan first")
    con = next((x for x in state["current"]["concepts"] if x["id"] == body.concept_id), None)
    if not con:
        raise HTTPException(404, "Concept not found")
    state["approved"] = {**con, "approved_at": time.time()}
    store.save(p)
    return state["approved"]


def _metrics(plan):
    ev = {e["eid"]: e for e in plan.get("evidence", [])}
    cs = plan.get("concepts", [])
    refs = [r for c in cs for r in c.get("evidence_refs", [])]
    checks = [k for c in cs for k in c.get("review", [])]
    return {
        "concepts": len(cs),
        "traceable_citations": len([r for r in refs if r in ev]),
        "qloo_citations": len([r for r in refs if ev.get(r, {}).get("source") == "qloo"]),
        "distinct_formats": len({c["format"] for c in cs}),
        "checks_passed": f"{sum(k['status'] == 'pass' for k in checks)}/{len(checks)}",
        "personalised_roles": sum(1 for c in cs for r in c.get("roles", []) if not str(r.get("role", "")).startswith("Contributor")),
        "evidence_items": len(ev),
    }


@app.post("/api/events/compare")
def compare(ref: ProgramRef, uid: Optional[str] = Depends(optional_user)):
    p = _program(ref.program_id, uid)
    g = _group(p, ref.group_id)
    state = (p.get("plans") or {}).get(g["id"])
    qplan = state["current"] if state else planner.run_agent(g, p.get("constraints"), p.get("location"))
    base = planner.run_agent(g, qplan.get("constraints") or p.get("constraints"), None, use_qloo=False)
    return {"baseline": base, "qloo": qplan, "metrics": {"baseline": _metrics(base), "qloo": _metrics(qplan)},
            "note": "Same inputs and constraints; baseline sees only participant-typed interests (no Qloo calls)."}


@app.get("/api/programs/{pid}/export", response_class=PlainTextResponse)
def export(pid: str, uid: Optional[str] = Depends(optional_user)):
    p = _program(pid, uid)
    lines = [f"# {p.get('name', 'Culture Connect program')}", "", f"Area: {p.get('location') or '—'}", ""]
    for gid, st in (p.get("plans") or {}).items():
        con = st.get("approved") or (st["current"]["concepts"] or [None])[0]
        if not con:
            continue
        ev = {e["eid"]: e for e in st["current"].get("evidence", [])}
        lines += [f"## {gid}: {con['title']}", "", con.get("summary", ""), "",
                  f"Duration {con['duration_min']} min · Group {con['group_size']} · Cost ~{con['cost_estimate']['amount']}",
                  f"Venue: {con.get('venue')}", "", "### Agenda"]
        lines += [f"- {a['title']} ({a['minutes']} min): {a['detail']}" for a in con["agenda"]]
        lines += ["", "### Roles"] + [f"- {r['member']}: {r['role']}" for r in con.get("roles", [])]
        lines += ["", "### Materials"] + [f"- {m}" for m in con.get("materials", [])]
        lines += ["", "### Accessibility"] + [f"- {m}" for m in con.get("accessibility", [])]
        if con.get("safeguards"):
            lines += ["", "### Safeguarding"] + [f"- {m}" for m in con["safeguards"]]
        lines += ["", "### Evidence"] + [f"- [{r}] ({ev[r]['source']}) {ev[r]['label']} — {ev[r]['detail']}"
                                        for r in con.get("evidence_refs", []) if r in ev]
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- static frontend
FRONT = config.ROOT / "frontend"
app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")


NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}  # always serve the latest frontend after an update


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html", headers=NO_CACHE)


@app.get("/{name}.{ext}")
def static_file(name: str, ext: str):
    f = (FRONT / f"{name}.{ext}").resolve()
    if f.parent != FRONT.resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers=NO_CACHE)
