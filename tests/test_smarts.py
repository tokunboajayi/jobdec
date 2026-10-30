import datetime

import results_engine as RE
from agents import smarts


def test_extract_deadline_formats():
    y = smarts.TODAY().year
    assert smarts.extract_deadline("Please apply by December 5, 2026.") == "2026-12-05"
    assert smarts.extract_deadline("Application deadline: 11/30/2026") == "2026-11-30"
    assert smarts.extract_deadline("Applications close Friday, Nov 20")[:4] in (str(y), str(y + 1))
    assert smarts.extract_deadline("We hire year-round.") == ""


def test_deadline_and_freshness_deltas(sandbox):
    today = smarts.TODAY()
    assert smarts.deadline_delta((today - datetime.timedelta(days=1)).isoformat())[0] == -10
    assert smarts.deadline_delta((today + datetime.timedelta(days=3)).isoformat())[0] == 0.5
    smarts.record_posted("https://a.com/job/1?src=x", 1)
    smarts.record_posted("https://a.com/job/2", 45)
    assert smarts.freshness_delta("https://a.com/job/1")[0] == 1.0
    assert smarts.freshness_delta("https://a.com/job/2")[0] == -1.0
    assert smarts.freshness_delta("https://a.com/job/never-seen")[0] == 0.0


def test_should_attempt_skips_repeat_failures_until_retry(sandbox):
    url = "https://acme.com/jobs/1"
    assert smarts.should_attempt("Acme", "AI Intern", url)[0]
    RE.ledger_add("Acme", "AI Intern", url, "timeout")
    RE.ledger_add("Acme", "AI Intern", url, "unanswered required")
    ok, why = smarts.should_attempt("Acme", "AI Intern", url)
    assert not ok and "failed 2x" in why
    smarts._save(smarts.llm.CACHE_DIR / "retry.json", {RE.job_key("Acme", "AI Intern", url): "new rule"})
    assert smarts.should_attempt("Acme", "AI Intern", url)[0]       # one retry...
    assert not smarts.should_attempt("Acme", "AI Intern", url)[0]   # ...then skipped again


def test_should_attempt_never_retries_closed_posting(sandbox):
    import json
    url = "https://acme.com/jobs/2"
    RE.ledger_add("Acme", "Data Intern", url, "not_submitted")
    rec = RE.RECORDS_DIR / datetime.date.today().isoformat() / f"{RE._slug('Acme', 'Data Intern')}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"status": "closed"}), encoding="utf-8")
    smarts._save(smarts.llm.CACHE_DIR / "retry.json", {RE.job_key("Acme", "Data Intern", url): "new rule"})
    ok, why = smarts.should_attempt("Acme", "Data Intern", url)
    assert not ok and why == "posting closed"


def test_site_memory_only_lengthens_timeouts(sandbox):
    url = "https://slow.wd5.myworkdayjobs.com/job/1"
    assert smarts.site_timeout(url, 260) == 260
    smarts.site_record(url, "submitted", 300)
    assert 260 < smarts.site_timeout(url, 260) <= 600
    smarts.site_record("https://fast.com/j", "submitted", 30)
    assert smarts.site_timeout("https://fast.com/j", 260) == 260


def test_why_answer_cleans_scraped_titles(sandbox, monkeypatch):
    from agents import jd_fetch
    smarts._save(smarts.llm.CACHE_DIR / "scout.json", {"k": {
        "company": "Veeam", "title": "Job Application for Customer Care AI Analyst Intern at Veeam Back to jobs",
        "url": "https://x.com/j", "category": "ai_automation", "keywords": ["llm", "workflow"]}})
    monkeypatch.setattr(jd_fetch, "fetch", lambda url: ("Build LLM workflows.", "test"))
    text = smarts.why_answer("Veeam", "Job Application for Customer Care AI Analyst Intern at Veeam Back to jobs")
    assert "the Customer Care AI Analyst Intern role" in text
    assert "Back to jobs" not in text and "Job Application" not in text
    assert smarts.why_answer("Nobody Inc", "Analyst") == ""


def test_learner_waits_for_enough_outcomes(sandbox):
    assert "need" in smarts.learner_train().lower() or "outcomes" in smarts.learner_train().lower()
