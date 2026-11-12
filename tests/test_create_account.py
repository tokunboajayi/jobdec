"""Beta sign-up: `setup_wizard.py --new <name>` makes a private candidate home from the templates."""
import pytest

import setup_wizard as SW


def test_new_account_gets_its_own_home(tmp_path, monkeypatch):
    for f in (".env.example", "profile.example.json"):
        (tmp_path / f).write_text((SW.ROOT / f).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(SW, "ROOT", tmp_path)
    monkeypatch.delenv("JOBDEC_HOME", raising=False)
    home = SW.create_account("jane-doe")
    assert (home / ".env").exists() and (home / "profile.json").exists() and (home / "resumes").is_dir()
    assert SW.os.environ["JOBDEC_HOME"] == "profiles/jane-doe"
    facts = [l for l in (home / ".env").read_text(encoding="utf-8").splitlines() if l.startswith("CANDIDATE_")]
    assert facts and all(l.endswith("=") for l in facts), "sample person's facts leaked into a new account"
    with pytest.raises(SystemExit):
        SW.create_account("jane-doe")  # never overwrite someone's account
    with pytest.raises(SystemExit):
        SW.create_account("../escape")
