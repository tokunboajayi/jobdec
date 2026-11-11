import fake_candidate
from agents import context, local

JD = """AI Automation Intern - Summer 2027
Location: Atlanta, GA
You will design AI-powered workflow automation with LLM tools, map business processes, gather requirements
from stakeholders and build dashboards in Excel and SQL. Apply by December 1, 2026."""


def test_scout_scores_ai_posting():
    r = local.scout("Testco", "AI Automation Intern", "https://testco.com/jobs/1", JD)
    assert r["eligible"] and r["category"] == "ai_automation"
    assert r["fit_score"] >= 7
    assert r["deadline"] == "2026-12-01"


def test_scout_rejects_off_season():
    r = local.scout("Testco", "Data Intern - Fall 2026", "https://testco.com/jobs/2", "Data Intern - Fall 2026\nSQL work.")
    assert not r["eligible"] and r["fit_score"] == 0


def test_outreach_note_follows_playbook(monkeypatch, tmp_path):
    facts = fake_candidate.use(monkeypatch, tmp_path)
    o = local.outreach("Testco", "AI Automation Intern (Summer 2027)", "ai_automation")
    assert len(o["note"]) <= 300 and o["note"].endswith(f"- {facts['FIRST_NAME']}")
    assert facts["UNIVERSITY"] in o["note"]
    assert any(org in o["note"] for org in context.employers() + ["Lab"])  # hook quotes the candidate's own resume
    assert not context.BANNED.search(o["note"])
    assert not context.unsupported_numbers(o["note"])


def test_read_email_classifies():
    r = local.read_email("Acme <hr@acme.com>", "Interview invitation", "We'd like to schedule a call. Are you free Tuesday at 2pm ET?")
    assert r["kind"] == "interview" and r["urgent"]
    assert local.read_email("Acme", "Update", "Unfortunately we are not moving forward.")["kind"] == "rejection"
    assert not local.read_email("Board", "Jobs you may like", "Recommended jobs. Unsubscribe")["is_about_application"]


def test_unsupported_numbers_catches_invented_stats():
    assert context.unsupported_numbers("I improved revenue by 87,654%")


def test_unknown_email_charset_does_not_crash_inbox_scan():
    import gmail_auth
    assert gmail_auth.decode_str("=?unknown-8bit?q?Interview_invite?=") == "Interview invite"


def test_fact_rules_come_from_the_candidate_only(tmp_path):
    import importlib
    import pytest
    try:
        with pytest.MonkeyPatch.context() as mp:
            facts = fake_candidate.use(mp, tmp_path)
            mp.delenv("CANDIDATE_US_CITIZEN", raising=False)
            importlib.reload(local)
            assert all(r[1] for r in local.FACT_MAP)  # unknown facts make no rule
            assert local.rule_for_question("Which university are you attending?")[1] == facts["UNIVERSITY"]
            assert local.rule_for_question("Expected graduation date")[1] == facts["EXPECTED_GRAD_DATE"]
            assert local.rule_for_question("Are you a U.S. citizen?") is None  # not stated -> not answered
    finally:
        importlib.reload(local)
