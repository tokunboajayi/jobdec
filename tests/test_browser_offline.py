"""Real Chromium, no network: the form filler and adaptive waits on local pages. Nothing is submitted."""
import pathlib, time

import pytest

pytest.importorskip("playwright")
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample_form.html"


def test_replay_fills_whole_form_offline():
    from agents import replay
    r = replay.replay(FIXTURE)
    assert r["error"] == "", r
    assert r["filled"] >= 5, r       # first, last, email, phone + sponsorship (AJ's explicit profile rule)
    assert r["unanswered"] == 0, r


def test_settle_returns_fast_on_static_page():
    from playwright.sync_api import sync_playwright
    from waits import settle
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.set_content(FIXTURE.read_text(encoding="utf-8"))
        t = time.time(); settle(pg, max_s=5)
        fast = time.time() - t
        pg.set_content("<div id=d></div><script>let n=0;const i=setInterval(()=>{d.innerHTML+='<input>';if(++n>12)clearInterval(i)},150)</script>")
        t = time.time(); settle(pg, max_s=5)
        slow = time.time() - t
        b.close()
    assert fast < 1.5
    assert slow > fast
