import results_engine as RE


def test_ai_roles_rank_above_plain_roles():
    ai, cat, _ = RE.score_job("Testco", "AI Engineer Intern - Summer 2027")
    plain, _, _ = RE.score_job("Testco", "Data Analyst Intern")
    assert cat == "ai_automation"
    assert ai > plain
    assert ai >= RE.strategy()["min_fit_score"]


def test_swe_and_off_season_roles_are_skipped():
    swe, cat, _ = RE.score_job("Testco", "Software Engineer Intern")
    assert cat == "swe" and swe < RE.strategy()["min_fit_score"]
    off, cat, _ = RE.score_job("Testco", "Business Analyst Intern - Fall 2026")
    assert cat == "ineligible" and off == 0


def test_ai_bonus_regex_has_real_word_boundaries():
    assert chr(8) not in RE.AI_RE.pattern          # a backspace here once silently disabled the AI bonus
    assert RE.AI_RE.search("Product Manager, GenAI")
    assert not RE.AI_RE.search("Maintenance planner")


def test_job_key_dedupes_same_requisition():
    a = RE.job_key("HNTB", "AI Intern", "https://hntb.wd5.myworkdayjobs.com/x/job/Austin/Intern_R-31865")
    b = RE.job_key("HNTB Corp", "Intern AI", "https://hntb.wd5.myworkdayjobs.com/y/job/KC/Intern_R-31865-1")
    assert a == b


def test_sensitive_questions_are_blocked():
    for q in ["Will you now or in the future require visa sponsorship?", "Have you ever been convicted of a felony?",
              "Are you legally authorized to work in the United States?"]:
        assert RE.should_block(q), q
    assert not RE.should_block("What is your expected graduation date?")


def test_queue_parsing_and_holds(tmp_path):
    q = tmp_path / "q.txt"
    q.write_text("# comment\nAcme Data Analyst Intern https://acme.com/jobs/123 resumes/a.pdf\n"
                 "Beta PM Intern (AJ OK relocation first) https://beta.com/jobs/9\n", encoding="utf-8")
    rows = RE.parse_queue_file(q)
    assert [r["company"] for r in rows] == ["Acme", "Beta"]
    assert rows[0]["resume"] == "resumes/a.pdf" and rows[0]["hold"] is None
    assert rows[1]["hold"] and rows[1]["role"] == "PM Intern"


def test_ledger_roundtrip(sandbox):
    RE.ledger_add("Acme", "AI Intern", "https://acme.com/jobs/1", "submitted")
    assert RE.submitted_today() == 1
    assert RE.job_key("Acme", "AI Intern", "https://acme.com/jobs/1") in RE.already_applied_keys()
