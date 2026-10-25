"""
Replay a saved failure page (records/<date>/<job>.html) through fill.fill_page offline - no network,
nothing submitted. Used by the site fixer to prove a fix helps and doesn't break other sites.

    python -m agents.replay records/2026-10-14/Acme_Analyst_Intern.html
prints JSON: {"filled": n, "unanswered": n, "blocked": n, "error": ""}
"""
import json, pathlib, subprocess, sys

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent

_CHILD = r"""
import json, sys, pathlib
sys.argv = ["fill.py"]
sys.path.insert(0, %r)
out = {"filled": 0, "unanswered": 0, "blocked": 0, "error": ""}
try:
    import fill, results_engine as RE
    from playwright.sync_api import sync_playwright
    html = pathlib.Path(%r).read_text(encoding="utf-8", errors="ignore")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_context(java_script_enabled=False).new_page()   # page scripts off: replay the saved DOM as-is
        pg.route("**/*", lambda r: r.abort())          # offline: block every network request
        pg.set_content(html, wait_until="domcontentloaded", timeout=15000)
        f, u, e, n = fill.fill_page(pg, None, False, company="Replay", role="Replay")
        out.update(filled=len(f), unanswered=len([x for x in u if x.get("required")]) + len(n), blocked=len(RE.SENSITIVE_HITS))
        b.close()
except Exception as ex:
    out["error"] = (type(ex).__name__ + ": " + str(ex))[:300]
print("REPLAY_JSON " + json.dumps(out))
"""


def replay(html_path, timeout=120):
    code = _CHILD % (str(AUTOFILL), str(html_path))
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(AUTOFILL), capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL, encoding="utf-8", errors="ignore")
        line = next((l for l in r.stdout.splitlines() if l.startswith("REPLAY_JSON ")), None)
        if line:
            return json.loads(line[len("REPLAY_JSON "):])
        return {"filled": 0, "unanswered": 0, "blocked": 0, "error": (r.stderr or "no output")[-300:]}
    except subprocess.TimeoutExpired:
        return {"filled": 0, "unanswered": 0, "blocked": 0, "error": "timeout"}


def all_snapshots():
    return sorted((AUTOFILL / "records").glob("*/*.html"))


if __name__ == "__main__":
    print(json.dumps(replay(sys.argv[1])))
