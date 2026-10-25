import pytest

from agents import semantic

pytestmark = pytest.mark.skipif(not semantic.available(), reason="sentence-transformers not installed")


def test_meaning_match_beats_unrelated_text():
    jd = "You will design agentic workflows and orchestrate LLM tools to automate business processes."
    good = semantic.fit_signal(jd, ["Built Claude API automations that streamlined team workflows."])
    bad = semantic.fit_signal(jd, ["Soldered printed circuit boards for a robotics club."])
    assert good is not None and good > bad


def test_entity_guard_rejects_different_country(monkeypatch):
    monkeypatch.setattr(semantic, "known_answers",
                        lambda: [("Are you legally authorized to work in the United States", "Yes")])
    assert semantic.known_answer("Are you authorized to work in Canada") is None
