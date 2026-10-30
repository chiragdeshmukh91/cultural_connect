"""Image uploads (profile pictures, Circle / event photos, organisation logos).

* Signed-in users only, rate-limited, max UPLOAD_MAX_BYTES.
* The file type is decided from the file's own bytes (PNG, JPEG, WebP, GIF) — never from the name or the
  client's Content-Type — and SVG is refused (it can carry scripts).
* Stored under UPLOAD_DIR with a random name; served from /uploads/<name> with nosniff + long cache.
"""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from . import config
from .auth import current_user, rate_limit

router = APIRouter()
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
PATH_RE = re.compile(r"^/uploads/[0-9a-f]{32}\.(png|jpg|webp|gif)$")
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def media_url(u: str | None, allow_https: bool = False) -> str:
    """Accept '' or a path returned by POST /api/uploads (and, if allowed, an https link). Raises 422 otherwise."""
    u = (u or "").strip()
    if not u or PATH_RE.match(u):
        if u and not (config.UPLOAD_DIR / u.rsplit("/", 1)[1]).exists():
            raise HTTPException(422, "That photo was not found — upload it again.")
        return u
    if allow_https and re.match(r"^https://[^\s\"'<>]+$", u) and len(u) <= 400:
        return u
    raise HTTPException(422, "Upload a photo (PNG, JPEG, WebP or GIF)" + (" or use an https:// link." if allow_https else "."))


@router.post("/api/uploads")
async def upload(request: Request, uid: str = Depends(current_user)):
    rate_limit("upload:" + uid, 30, 3600)
    size = int(request.headers.get("content-length") or 0)
    if size > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, f"Photos can be at most {config.UPLOAD_MAX_BYTES // (1024 * 1024)} MB.")
    data = await request.body()
    if not data:
        raise HTTPException(400, "No file received.")
    if len(data) > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, f"Photos can be at most {config.UPLOAD_MAX_BYTES // (1024 * 1024)} MB.")
    ext = sniff(data)
    if not ext:
        raise HTTPException(415, "Only PNG, JPEG, WebP or GIF images can be uploaded.")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{ext}"
    (config.UPLOAD_DIR / name).write_bytes(data)
    return {"url": f"/uploads/{name}", "bytes": len(data), "type": MEDIA[ext]}


@router.get("/uploads/{name}")
def serve(name: str):
    if not NAME_RE.match(name):
        raise HTTPException(404)
    f = config.UPLOAD_DIR / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type=MEDIA[name.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
