import pathlib, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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
