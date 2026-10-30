import os
import tempfile

# Configure an isolated environment BEFORE any backend module is imported.
_tmp = tempfile.mkdtemp(prefix="cc-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "boot.db")
os.environ["QLOO_API_KEY"] = "test-key-not-real"
os.environ["QLOO_BASE_URL"] = "http://127.0.0.1:9"  # unroutable: any un-faked Qloo call fails loudly
os.environ["LLM_PROVIDER"] = "none"
os.environ["AGENT_WORKER"] = "0"  # tests drive the job queue synchronously (jobs.run_pending)


# ---------------------------------------------------------------- shared fakes + per-test isolated database
import re  # noqa: E402

import pytest  # noqa: E402

from backend import auth, circles, config, db, main, planner  # noqa: E402
from backend.qloo_client import QlooError  # noqa: E402


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


RELATED = {"chess": "board games", "jazz": "blues"}


def fake_resolve(label, category=None):
    if _n(label) == "qloo down":
        raise QlooError("Qloo HTTP 503", 503)
    k = _n(label)
    return {"label": label, "warnings": [], "candidates": [
        {"kind": "tag", "id": f"T:{k}", "name": label.title(), "type": "urn:tag:keyword:qloo", "source": "GET /v2/tags", "match": 1.0},
        {"kind": "entity", "id": f"E:{k}", "name": label.title(), "type": "urn:entity:book", "source": "GET /search", "match": 1.0},
    ], "suggested": f"T:{k}", "suggested_ids": [f"T:{k}"]}


def fake_taste(resolved, discovery_types=None):
    tags = []
    for r in resolved:
        base = r["id"].split(":", 1)[1]
        rel = RELATED.get(base)
        if rel:
            tags.append({"kind": "tag", "id": f"T:{rel}", "name": rel.title(), "affinity": 0.9})
    return {"tags": tags, "entities": [], "requests": [{"filter.type": "urn:tag"}], "warnings": []}


def fake_anchors(members, location, discovery_types=None, take=5):
    return {"anchors": [{"kind": "entity", "id": "A1", "name": "Anchor Book", "type": "urn:entity:book", "image": None,
                         "affinity": 0.8, "driven_by": [m["name"] for m in members][:2]}],
            "venues": [], "requests": [{"filter.type": "urn:entity:book"}], "warnings": []}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.migrate()
    auth._hits.clear()
    monkeypatch.setattr(circles, "resolve_interest", fake_resolve)
    monkeypatch.setattr(circles, "taste_profile", fake_taste)
    monkeypatch.setattr(main, "resolve_interest", fake_resolve)
    monkeypatch.setattr(main, "taste_profile", fake_taste)
    monkeypatch.setattr(planner, "group_anchors", fake_anchors)
    yield


