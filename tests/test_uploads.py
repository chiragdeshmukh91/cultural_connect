"""Photo uploads: type sniffing, size limit, auth, and use as profile picture / event / Circle / organisation images."""
from backend import config
from tests.test_circles import account, client, make_circle, profile
from tests.test_platform import event_body, make_org

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 64


def up(h, data, ctype="image/png"):
    return client.post("/api/uploads", content=data, headers={**h, "Content-Type": ctype})


def test_upload_rules_and_serving():
    h = account()
    assert client.post("/api/uploads", content=PNG, headers={"Content-Type": "image/png"}).status_code == 401
    assert up(h, b"<svg onload=alert(1)></svg>", "image/svg+xml").status_code == 415   # SVG refused
    assert up(h, b"GIF89a" + b"\0" * 10, "image/png").status_code == 200              # type comes from the bytes
    assert up(h, b"\xff\xd8\xff" + b"\0" * (config.UPLOAD_MAX_BYTES + 1)).status_code == 413
    r = up(h, JPG, "application/octet-stream")
    assert r.status_code == 200 and r.json()["url"].endswith(".jpg")
    got = client.get(r.json()["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and got.content == JPG
    assert client.get("/uploads/../.env").status_code == 404
    assert client.get("/uploads/0123456789abcdef0123456789abcdef.png").status_code == 404


def test_photos_on_profile_circle_event_and_org():
    h = account()
    url = up(h, PNG).json()["url"]
    body = profile("Photo", [("Chess", "teach")], avatar_url=url)
    p = client.post("/api/me", json=body, headers=h).json()
    assert p["profile"]["avatar_url"] == url
    assert client.put("/api/me", json={**body, "avatar_url": "https://evil.example/x.png"}, headers=h).status_code == 422
    body.pop("avatar_url")
    p = client.put("/api/me", json=body, headers=h).json()
    assert p["profile"]["avatar_url"] == url   # omitted = unchanged

    r = make_circle(h, p, "Chess", image_url=url)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["image_url"] == url
    members = client.get(f"/api/circles/{c['id']}/members", headers=h).json()["members"]
    assert members[0]["avatar_url"] == url

    org = make_org(h, logo_url=url)
    assert org["logo_url"] == url
    assert client.post("/api/orgs", json={"name": "Bad logo", "logo_url": "/uploads/nothere.png"}, headers=h).status_code == 422
    ev = client.post(f"/api/orgs/{org['id']}/events", json=event_body(image_url=url), headers=h).json()
    assert ev["image_url"] == url
    assert client.post(f"/api/orgs/{org['id']}/events", json=event_body(image_url="javascript:x"), headers=h).status_code == 422
