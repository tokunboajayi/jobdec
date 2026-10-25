import os
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


def test_outreach_note_follows_playbook():
    o = local.outreach("Testco", "AI Automation Intern (Summer 2027)", "ai_automation")
    first = os.getenv("CANDIDATE_FIRST_NAME", "Tokunbo")
    assert len(o["note"]) <= 300 and o["note"].endswith(f"- {first}")
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
