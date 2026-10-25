"""Every module compiles and the pipeline entry points import cleanly (catches stray control characters too)."""
import importlib, pathlib, py_compile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = [p for d in ("", "agents", "brain", "dashboard", "tools") for p in (ROOT / d).glob("*.py")]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_compiles_without_control_chars(path):
    py_compile.compile(str(path), doraise=True)
    assert chr(8) not in path.read_text(encoding="utf-8", errors="ignore"), "backspace from a non-raw \\b"


@pytest.mark.parametrize("mod", ["results_engine", "waits", "fill", "auth_manager", "batch_apply", "batch_apply_parallel",
                                 "triage", "daily_run", "outcomes", "ai_responder", "agents.llm", "agents.context", "agents.local",
                                 "agents.smarts", "agents.job_scout", "agents.resume_tailor", "agents.form_answerer",
                                 "agents.outreach_drafter", "agents.inbox_analyst", "agents.site_fixer",
                                 "agents.job_sources", "agents.replay"])
def test_imports(mod):
    importlib.import_module(mod)


def test_strategy_is_valid():
    import results_engine as RE
    s = RE.strategy()
    assert s["daily_cap"] >= 100 and s["min_fit_score"] >= 1
    assert s["category_weights"]["ai_automation"] > s["category_weights"]["swe"]
