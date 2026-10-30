"""Optional geocoding for meeting places via OpenStreetMap Nominatim (no API key; usage policy requires a
contact email, a real User-Agent, and at most ~1 request/second). Disabled unless GEOCODER=nominatim.

Results are remembered for a while so the server can confirm that coordinates labelled "nominatim" really
came from a geocoder response — clients cannot attach a fake map pin to a place.
A geocoder result proves only that an address string matched a map location. It says nothing about
whether a venue is open, safe, available or approved for an activity.
"""
from __future__ import annotations

import threading
import time

import requests
from fastapi import HTTPException

from . import config

_seen: dict[tuple, float] = {}
_lock = threading.Lock()
_last = [0.0]


def enabled() -> bool:
    return config.GEOCODER == "nominatim" and bool(config.NOMINATIM_EMAIL)


def search(q: str) -> list[dict]:
    if not enabled():
        raise HTTPException(501, "Map search isn't configured on this server. Enter the address manually — it will be shown without a map pin.")
    q = (q or "").strip()[:200]
    if len(q) < 3:
        raise HTTPException(422, "Type at least 3 characters.")
    with _lock:
        wait = 1.05 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    try:
        r = requests.get(f"{config.NOMINATIM_URL}/search", timeout=10,
                         params={"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 0, "email": config.NOMINATIM_EMAIL},
                         headers={"User-Agent": f"CultureConnect/1.0 ({config.NOMINATIM_EMAIL})"})
    except requests.RequestException:
        raise HTTPException(503, "The map service didn't respond. Try again, or enter the address manually.")
    if r.status_code == 429:
        raise HTTPException(429, "The map service is rate-limiting us. Try again in a minute.")
    if not r.ok:
        raise HTTPException(502, f"Map service error ({r.status_code}).")
    out = []
    for x in r.json()[:5]:
        try:
            lat, lon = round(float(x["lat"]), 6), round(float(x["lon"]), 6)
        except (KeyError, ValueError):
            continue
        name = x.get("display_name", "")
        out.append({"display_name": name, "lat": lat, "lon": lon, "osm_type": x.get("osm_type"), "osm_id": x.get("osm_id")})
        with _lock:
            _seen[(lat, lon)] = time.time()
    return out


def came_from_geocoder(lat, lon) -> bool:
    if lat is None or lon is None:
        return False
    with _lock:
        t = _seen.get((round(float(lat), 6), round(float(lon), 6)))
    return bool(t and time.time() - t < 6 * 3600)


def remember(lat: float, lon: float):  # test hook
    with _lock:
        _seen[(round(lat, 6), round(lon, 6))] = time.time()
