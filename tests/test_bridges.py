"""Unit tests for the bridge engine and planner (no network)."""
from backend.bridges import build_groups, pair_evidence
from backend.planner import parse_feedback, review, rule_generate, evidence_pack, DEFAULT_CONSTRAINTS


def person(pid, name, interests, loc="Pune"):
    return {"id": pid, "name": name, "location": loc, "consent": True,
            "interests": [{"label": l, "intent": i, "resolved": [{"kind": "tag", "id": f"urn:tag:{l}", "name": l.title(), "type": "urn:tag:keyword"}]}
                          for l, i in interests],
            "profile": {"tags": [{"id": "urn:tag:x", "name": "X"}], "entities": []}}


def test_mentorship_detected():
    a, b = person("a", "Asha", [("chess", "teach")]), person("b", "Arjun", [("chess", "learn")])
    ev = pair_evidence(a, b)["evidence"]
    m = [e for e in ev if e["kind"] == "mentorship"]
    assert m and m[0]["teacher"] == "Asha" and m[0]["learner"] == "Arjun"


def test_groups_and_consent():
    ps = [person("a", "A", [("chess", "teach")]), person("b", "B", [("chess", "learn")]),
          person("c", "C", [("cricket", "share")]), person("d", "D", [("cricket", "share")])]
    ps[3]["consent"] = False
    res = build_groups(ps, 2, 4)
    names = [{m["name"] for m in g["members"]} for g in res["groups"]]
    assert {"A", "B"} <= names[0]
    assert "D" in res["excluded_no_consent"]


def test_plan_respects_constraints():
    ps = [person("a", "A", [("chess", "teach")]), person("b", "B", [("chess", "learn")])]
    g = build_groups(ps, 2, 4)["groups"][0]
    c = {**DEFAULT_CONSTRAINTS, "duration_min": 75, "budget": 3}
    pack = evidence_pack(g, None, use_qloo=False)
    concepts = rule_generate(g, pack, c, {"themes": [], "formats": []})
    assert concepts and concepts[0]["format"] == "skill_swap"
    for con in concepts:
        assert sum(a["minutes"] for a in con["agenda"]) == 75
        assert all(k["status"] != "fail" for k in review(con, c, pack))


def test_feedback_parsing():
    c, notes = parse_feedback("make it shorter, free and online", {**DEFAULT_CONSTRAINTS})
    assert c["duration_min"] < 90 and c["budget"] == 0 and c["setting"] == "online" and notes
