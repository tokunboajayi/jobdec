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
    best = fill._best_option(opts, "Male", "Male")
    assert best is not None and best[0] == "Male (he/him)"


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
        ticked = pg.eval_on_selector_all("input[type=checkbox]:checked", "els => els.map(e => e.parentElement.innerText.trim())")
        b.close()
    own_gender = (fill.rule_for("Gender") or {}).get("a")
    own_major = (fill.rule_for("Undergrad Discipline(s) *") or {}).get("a") or ""
    assert gender in (own_gender, "Decline to self-identify", "Select"), gender   # the profile's answer, never another
    assert len(ticked) <= 1 and all(t.lower() in own_major.lower() for t in ticked), ticked  # not every box


# B-1 (2026-11-03): 27 applications submitted School* = "Alcorn State University", the first option of a Greenhouse
# school search that did not list the candidate's school. Like react-select, Enter / Tab commit the focused option.
SCHOOLS = ["Alcorn State University", "Auburn University", "Georgia Southern University", "Kennesaw State University",
           "State University"]
SCHOOL_PAGE = """<!doctype html><html><body><form>
  <label for="school">School*</label>
  <div class="select__control"><div class="select__single-value" id="school_value"></div>
  <input id="school" class="select__input" role="combobox" aria-expanded="false" aria-required="true" required autocomplete="off"></div>
  <div id="school_menu"></div>
</form><script>
  const OPTIONS = %s, input = document.getElementById("school"), menu = document.getElementById("school_menu");
  function render(filter) {
    menu.innerHTML = "";
    const list = OPTIONS.filter(o => !filter || o.toLowerCase().includes(filter.toLowerCase()));
    if (!list.length) { menu.textContent = "No results found"; return; }
    for (const o of list) {
      const d = document.createElement("div");
      d.setAttribute("role", "option"); d.className = "select__option"; d.textContent = o;
      d.addEventListener("click", () => commit(o));
      menu.appendChild(d);
    }
  }
  function commit(o) { document.getElementById("school_value").textContent = o; input.value = ""; menu.innerHTML = ""; input.dataset.chosen = o; }
  input.addEventListener("input", () => render(input.value));
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" && !menu.querySelector("[role=option]")) render(input.value);
    const first = menu.querySelector("[role=option]");
    if ((e.key === "Enter" || e.key === "Tab") && first) commit(first.textContent);
  });
</script></body></html>"""


def _own_school_rule():
    r = fill.rule_for("School*") or {}
    assert r.get("a"), "profile has no school answer"
    return r


def test_pick_option_never_takes_first_school():
    r = _own_school_rule()
    opts = ["Select"] + [o for o in SCHOOLS if o != r["a"]]
    assert fill.pick_option(opts, r, "School*") is None
    assert fill.pick_option(opts, None, "School*") is None


def test_school_search_miss_leaves_field_empty():
    pytest.importorskip("playwright")
    import json
    from playwright.sync_api import sync_playwright
    r = _own_school_rule()
    opts = [o for o in SCHOOLS if o != r["a"]]
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.route("**/*", lambda req: req.abort())
        pg.set_content(SCHOOL_PAGE % json.dumps(opts))
        direct = fill.pick_prompt_option(pg, pg, pg.locator("#school"), r["a"], r, label="School*")
        after_direct = pg.get_attribute("#school", "data-chosen")
        pg.set_content(SCHOOL_PAGE % json.dumps(opts))
        fill.fill_page(pg, None, False, company="Test", role="Test")
        after_fill = pg.get_attribute("#school", "data-chosen")
        b.close()
    assert direct is None and after_direct is None, (direct, after_direct)
    assert after_fill is None, after_fill
