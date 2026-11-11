"""2026-11-11 live review: 9 Anduril applications said the candidate (a US citizen) holds a green card. One shared
word ("person") was enough to pick an option, and several fill paths took the first option when nothing matched.
An option is now chosen only when it IS the candidate's answer; otherwise the field is left for the grounded AI."""
from agents import intelligent_resolver as IR
from agents import options as O

EXPORT = "EXPORT CONTROLS - This position is subject to U.S. export controls. Please select the option that applies to you."
ANDURIL = ["A U.S. citizen or national",
           "A person lawfully admitted for permanent residence of the United States (i.e., Green Card holder)",
           "A person granted asylum or refugee status", "None of the above"]
EXPORT_RULE = r"^(?:(?:I am )?an? )?U\.?S\.? ?(?:citizen|national|person)|United States citizen|^citizen\b|^Yes\b"


def test_one_shared_word_never_picks_an_option():
    assert IR.pick_best_matching_option("U.S. person", ANDURIL) is None
    assert IR.pick_best_matching_option("Yes", ["Yes", "No"]) == "Yes"


def test_export_rule_picks_the_citizen_option():
    assert O.resolve(EXPORT, "U.S. Citizen", ANDURIL, pattern=EXPORT_RULE) == "A U.S. citizen or national"


def test_no_ai_means_no_option_not_the_first_one():
    # tests run without an API key: nothing grounded answers, so nothing is picked
    assert IR.resolve_field("Which shift do you prefer?", "select", ["Night", "Day"]) is None
    import fill
    assert fill.pick_option(["Night", "Day"], {"a": "Weekends"}, label="Which shift do you prefer?") is None


def test_month_list_accepts_a_full_date():  # Baird: graduation fact 12/10/2027 could not pick "December"
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]
    assert O.resolve("What is your anticipated month of graduation?*", "12/10/2027", months) == "December"


def test_work_dates_come_from_that_jobs_resume_line(monkeypatch):
    # Cloudflare 2026-11-11: the generic 'start date year -> 2023' (school) rule went on a work-history block
    import fill
    from agents import context
    monkeypatch.setattr(context, "resume_text", lambda: "Acme Robotics | Intern | Atlanta, GA | May 2026 - Aug 2026\n")
    fill.resume_jobs.cache_clear()
    try:
        from playwright.sync_api import sync_playwright
        html = ("<div><label for=c>Company*</label><input id=c value='Acme Robotics'>"
                "<label for=y>From* Year</label><input id=y><label for=t>To* Month</label><input id=t></div>"
                "<div><label for=s>School or University*</label><input id=s><label for=e>From* Year</label><input id=e></div>")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.set_content(html)
            assert fill.experience_date(pg.locator("#y"), "From* Year")[0] == "2026"
            assert fill.experience_date(pg.locator("#t"), "To* Month")[0] == "08"
            assert fill.experience_date(pg.locator("#e"), "From* Year") is None  # education: normal rules
            b.close()
    finally:
        fill.resume_jobs.cache_clear()


def test_dropdown_options_are_found_inside_an_iframe_form():
    # William Blair embeds Greenhouse in an iframe: options were searched on the top page only (0 found)
    import fill
    from playwright.sync_api import sync_playwright
    inner = "<div role=listbox><div role=option>United States +1</div><div role=option>Canada +1</div></div>"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(f'<p>company site</p><iframe srcdoc="{inner}" style="width:600px;height:300px"></iframe>')
        pg.wait_for_timeout(300)
        frame = pg.frames[1]
        assert [t for t, _ in fill._visible_options(frame)] == ["United States +1", "Canada +1"]
        b.close()


def test_major_is_never_swapped_for_a_different_one():
    pat = r"Computer Information Systems|^Information Systems|Management Information Systems"
    assert O.resolve("Discipline", "Computer Information Systems", ["Computer Science", "Other"], pattern=pat) == "Other"


def test_pitch_only_goes_into_real_open_questions():
    assert IR.synthesize_from_resume("Do you identify as disabled?", "text") is None
    for label in ("Search", "START YOUR JOB SEARCH HERE", "If you chose Other to the above question, please list which",
                  "Title*", "Current role"):
        assert IR.synthesize_from_resume(label, "text") is None, label
