"""Checkpoint 1 from the build guide: prove real Qloo calls work before using the app.

Run from the project root:  python scripts/qloo_smoke_test.py
Prints status + response shape for each endpoint the app uses. Never prints the API key.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config  # noqa: E402
from backend.qloo_client import QlooError, get  # noqa: E402

CHECKS = [
    ("Entity search", "/search", {"query": "chess", "take": 3}),
    ("Tag search", "/v2/tags", {"filter.query": "chess", "take": 3}),
    ("Audiences", "/v2/audiences", {"filter.parents.types": "urn:audience:hobbies_and_interests", "take": 3}),
    ("Insights (artist)", "/v2/insights", {"filter.type": "urn:entity:artist", "take": 2}),
    ("Insights (taste tags)", "/v2/insights", {"filter.type": "urn:tag", "filter.tag.types": "urn:tag:keyword:media", "take": 3}),
]

print(f"Qloo base URL: {config.QLOO_BASE_URL}  | key configured: {bool(config.QLOO_API_KEY)}")
ok = 0
for name, path, params in CHECKS:
    try:
        data = get(path, params, use_cache=False)
        res = data.get("results") if isinstance(data, dict) else None
        if isinstance(res, dict):
            shape = {k: (len(v) if isinstance(v, list) else type(v).__name__) for k, v in res.items()}
        else:
            shape = f"list[{len(res)}]" if isinstance(res, list) else type(res).__name__
        print(f"  OK   {name:<22} {path:<16} results: {shape}")
        first = (res if isinstance(res, list) else next((v for v in (res or {}).values() if isinstance(v, list)), [])) or []
        if first:
            print("       sample:", json.dumps({k: first[0].get(k) for k in ("name", "entity_id", "id", "tag_id", "subtype", "type") if k in first[0]})[:200])
        ok += 1
    except QlooError as exc:
        print(f"  FAIL {name:<22} {path:<16} {exc}")
print(f"\n{ok}/{len(CHECKS)} checks passed.")
if ok == 0:
    print("No Qloo call succeeded: check QLOO_API_KEY / QLOO_BASE_URL in .env and your network/proxy.")
