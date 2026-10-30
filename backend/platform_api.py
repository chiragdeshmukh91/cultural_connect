"""HTTP routes: accounts, organisations, events, meeting-place polls, chat, notifications, geocoding, admin review."""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import auth, db, geo, mailer
from . import platform_svc as P
from . import agents
from .auth import client_key, current_user, optional_user, rate_limit, rate_refund

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- models
class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)
    mode: Optional[Literal["individual", "organisation"]] = None


class SigninIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=200)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=1, max_length=200)


class ModeIn(BaseModel):
    mode: Literal["individual", "organisation"]


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    logo_url: str = Field(default="", max_length=400)
    category: str = Field(default="", max_length=60)
    service_area: str = Field(default="", max_length=120)
    contact_kind: Literal["", "email", "phone", "url"] = ""
    contact_value: str = Field(default="", max_length=200)


class EvidenceIn(BaseModel):
    evidence: str = Field(min_length=10, max_length=2000)


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class CodeIn(BaseModel):
    code: str = Field(max_length=100)


class EventIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=5000)
    purpose: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=60)
    starts_at: str = Field(max_length=25)
    ends_at: str = Field(max_length=25)
    timezone: str = Field(max_length=60)
    location_status: Literal["tbc", "confirmed", "online"] = "tbc"
    venue_name: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=300)
    lat: Optional[float] = None
    lon: Optional[float] = None
    geo_source: Literal["", "organiser", "nominatim"] = ""
    online_url: str = Field(default="", max_length=400)
    capacity: int = Field(ge=1, le=5000)
    rsvp_deadline: Optional[str] = Field(default=None, max_length=25)
    cost_note: str = Field(default="", max_length=300)
    materials: str = Field(default="", max_length=1000)
    accessibility: str = Field(default="", max_length=1000)
    requirements: str = Field(default="", max_length=1000)
    min_age: Optional[int] = Field(default=None, ge=0, le=120)
    safety: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=300)
    image_url: str = Field(default="", max_length=400)

    @field_validator("rsvp_deadline")
    @classmethod
    def _dl(cls, v):
        return v or None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class RsvpIn(BaseModel):
    status: Literal["going", "maybe", "not_going"]


class AttendIn(BaseModel):
    user_id: str = Field(max_length=40)
    attended: bool


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class ProgramIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class GroupCircleIn(BaseModel):
    name: str = Field(default="", max_length=80)


class PlaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=3, max_length=300)
    lat: Optional[float] = None
    lon: Optional[float] = None
    url: str = Field(default="", max_length=400)
    cost_note: str = Field(default="", max_length=200)
    accessibility_note: str = Field(default="", max_length=200)


class PlaceVoteIn(BaseModel):
    place_id: int


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    client_id: str = Field(min_length=6, max_length=64)
    thread: str = Field(default="", max_length=60)

    @field_validator("client_id")
    @classmethod
    def _cid(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", v):
            raise ValueError("Invalid client id.")
        return v


class ReportIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ---------------------------------------------------------------- auth
def _bearer(authorization: Optional[str]) -> Optional[str]:
    return authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None


@router.post("/auth/signup")
def signup(body: SignupIn, request: Request):
    key = "signup:" + client_key(request)
    rate_limit(key, 10, 3600)
    try:
        return auth.signup(body.email, body.password, body.mode)
    except HTTPException as e:
        if e.status_code in (400, 422):   # weak password / invalid email: don't burn the quota
            rate_refund(key)
        raise


@router.post("/auth/signin")
def signin(body: SigninIn, request: Request):
    rate_limit("signin:" + client_key(request), 20, 900)
    rate_limit("signin-email:" + body.email.strip().lower(), 10, 900)
    return auth.signin(body.email, body.password)


@router.post("/auth/signout")
def signout(authorization: Optional[str] = Header(default=None)):
    auth.signout(_bearer(authorization))
    return {"ok": True}


@router.post("/auth/forgot")
def forgot(body: EmailIn, request: Request):
    rate_limit("forgot:" + client_key(request), 5, 3600)
    auth.forgot(body.email)
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent.",
            "email_configured": mailer.enabled()}


@router.post("/auth/reset")
def reset(body: ResetIn, request: Request):
    rate_limit("reset:" + client_key(request), 10, 3600)
    return auth.reset(body.token, body.password)


@router.post("/auth/verify")
def verify(body: TokenIn):
    return auth.verify_email(body.token)


@router.post("/auth/resend-verification")
def resend(uid: str = Depends(current_user)):
    rate_limit("resend:" + uid, 3, 3600)
    auth.resend_verification(uid)
    return {"ok": True, "email_configured": mailer.enabled()}


@router.post("/auth/claim")
def claim(body: SigninIn, uid: str = Depends(current_user)):
    return auth.claim(uid, body.email, body.password)


@router.post("/auth/password")
def password(body: PasswordIn, uid: str = Depends(current_user)):
    auth.change_password(uid, body.current, body.new)
    return {"ok": True}


@router.put("/auth/mode")
def mode(body: ModeIn, uid: str = Depends(current_user)):
    auth.set_mode(uid, body.mode)
    return {"ok": True}


@router.get("/auth/me")
def me(uid: str = Depends(current_user)):
    acct = auth.account_of(uid)
    with db.read() as c:
        prof = c.execute("SELECT alias, discoverable FROM profiles WHERE user_id = ?", (uid,)).fetchone()
    return {"user_id": uid, "account": acct, "legacy": acct is None, "has_profile": bool(prof),
            "alias": prof["alias"] if prof else None, "orgs": P.my_orgs(uid), "is_admin": auth.is_admin(uid),
            "email_configured": mailer.enabled(), "geocoder": geo.enabled()}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(uid: str = Depends(current_user)):
    return P.list_notifications(uid)


@router.get("/notifications/unread")
def unread(uid: str = Depends(current_user)):
    return {"unread": P.unread_count(uid)}


@router.post("/notifications/read")
def read_all(nid: Optional[int] = None, uid: str = Depends(current_user)):
    P.mark_read(uid, nid)
    return {"ok": True}


# ---------------------------------------------------------------- organisations
@router.get("/orgs")
def orgs(q: str = ""):
    return P.list_orgs(q[:60])


@router.post("/orgs")
def create_org(body: OrgIn, uid: str = Depends(current_user)):
    key = "org-create:" + uid
    rate_limit(key, 10, 3600)
    try:
        return P.create_org(uid, body.model_dump())
    except HTTPException as e:
        if e.status_code in (400, 422):   # invalid contact/link: don't burn the quota
            rate_refund(key)
        raise


@router.get("/me/orgs")
def my_orgs(uid: str = Depends(current_user)):
    return P.my_orgs(uid)


@router.get("/orgs/{ref}")
def org(ref: str, uid: Optional[str] = Depends(optional_user)):
    return P.org_detail(ref, uid)


@router.put("/orgs/{oid}")
def update_org(oid: str, body: OrgIn, uid: str = Depends(current_user)):
    return P.update_org(uid, oid, body.model_dump())


@router.get("/orgs/{oid}/dashboard")
def dashboard(oid: str, uid: str = Depends(current_user)):
    return P.dashboard(uid, oid)


@router.post("/orgs/{oid}/verification")
def request_verification(oid: str, body: EvidenceIn, uid: str = Depends(current_user)):
    return P.request_verification(uid, oid, body.evidence)


@router.get("/orgs/{oid}/team")
def team(oid: str, uid: str = Depends(current_user)):
    return P.team(uid, oid)


@router.post("/orgs/{oid}/invites")
def staff_invite(oid: str, uid: str = Depends(current_user)):
    rate_limit("invite:" + uid, 10, 3600)
    return P.create_staff_invite(uid, oid)


@router.post("/org-invites/accept")
def accept_invite(body: CodeIn, uid: str = Depends(current_user)):
    rate_limit("invite-accept:" + uid, 10, 3600)
    return P.accept_staff_invite(uid, body.code)


@router.delete("/orgs/{oid}/team/{target}")
def remove_staff(oid: str, target: str, uid: str = Depends(current_user)):
    return P.remove_staff(uid, oid, target)


@router.get("/orgs/{oid}/programs")
def org_programs(oid: str, uid: str = Depends(current_user)):
    return P.org_programs(uid, oid)


@router.post("/orgs/{oid}/programs")
def org_new_program(oid: str, body: ProgramIn, uid: str = Depends(current_user)):
    return P.create_org_program(uid, oid, body.name)


@router.post("/orgs/{oid}/programs/{pid}/groups/{gid}/circle")
def group_circle(oid: str, pid: str, gid: str, body: GroupCircleIn, uid: str = Depends(current_user)):
    return P.circle_from_group(uid, oid, pid, gid, body.name)


@router.post("/orgs/{oid}/events")
def create_event(oid: str, body: EventIn, uid: str = Depends(current_user)):
    rate_limit("event-create:" + uid, 30, 3600)
    return P.create_org_event(uid, oid, body.model_dump(exclude={"reason"}))


@router.get("/admin/verifications")
def admin_queue(uid: str = Depends(current_user)):
    return P.admin_queue(uid)


@router.post("/admin/verifications/{oid}")
def admin_review(oid: str, body: ReviewIn, uid: str = Depends(current_user)):
    return P.admin_review(uid, oid, body.decision, body.note)


# ---------------------------------------------------------------- events
@router.get("/events")
def events(q: str = "", area: str = ""):
    return P.public_events(q[:60], area[:60])


@router.get("/me/activities")
def activities(uid: str = Depends(current_user)):
    return P.my_activities(uid)


@router.get("/events/{eid}")
def event(eid: str, uid: Optional[str] = Depends(optional_user)):
    return P.get_event(eid, uid)


@router.put("/events/{eid}")
def update_event(eid: str, body: EventIn, uid: str = Depends(current_user)):
    out = P.update_event(uid, eid, body.model_dump(exclude={"reason"}), body.reason)
    agents.on_event_changed(eid, "an event changed")
    return out


@router.post("/events/{eid}/publish")
def publish(eid: str, uid: str = Depends(current_user)):
    out = P.publish_event(uid, eid)
    agents.on_event_changed(eid, "a new event matching your interests was published")
    return out


@router.post("/events/{eid}/cancel")
def cancel(eid: str, body: ReasonIn, uid: str = Depends(current_user)):
    out = P.cancel_event_v(uid, eid, body.reason)
    agents.on_event_changed(eid, "an event was cancelled")
    return out


@router.post("/events/{eid}/complete")
def complete(eid: str, uid: str = Depends(current_user)):
    out = P.complete_event(uid, eid)
    agents.on_event_changed(eid, "an event was completed")
    return out


@router.post("/events/{eid}/rsvp")
def rsvp(eid: str, body: RsvpIn, uid: str = Depends(current_user)):
    rate_limit("rsvp:" + uid, 30)
    out = P.rsvp_v(uid, eid, body.status)
    agents.refresh_user(uid, "you RSVP'd to an event")
    if out.get("display_status") == "full" or out.get("going", 0) >= out.get("capacity", 10 ** 9):
        agents.on_event_changed(eid, "an event filled up")
    return out


@router.get("/events/{eid}/participants")
def participants(eid: str, uid: str = Depends(current_user)):
    return P.participants(uid, eid)


@router.post("/events/{eid}/attendance")
def attendance(eid: str, body: AttendIn, uid: str = Depends(current_user)):
    return P.mark_attendance(uid, eid, body.user_id, body.attended)


@router.post("/events/{eid}/feedback")
def event_feedback(eid: str, body: FeedbackIn, uid: str = Depends(current_user)):
    out = P.feedback(uid, eid, body.rating, body.comment)
    agents.refresh_user(uid, "you gave event feedback")
    return out


# ---------------------------------------------------------------- meeting places + geocoding
@router.get("/geo/search")
def geo_search(q: str, uid: str = Depends(current_user)):
    rate_limit("geo:" + uid, 20)
    return geo.search(q)


@router.get("/proposals/{pid}/places")
def places(pid: str, uid: str = Depends(current_user)):
    return P.places(uid, pid)


@router.post("/proposals/{pid}/places")
def add_place(pid: str, body: PlaceIn, uid: str = Depends(current_user)):
    rate_limit("place:" + uid, 20, 3600)
    return P.add_place(uid, pid, body.model_dump())


@router.post("/proposals/{pid}/places/vote")
def vote_place(pid: str, body: PlaceVoteIn, uid: str = Depends(current_user)):
    return P.vote_place(uid, pid, body.place_id)


# ---------------------------------------------------------------- chat
@router.get("/circles/{cid}/messages")
def messages(cid: str, thread: str = "", after: Optional[int] = None, before: Optional[int] = None, limit: int = 40,
             uid: str = Depends(current_user)):
    return P.messages(uid, cid, thread[:60], after, before, limit)


@router.post("/circles/{cid}/messages")
def send(cid: str, body: MessageIn, uid: str = Depends(current_user)):
    rate_limit("chat:" + uid, 20)
    return P.send_message(uid, cid, body.body, body.client_id, body.thread)


@router.delete("/circles/{cid}/messages/{mid}")
def delete_message(cid: str, mid: int, uid: str = Depends(current_user)):
    return P.delete_message(uid, cid, mid)


@router.post("/circles/{cid}/messages/{mid}/report")
def report_message(cid: str, mid: int, body: ReportIn, uid: str = Depends(current_user)):
    rate_limit("report:" + uid, 10)
    return P.report_message(uid, cid, mid, body.reason)
