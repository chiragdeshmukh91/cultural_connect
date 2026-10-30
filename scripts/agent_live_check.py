"""Live check of the Qloo calls the autonomous agents depend on (run on a machine that can reach Qloo).

    python scripts/agent_live_check.py "pottery" "Pune"

1. resolves the interest exactly like the discovery agent (GET /search, /v2/tags, /v2/audiences)
2. runs the taste profile (GET /v2/insights filter.type=urn:tag + cross-category types)
3. asks Qloo for places near the location (GET /v2/insights filter.type=urn:entity:place, filter.location.query)
   and prints which operational fields Qloo actually returned (address, coordinates, hours, closed flag) —
   these are exactly the fields the venue validator uses. Nothing is written to the database. The key is never printed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config  # noqa: E402
from backend.qloo_client import QlooError  # noqa: E402
from backend.qloo_service import insights, resolve_interest, split_signals, taste_profile  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "pottery"
where = sys.argv[2] if len(sys.argv) > 2 else "Pune"
print(f"Qloo base URL: {config.QLOO_BASE_URL} | key configured: {bool(config.QLOO_API_KEY)}")
try:
    res = resolve_interest(label)
    picks = [c for c in res["candidates"] if c["id"] in res.get("suggested_ids", [])]
    print(f"\n1) Resolve '{label}': {len(res['candidates'])} candidates; auto-attach (match >= 0.8):",
          [(c["kind"], c["name"], round(c.get("match") or 0, 2)) for c in picks if (c.get("match") or 0) >= 0.8] or "none")
    if not picks:
        sys.exit("No confident match — the agent would keep this as a declared interest only.")
    prof = taste_profile([{"kind": c["kind"], "id": c["id"]} for c in picks])
    print(f"2) Taste profile: {len(prof['tags'])} tags, {len(prof['entities'])} entities; warnings: {prof['warnings'] or 'none'}")
    print("   sample tags:", [t["name"] for t in prof["tags"][:6]])
    e, t, a = split_signals([{"kind": c["kind"], "id": c["id"]} for c in picks])
    places = insights("urn:entity:place", e, t, a, take=6, location_query=where)["items"]
    print(f"3) Places near '{where}': {len(places)}")
    for p in places:
        print(f"   - {p['name']!r}: address={'yes' if p.get('address') else 'NO'}, coords={'yes' if p.get('lat') is not None else 'NO'}, "
              f"hours={'yes' if p.get('hours') else 'NO'}, is_closed={p.get('is_closed')}, website={'yes' if p.get('website') else 'no'}")
except QlooError as exc:
    sys.exit(f"Qloo error: {exc} (status {exc.status})")
