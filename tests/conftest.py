import os, pathlib, shutil, sys, tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Tests run as a throwaway candidate, set before any project module is imported: ledgers, queues, caches and
# .env resolve into a temp folder, so a test can never write the real applications.csv (it did, 2026-11-10).
# The owner's answer rules are copied in read-only so rule tests still see real rules.
_TEST_HOME = pathlib.Path(tempfile.mkdtemp(prefix="jobdec-test-home-"))
if (ROOT / "profile.json").exists():
    shutil.copy(ROOT / "profile.json", _TEST_HOME / "profile.json")
os.environ["JOBDEC_HOME"] = str(_TEST_HOME)
for _k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_k, None)  # no test may message anyone or call a paid API


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point every file the smarts / ledger code writes at a temp dir, so tests never touch real run data."""
    import results_engine as RE
    from agents import llm, smarts
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(llm, "CACHE_DIR", cache)
    monkeypatch.setattr(smarts, "SITES", cache / "sites.json")
    monkeypatch.setattr(smarts, "POSTED", cache / "posted.json")
    monkeypatch.setattr(smarts, "MODEL", cache / "learned_model.json")
    monkeypatch.setattr(smarts, "PREP_DIR", tmp_path / "prep")
    monkeypatch.setattr(RE, "LEDGER_FILE", tmp_path / "results.csv")
    return tmp_path
