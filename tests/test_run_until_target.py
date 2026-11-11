"""A-7: the runner stops after MAX_FAILED_CYCLES consecutive crashed batches instead of relaunching forever."""
import sys
import types

import run_until_target as R


def _offline(monkeypatch, codes):
    calls = []
    monkeypatch.setattr(sys, "argv", ["run_until_target.py", "--target", "10"])
    monkeypatch.setattr(R, "get_applied_count", lambda: 0)
    monkeypatch.setattr(R, "run_ingestion", lambda: 0)
    monkeypatch.setattr(R, "run_triage", lambda: None)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: None)  # outcomes.py
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    import agents
    stub = types.SimpleNamespace(learner_train=lambda: "stub", run=lambda d: {"failures": 0, "rules_added": [], "needs_you": []})
    for name in ("smarts", "site_fixer"):
        monkeypatch.setattr(agents, name, stub, raising=False)
        monkeypatch.setitem(sys.modules, f"agents.{name}", stub)

    def batch(**kw):
        calls.append(kw)
        return codes[min(len(calls), len(codes)) - 1]
    monkeypatch.setattr(R, "run_batch", batch)
    return calls


def test_stops_after_three_consecutive_failed_batches(monkeypatch, capsys):
    calls = _offline(monkeypatch, [1])
    assert R.main() == 1
    assert len(calls) == R.MAX_FAILED_CYCLES == 3
    assert "STOPPED" in capsys.readouterr().out


def test_a_good_batch_resets_the_failure_count(monkeypatch):
    calls = _offline(monkeypatch, [1, 1, 0, 1, 1, 1])
    assert R.main() == 1
    assert len(calls) == 6
