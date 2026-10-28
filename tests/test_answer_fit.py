"""Answers must fit the field: the 2026-10-14 failures, as tests."""
import pathlib

import pytest

import fill
from agents import options as O

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "answer_fit.html"


@pytest.mark.parametrize("label,want,opts,expect", [
    ("Is your expected graduation date in 2028 or later?*", "December 2027", ["Select...", "Yes", "No"], "No"),
    ("Will you graduate before 2029?", "05/2028", ["Yes", "No"], "Yes"),
    ("Gender", "Male", ["Female", "Male", "Decline"], "Male"),
    ("End date month*", "08", ["January", "July", "August", "September"], "August"),
    ("Start month", "May", ["01", "05", "08"], "05"),
    ("Country", "United States of America", ["Canada", "USA"], "USA"),
    ("Discipline", "Computer Information Systems", ["Computer Science", "Information Systems", "Political Science"], "Information Systems"),
    ("Authorized?", "Yes, I am authorized to work in this country for any employer", ["Yes", "No"], "Yes"),
])
def test_resolve(label, want, opts, expect):
    assert O.resolve(label, want, opts) == expect


def test_resolve_refuses_unsafe_yes_no():
    assert O.resolve("Which state?", "Georgia", ["Yes", "No"]) is None


def test_core_question_finds_the_ask():
    long = ("To be eligible for this position, your primary residence must be located in the United States. "
            "Please indicate the state in which you currently reside.*")
    assert O.core_question(long) == "Please indicate the state in which you currently reside"


@pytest.mark.parametrize("label,cat,answer", [
    ("Please re-confirm the university you currently attend *", "school", "Georgia State University"),
    ("What country do you currently reside in?*", "country", "United States of America"),
    ("To be eligible ... in the United States. Please indicate the state in which you currently reside.*", "state", "Georgia"),
])
def test_fact_questions_come_from_profile(label, cat, answer):
    c, r = O.fact_rule(label, fill.rule_for)
    assert c == cat and r is not None and r["a"] == answer


def test_profile_rules_have_no_backspaces():
    import json
    d = json.loads((pathlib.Path(fill.__file__).parent / "profile.json").read_text(encoding="utf-8"))
    assert not [r["q"] for r in d["rules"] if any(chr(8) in str(v) for v in r.values())]


@pytest.mark.parametrize("q,a", [
    ("Do you have relevant internship experience at a proprietary trading firm?", "No"),
    ("If yes, select your most recent proprietary trading firm experience", "N/A"),
    ("If yes, please provide your visa type and expiration date.", "N/A"),
    ("Do you have relevant work experience?", "Yes"),
])
def test_profile_rules_tell_the_truth(q, a):
    r = fill.rule_for(q)
    assert r is not None and r["a"] == a


def test_live_form_answers_fit():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.route("**/*", lambda r: r.abort())
        pg.set_content(FIXTURE.read_text(encoding="utf-8"))
        fill.fill_page(pg, None, False, company="Test", role="Test")
        got = {k: pg.eval_on_selector(f"#{k}", "s => s.options[s.selectedIndex].text") for k in ("g28", "st", "uni", "cty", "pt")}
        visa = pg.input_value("#vt")
        b.close()
    assert got == {"g28": "No", "st": "Georgia", "uni": "Georgia State University", "cty": "United States", "pt": "No"}, got
    assert visa == "N/A"


def test_react_select_opens_full_list_when_search_finds_nothing():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    page_html = (pathlib.Path(__file__).parent / "fixtures" / "react_select.html").read_text(encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.route("**/*", lambda r: r.abort())
        pg.set_content(page_html)
        fill.fill_page(pg, None, False, company="Test", role="Test")
        chosen = pg.get_attribute("#grad", "data-chosen")
        b.close()
    assert chosen in ("December 2027", "May/June 2028"), chosen


@pytest.mark.parametrize("want,expect", [("05/2028", "May/June 2028"), ("December 2027", "December 2027"), ("2028", "May/June 2028")])
def test_resolve_dates(want, expect):
    assert O.resolve("Are you graduating in December 2027 or May/June 2028?", want, ["December 2027", "May/June 2028"]) == expect


def test_combobox_with_unmatched_typed_answer():
    """Live failure: typing '05/2028' filtered the list to 0 results and nothing was chosen."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    page_html = (pathlib.Path(__file__).parent / "fixtures" / "react_select.html").read_text(encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.set_content(page_html)
        fill.pick_prompt_option(pg, pg, pg.locator("#grad"), "05/2028", {"a": "05/2028"},
                                label="Are you graduating in December 2027 or May/June 2028?*")
        chosen = pg.get_attribute("#grad", "data-chosen")
        b.close()
    assert chosen == "May/June 2028", chosen


def test_resource_is_not_a_referral_source():
    import ai_responder
    long = ("To provide you with the more efficient recruiting process, DIRECTV and its Human Resource suppliers "
            "may use artificial intelligence in the application screening process")
    assert ai_responder.pick_best_option(long, ["Yes", "No"]) != "LinkedIn"
    r = fill.rule_for(long)
    assert r is not None and r["a"] == "Yes"
    assert ai_responder.pick_best_option("How did you hear about us?", ["Indeed", "LinkedIn"]) == "LinkedIn"


def test_fill_output_survives_non_cp1252_text():
    import subprocess, sys
    code = "import sys; sys.argv=['x']; sys.path.insert(0, '.'); import fill; print('\u2018quoted\u2019 \u2192 ok')"
    r = subprocess.run([sys.executable, "-c", code], cwd=str(pathlib.Path(fill.__file__).parent), capture_output=True,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr[-300:]


def test_workday_country_listbox_finds_option_past_100():
    """Live failure (Primient): country became 'Aland Islands', then 'Georgia' the country."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    page_html = (pathlib.Path(__file__).parent / "fixtures" / "workday_listbox.html").read_text(encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.set_content(page_html)
        fill.fill_page(pg, None, False, company="Test", role="Test")
        chosen = pg.get_attribute("#country", "data-chosen")
        b.close()
    assert chosen == "United States of America", chosen


def test_short_learned_labels_only_match_exactly():
    """Learned rules like q='Date' used to answer every question containing 'date'."""
    import datetime
    r_date = fill.rule_for("Date")
    r_visa = fill.rule_for("If yes, please provide your visa type and expiration date.")
    assert r_date is not None and r_date["a"] == datetime.date.today().strftime("%m/%d/%Y")
    assert r_visa is not None and r_visa["a"] == "N/A"


def test_dial_code_list_gets_us_not_first_country():
    """Live failure: 'Phone Number' code dropdown got +355 / +358, site refused SMS."""
    assert O.resolve("Phone Number", "470-564-0910", ["Albania (+355)", "Aland Islands (+358)", "United States (+1)"]) == "United States (+1)"
