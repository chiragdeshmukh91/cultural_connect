"""Agent Activity Centre API. Every route checks the caller's permissions on the server (agents.py)."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import agents
from .auth import current_user, rate_limit

router = APIRouter(prefix="/api/agent")


class SettingsIn(BaseModel):
    automation: Optional[bool] = None
    circle_invites: Optional[bool] = None
    email_notify: Optional[bool] = None


class CircleSettingsIn(BaseModel):
    auto_plan: Optional[bool] = None
    approval_policy: Optional[Literal["host", "auto"]] = None


class ApproveIn(BaseModel):
    timezone: Optional[str] = Field(default=None, max_length=60)


@router.get("/summary")
def summary(uid: str = Depends(current_user)):
    return agents.summary(uid)


@router.get("/settings")
def get_settings(uid: str = Depends(current_user)):
    from . import db
    with db.read() as c:
        return agents.get_settings(c, uid)


@router.put("/settings")
def put_settings(body: SettingsIn, uid: str = Depends(current_user)):
    return agents.put_settings(uid, body.model_dump())


@router.get("/runs")
def runs(limit: int = 30, uid: str = Depends(current_user)):
    return agents.list_runs(uid, limit)


@router.get("/runs/{rid}")
def run(rid: str, uid: str = Depends(current_user)):
    return agents.run_detail(uid, rid)


@router.post("/runs/{rid}/{action}")
def control(rid: str, action: Literal["pause", "resume", "retry", "cancel"], uid: str = Depends(current_user)):
    rate_limit("agent-ctl:" + uid, 30)
    return agents.control_run(uid, rid, action)


@router.get("/discovery")
def discovery(uid: str = Depends(current_user)):
    return {"result": agents.discovery(uid), "status": agents.discovery_status(uid)}


class FeedbackIn(BaseModel):
    item_type: Literal["circle", "event", "interest"]
    item_id: str = Field(min_length=1, max_length=200)
    action: Literal["saved", "dismissed", "clear"]


@router.post("/feedback")
def feedback(body: FeedbackIn, uid: str = Depends(current_user)):
    rate_limit("agent-feedback:" + uid, 60, 3600)
    return agents.record_feedback(uid, body.item_type, body.item_id, body.action)


@router.post("/discovery/refresh")
def refresh(uid: str = Depends(current_user)):
    rate_limit("agent-refresh:" + uid, 6, 3600)  # respects the Qloo hackathon quota
    rid = agents.on_profile_saved(uid, "refresh requested", force=True)
    return {"run_id": rid, "queued": bool(rid),
            "message": None if rid else "Turn on discovery consent in Profile & Privacy first."}


@router.get("/invites")
def invites(uid: str = Depends(current_user)):
    return agents.my_invites(uid)


@router.post("/invites/{pid}/{action}")
def respond(pid: str, action: Literal["accept", "decline", "withdraw"], uid: str = Depends(current_user)):
    rate_limit("agent-invite:" + uid, 30)
    return agents.respond_invite(uid, pid, action)


@router.get("/approvals")
def approvals(uid: str = Depends(current_user)):
    return agents.approvals(uid)


@router.post("/approvals/{pid}/approve")
def approve(pid: str, body: ApproveIn, uid: str = Depends(current_user)):
    out = agents.approve(uid, pid, body.timezone)
    if out.get("event_id"):
        agents.on_event_changed(out["event_id"], "a new event matching your interests was published")
    return out


@router.post("/proposals/{pid}/approve-now")
def approve_now(pid: str, body: ApproveIn, uid: str = Depends(current_user)):
    return agents.approve_now(uid, pid, body.timezone)


@router.post("/approvals/{pid}/reject")
def reject(pid: str, uid: str = Depends(current_user)):
    return agents.reject(uid, pid)


@router.post("/circles/{cid}/plan")
def plan_now(cid: str, uid: str = Depends(current_user)):
    from . import db
    rate_limit("agent-plan:" + uid, 6, 3600)
    with db.read() as c:
        if not agents._is_circle_mod(c, cid, uid):
            from fastapi import HTTPException
            raise HTTPException(403, "Only a host or moderator can start planning.")
    rid = agents.on_membership_changed(cid, "host asked the agent to plan", force=True)
    return {"run_id": rid, "queued": bool(rid),
            "message": None if rid else "Not started: the Circle needs its minimum number of members and no open agent draft."}


@router.put("/circles/{cid}/settings")
def circle_settings(cid: str, body: CircleSettingsIn, uid: str = Depends(current_user)):
    return agents.circle_settings(uid, cid, body.model_dump())
