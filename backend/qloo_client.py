"""Thin, safe HTTP client for the Qloo API.

* Only the backend talks to Qloo; the key never leaves the server.
* Every call is recorded in an audit trail (path, params, status, timing) WITHOUT the key,
  so the UI can show judges exactly which real Qloo requests produced each piece of evidence.
* Small in-memory TTL cache + bounded retries for 429/5xx.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests

from . import config


class QlooError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
AUDIT: deque = deque(maxlen=300)
_session = requests.Session()


def _key(method: str, path: str, params: Any) -> str:
    raw = json.dumps([method, path, params], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def _clean(params: dict) -> dict:
    out = {}
    for k, v in (params or {}).items():
        if v is None or v == "" or v == []:
            continue
        out[k] = ",".join(map(str, v)) if isinstance(v, (list, tuple)) else v
    return out


_inflight: dict[str, threading.Lock] = {}


def request(method: str, path: str, params: dict | None = None, body: dict | None = None,
            use_cache: bool = True) -> dict:
    """Identical concurrent requests are de-duplicated: the first caller fetches, the rest wait and reuse the cache."""
    if not use_cache:
        return _request(method, path, params, body, use_cache)
    ck = _key(method, path, [_clean(params or {}), body])
    with _lock:
        lk = _inflight.setdefault(ck, threading.Lock())
    with lk:
        try:
            return _request(method, path, params, body, use_cache)
        finally:
            with _lock:
                if len(_inflight) > 2000:
                    _inflight.clear()


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None,
             use_cache: bool = True) -> dict:
    if not config.QLOO_API_KEY:
        raise QlooError("QLOO_API_KEY is not set. Add it to the .env file in the project root.", 500)
    params = _clean(params or {})
    ck = _key(method, path, [params, body])
    now = time.time()
    if use_cache:
        with _lock:
            hit = _cache.get(ck)
        if hit and now - hit[0] < config.QLOO_CACHE_TTL:
            AUDIT.appendleft({"path": path, "params": params, "body": body, "status": "cache",
                              "ms": 0, "at": datetime.now(timezone.utc).isoformat()})
            return hit[1]

    url = f"{config.QLOO_BASE_URL}{path}"
    headers = {"X-Api-Key": config.QLOO_API_KEY, "Accept": "application/json"}
    last_err: QlooError | None = None
    for attempt in range(config.QLOO_MAX_RETRIES + 1):
        t0 = time.time()
        try:
            resp = _session.request(method, url, params=params, json=body, headers=headers,
                                    timeout=config.QLOO_TIMEOUT)
        except requests.RequestException as exc:
            last_err = QlooError(f"Network error calling Qloo: {type(exc).__name__}", 503)
            _audit(path, params, body, "network-error", t0)
            time.sleep(0.6 * (attempt + 1))
            continue
        _audit(path, params, body, resp.status_code, t0)
        if resp.status_code == 429 or resp.status_code >= 500:
            last_err = QlooError(f"Qloo HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            time.sleep(1.0 * (attempt + 1))
            continue
        if resp.status_code == 404:
            data = {"results": [], "_empty": True}
        elif not resp.ok:
            raise QlooError(f"Qloo HTTP {resp.status_code}: {resp.text[:400]}", resp.status_code)
        else:
            try:
                data = resp.json()
            except ValueError:
                raise QlooError("Qloo returned non-JSON content", 502)
        if use_cache:
            with _lock:
                _cache[ck] = (time.time(), data)
        return data
    raise last_err or QlooError("Qloo request failed", 503)


def _audit(path, params, body, status, t0):
    AUDIT.appendleft({"path": path, "params": params, "body": body, "status": status,
                      "ms": int((time.time() - t0) * 1000), "at": datetime.now(timezone.utc).isoformat()})


def get(path: str, params: dict | None = None, use_cache: bool = True) -> dict:
    return request("GET", path, params=params, use_cache=use_cache)


def post(path: str, body: dict, params: dict | None = None) -> dict:
    return request("POST", path, params=params, body=body)
