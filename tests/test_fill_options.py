"""Answer-picking regressions found in the 2026-10-14 live run (DVTrading form)."""
import pathlib

import pytest

import fill

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "option_traps.html"


def test_pick_option_prefers_whole_word():
    rule = {"q": "^gender", "a": "Male"}
    assert fill.pick_option(["Select", "Female", "Male"], rule, "Gender") == "Male"


def test_best_option_prefers_whole_word():
    opts = [("Female", 1), ("Male (he/him)", 2)]
    assert fill._best_option(opts, "Male", "Male")[0] == "Male (he/him)"


def test_live_form_gender_and_discipline_list():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.route("**/*", lambda r: r.abort())
        pg.set_content(FIXTURE.read_text(encoding="utf-8"))
        fill.fill_page(pg, None, False, company="Test", role="Test")
        gender = pg.eval_on_selector("#g", "s => s.options[s.selectedIndex].text")
        ticked = pg.eval_on_selector_all("input[type=checkbox]:checked", "els => els.map(e => e.value)")
        b.close()
    assert gender in ("Male", "Decline to self-identify")   # AJ's rule says Male; never Female
    assert ticked == ["is"], ticked                          # only Information Systems, not every box
