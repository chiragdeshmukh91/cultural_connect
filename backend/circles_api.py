"""HTTP routes for individuals and Circles. All authorization is enforced in circles.py on the server."""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from . import agents
from . import circles as svc
from .auth import current_user, optional_user, rate_limit

router = APIRouter(prefix="/api")

Intent = Literal["enjoy", "teach", "learn", "discuss", "collaborate"]


class SignalIn(BaseModel):
    id: str = Field(max_length=200)
    kind: Optional[str] = None


class InterestIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    intent: Intent = "enjoy"
    category: Optional[str] = Field(default=None, max_length=60)
    signals: List[SignalIn] = Field(default_factory=list, max_length=4)


def _clean_list(v, allowed):
    return [x for x in dict.fromkeys(v or []) if x in allowed]


class ProfileIn(BaseModel):
    alias: str = Field(min_length=2, max_length=40)
    area: str = Field(default="", max_length=60)
    show_area: bool = False
    share_interests: bool = False
    bio: str = Field(default="", max_length=280)
    language: str = Field(default="", max_length=30)
    budget_max: Optional[float] = Field(default=None, ge=0, le=10000)
    availability: List[str] = Field(default_factory=list)
    activity_prefs: List[str] = Field(default_factory=list)
    accessibility: List[str] = Field(default_factory=list)
    exclude_topics: List[str] = Field(default_factory=list, max_length=10)
    interests: List[InterestIn] = Field(min_length=1, max_length=12)
    adult_confirmed: bool
    discoverable: bool
    avatar_url: Optional[str] = Field(default=None, max_length=400)  # path from POST /api/uploads; None = unchanged
    timezone: str = Field(default="", max_length=60)  # browser IANA zone, used to schedule agent-drafted activities

    @field_validator("adult_confirmed")
    @classmethod
    def _adult(cls, v):
        if not v:
            raise ValueError("Self-serve Circles are for adults (18+). Under-18s can take part through an organization.")
        return v

    @field_validator("availability")
    @classmethod
    def _av(cls, v):
        return _clean_list(v, svc.AVAIL)

    @field_validator("activity_prefs")
    @classmethod
    def _pr(cls, v):
        return _clean_list(v, svc.PREFS)

    @field_validator("accessibility")
    @classmethod
    def _ac(cls, v):
        return _clean_list(v, svc.ACCESS)

    @field_validator("exclude_topics")
    @classmethod
    def _ex(cls, v):
        return [x.strip()[:40] for x in v if x and x.strip()]

    @field_validator("alias")
    @classmethod
    def _al(cls, v):
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Alias must be at least 2 characters.")
        return v


class ConsentIn(BaseModel):
    discoverable: bool


class CircleIn(BaseModel):
    interest_id: int
    name: str = Field(min_length=3, max_length=80)
    purpose: str = Field(default="", max_length=400)
    category: Optional[Literal["general", "health", "political"]] = None
    visibility: Literal["public", "private"] = "public"
    meeting_mode: Literal["in_person", "online", "either"] = "either"
    area: Optional[str] = Field(default=None, max_length=60)
    language: str = Field(default="", max_length=30)
    intents: List[Intent] = Field(default_factory=list)
    accessibility: List[str] = Field(default_factory=lambda: ["flexible_participation"])
    capacity: int = Field(default=12, ge=3, le=50)
    min_size: int = Field(default=3, ge=2, le=10)
    member_events: bool = True
    image_url: str = Field(default="", max_length=400)

    @field_validator("accessibility")
    @classmethod
    def _ac(cls, v):
        return _clean_list(v, svc.ACCESS)


class CircleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=80)
    purpose: Optional[str] = Field(default=None, max_length=400)
    category: Optional[Literal["general", "health", "political"]] = None
    capacity: Optional[int] = Field(default=None, ge=3, le=50)
    min_size: Optional[int] = Field(default=None, ge=2, le=10)
    member_events: Optional[bool] = None
    accessibility: Optional[List[str]] = None
    language: Optional[str] = Field(default=None, max_length=30)
    image_url: Optional[str] = Field(default=None, max_length=400)


class MemberAction(BaseModel):
    action: Literal["approve", "decline", "remove", "make_moderator", "make_member"]


class PostIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: Optional[int] = None


class PostEdit(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class HideIn(BaseModel):
    hidden: bool = True


class ReportIn(BaseModel):
    target_type: Literal["post", "user"]
    target_id: str = Field(max_length=40)
    reason: str = Field(min_length=3, max_length=500)


class BlockIn(BaseModel):
    user_id: str = Field(max_length=40)
    blocked: bool = True


class EventIn(BaseModel):
    title: str = Field(default="", max_length=100)
    duration_min: int = Field(ge=15, le=480)
    budget: float = Field(ge=0, le=10000)
    currency: str = Field(default="USD", max_length=8)
    setting: Literal["any", "indoor", "outdoor", "online"] = "any"
    time_options: List[str] = Field(default_factory=list, max_length=3)
    capacity: Optional[int] = Field(default=None, ge=2, le=50)
    location_note: str = Field(default="", max_length=200)


class VoteIn(BaseModel):
    kind: Literal["activity", "time"]
    choice: int = Field(ge=0, le=5)


class ConfirmIn(BaseModel):
    option: int = Field(ge=0, le=5)
    time_index: Optional[int] = Field(default=None, ge=0, le=5)
    location_note: Optional[str] = Field(default=None, max_length=200)
    place_id: Optional[int] = None
    timezone: str = Field(default="UTC", max_length=60)


class RsvpIn(BaseModel):
    status: Literal["going", "maybe", "not_going"]


# ---------------------------------------------------------------- me / profile
@router.post("/me")
def create_me(body: ProfileIn, uid: str = Depends(current_user)):
    """Create the individual profile for the signed-in account (accounts are created via /api/auth/signup)."""
    rate_limit("profile:" + uid, 20)
    out = svc.save_profile(uid, body.model_dump())
    out["agent_run"] = agents.on_profile_saved(uid, "onboarding completed")  # automatic Qloo discovery, no manual search
    return out


@router.get("/me")
def read_me(uid: str = Depends(current_user)):
    return svc.get_profile(uid)


@router.put("/me")
def update_me(body: ProfileIn, uid: str = Depends(current_user)):
    rate_limit("profile:" + uid, 20)
    out = svc.save_profile(uid, body.model_dump())
    out["agent_run"] = agents.on_profile_saved(uid, "preferences changed")
    return out


@router.put("/me/consent")
def consent(body: ConsentIn, uid: str = Depends(current_user)):
    out = svc.set_discovery(uid, body.discoverable)
    agents.on_profile_saved(uid, "discovery consent turned on")
    return out


@router.delete("/me")
def delete_me(uid: str = Depends(current_user)):
    return svc.delete_account(uid)


@router.get("/me/circles")
def my_circles(uid: str = Depends(current_user)):
    return svc.my_circles(uid)


@router.get("/me/events")
def my_events(uid: str = Depends(current_user)):
    return svc.my_events(uid)


@router.get("/me/blocks")
def my_blocks(uid: str = Depends(current_user)):
    return svc.my_blocks(uid)


@router.post("/me/blocks")
def set_block(body: BlockIn, uid: str = Depends(current_user)):
    return svc.block(uid, body.user_id, body.blocked)


# ---------------------------------------------------------------- discovery
@router.get("/circles/recommendations")
def recommendations(uid: str = Depends(current_user)):
    rate_limit("rec:" + uid, 20)
    return svc.recommend(uid)


@router.get("/circles")
def browse(q: str = "", category: str = "", uid: Optional[str] = Depends(optional_user)):
    return svc.browse(q[:60], category[:20], uid)


@router.post("/circles")
def create_circle(body: CircleIn, uid: str = Depends(current_user)):
    rate_limit("create-circle:" + uid, 5, 3600)
    out = svc.create_circle(uid, body.model_dump())
    agents.on_circle_changed(out["id"], "a new Circle matching your interests was created")
    return out


@router.get("/circles/{cid}")
def circle(cid: str, invite: Optional[str] = None, uid: Optional[str] = Depends(optional_user)):
    return svc.circle_detail(cid, uid, (invite or "")[:40] or None)


@router.patch("/circles/{cid}")
def edit_circle(cid: str, body: CircleUpdate, uid: str = Depends(current_user)):
    out = svc.update_circle(uid, cid, body.model_dump(exclude_none=True))
    agents.on_circle_changed(cid, "a Circle matching your interests was updated")  # cached re-rank, no new Qloo call
    return out


@router.post("/circles/{cid}/join")
def join(cid: str, invite: Optional[str] = None, uid: str = Depends(current_user)):
    rate_limit("join:" + uid, 20)
    out = svc.join(uid, cid, (invite or "")[:40] or None)
    agents.on_membership_changed(cid, "a member joined")
    agents.refresh_user(uid, "you joined or requested to join a Circle")
    return out


@router.post("/circles/{cid}/leave")
def leave(cid: str, uid: str = Depends(current_user)):
    out = svc.leave(uid, cid)
    agents.refresh_user(uid, "you left a Circle")
    return out


@router.get("/circles/{cid}/members")
def members(cid: str, uid: str = Depends(current_user)):
    return svc.members(uid, cid)


@router.post("/circles/{cid}/members/{target}")
def member_action(cid: str, target: str, body: MemberAction, uid: str = Depends(current_user)):
    out = svc.moderate_member(uid, cid, target, body.action)
    agents.on_membership_changed(cid, f"moderator action: {body.action}")
    return out


# ---------------------------------------------------------------- discussion
@router.get("/circles/{cid}/posts")
def posts(cid: str, before: Optional[int] = None, limit: int = 20, uid: str = Depends(current_user)):
    return svc.list_posts(uid, cid, before, limit)


@router.post("/circles/{cid}/posts")
def new_post(cid: str, body: PostIn, uid: str = Depends(current_user)):
    rate_limit("post:" + uid, 8)
    return svc.create_post(uid, cid, body.body, body.parent_id)


@router.patch("/circles/{cid}/posts/{pid}")
def edit_post(cid: str, pid: int, body: PostEdit, uid: str = Depends(current_user)):
    rate_limit("post:" + uid, 8)
    return svc.edit_post(uid, cid, pid, body.body)


@router.delete("/circles/{cid}/posts/{pid}")
def del_post(cid: str, pid: int, uid: str = Depends(current_user)):
    return svc.delete_post(uid, cid, pid)


@router.post("/circles/{cid}/posts/{pid}/hide")
def hide_post(cid: str, pid: int, body: HideIn, uid: str = Depends(current_user)):
    return svc.hide_post(uid, cid, pid, body.hidden)


@router.post("/circles/{cid}/reports")
def report(cid: str, body: ReportIn, uid: str = Depends(current_user)):
    rate_limit("report:" + uid, 10)
    return svc.report(uid, cid, body.target_type, body.target_id, body.reason)


@router.get("/circles/{cid}/reports")
def reports(cid: str, uid: str = Depends(current_user)):
    return svc.list_reports(uid, cid)


@router.post("/circles/{cid}/reports/{rid}/resolve")
def resolve_report(cid: str, rid: int, uid: str = Depends(current_user)):
    return svc.resolve_report(uid, cid, rid)


# ---------------------------------------------------------------- member-led events
@router.get("/circles/{cid}/events")
def circle_events(cid: str, uid: str = Depends(current_user)):
    return svc.list_events(uid, cid)


@router.post("/circles/{cid}/events")
def propose(cid: str, body: EventIn, uid: str = Depends(current_user)):
    rate_limit("propose:" + uid, 6, 3600)
    return svc.propose_event(uid, cid, body.model_dump())


@router.get("/circle-events/{eid}")
def event(eid: str, uid: str = Depends(current_user)):
    return svc.get_event(uid, eid)


@router.post("/circle-events/{eid}/vote")
def vote(eid: str, body: VoteIn, uid: str = Depends(current_user)):
    out = svc.vote(uid, eid, body.kind, body.choice)
    agents.after_vote(eid)
    return out


@router.post("/circle-events/{eid}/confirm")
def confirm(eid: str, body: ConfirmIn, uid: str = Depends(current_user)):
    out = svc.confirm_event(uid, eid, body.option, body.time_index, body.location_note, body.place_id, body.timezone)
    if out.get("event_id"):
        agents.on_event_changed(out["event_id"], "a new event matching your interests was published")
    return out


@router.post("/circle-events/{eid}/cancel")
def cancel(eid: str, uid: str = Depends(current_user)):
    return svc.cancel_event(uid, eid)


@router.post("/circle-events/{eid}/rsvp")
def rsvp(eid: str, body: RsvpIn, uid: str = Depends(current_user)):
    return svc.rsvp(uid, eid, body.status)
