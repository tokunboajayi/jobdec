import json, pathlib, re

RULES = json.loads((pathlib.Path(__file__).resolve().parents[1] / "profile.json").read_text(encoding="utf-8"))["rules"]
BS = chr(92)


def test_all_rule_regexes_compile():
    for r in RULES:
        for k in ("q", "option"):
            if isinstance(r.get(k), str):
                re.compile(r[k])


def test_no_double_escaped_options():
    # '^No\b' in the loaded value is a literal backslash + b, which never matches a dropdown option
    bad = [r["q"][:60] for r in RULES if BS * 2 in (r.get("option") or "")]
    assert not bad, bad


def test_no_delta_or_2028_grad_answers():
    for r in RULES:
        assert r.get("a") != "Delta Air Lines" or "previous" in r["q"], r["q"]
        if re.search(r"end date.*year|start.*year", r["q"]):
            assert r.get("a") != "2028", r["q"]
