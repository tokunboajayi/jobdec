"""
Agent 6 - Site Fixer. Turns today's failed applications into fixes, with no human step:

  A. Rule fixes (most failures): a required question had no answer. If the verified facts answer it,
     a profile.json rule is added automatically (marked "src": "site_fixer"). Questions only AJ can
     answer (demographics, legal history, pay...) are listed in agents/needs_you.md instead - the
     pipeline keeps skipping those jobs until he adds an answer. Nothing waits on him.
  B. Code fixes (page stuck / crash): the expert model proposes a patch to fill.py. It is applied only
     if `git apply` succeeds, the file compiles, the failed page replays better, and NO saved page
     replays worse. Accepted patches are committed (undo with `git revert`); rejected ones are rolled
     back and saved under agents/fixes/ for reference.
"""
import datetime, json, pathlib, py_compile, re, subprocess
from typing import List
from pydantic import BaseModel
from . import llm, context, replay, local

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
FIX_DIR = pathlib.Path(__file__).resolve().parent / "fixes"
NEEDS_YOU = pathlib.Path(__file__).resolve().parent / "needs_you.md"
COMMON_LABELS = ["First Name", "Last Name", "Email", "Phone Number", "Address Line 1", "City", "State",
                 "Postal Code", "Country", "School", "Degree", "Resume", "LinkedIn", "Gender", "Race",
                 "Veteran Status", "Disability", "How did you hear about us?"]
MAX_CODE_FIXES_PER_DAY = 2


class RuleFix(BaseModel):
    label: str
    pattern: str
    answer: str
    option_pattern: str
    answer_comes_from_facts: bool
    fact_quote: str


class RulePlan(BaseModel):
    rules: List[RuleFix]


class CodeFix(BaseModel):
    diagnosis: str
    confident: bool
    unified_diff: str


RULE_SYSTEM = f"""You write answer rules for an application form-filler, using ONLY the candidate's facts.

{context.FACT_TEXT}

For each unanswered question: pattern = a short case-insensitive Python regex that matches this question's
wording (and close variants) but NOT unrelated questions like name, email, phone, address, gender or race.
answer = the value to enter. option_pattern = regex that picks the right dropdown option (e.g. "^No$"), or "".
answer_comes_from_facts = true only if a fact above states it; fact_quote = that exact fact text.
If the facts don't answer it, still return the item with answer_comes_from_facts=false and answer="".
Never answer demographics, legal/criminal history, relatives, pay, or anything not in the facts."""


def _today_failures(day=None):
    d = AUTOFILL / "records" / (day or datetime.date.today().isoformat())
    out = []
    for j in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            rec = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("status") != "submitted":
            rec["_json"], rec["_html"], rec["_log"] = j, j.with_suffix(".html"), j.with_suffix(".log")
            out.append(rec)
    return out


# ---------------------------------------------------------------- A. rule fixes
def _rule_ok(fix):
    try:
        rx = re.compile(fix.pattern, re.I)
    except re.error:
        return False
    if not rx.search(fix.label) or any(rx.search(l) for l in COMMON_LABELS):
        return False
    if not fix.answer_comes_from_facts or not fix.answer.strip():
        return False
    q = fix.fact_quote.strip().lower()
    return bool(q) and q[:60] in context.FACT_TEXT.lower()


def _add_rules(fixes):
    p = AUTOFILL / "profile.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    existing = {r["q"] for r in data["rules"]}
    added = []
    for f in fixes:
        if f.pattern in existing:
            continue
        rule = {"q": f.pattern, "a": f.answer, "src": "site_fixer", "added": datetime.date.today().isoformat()}
        if f.option_pattern:
            rule["option"] = f.option_pattern
        data["rules"].insert(0, rule)
        added.append(rule)
    if added:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return added


def _needs_you(items):
    existing = NEEDS_YOU.read_text(encoding="utf-8") if NEEDS_YOU.exists() else (
        "# Questions only you can answer\n"
        "Add each answer as a rule in profile.json, e.g. {\"q\": \"pattern\", \"a\": \"your answer\"}.\n"
        "Jobs that ask these are skipped until then.\n")
    new = [f"- {l}" for l in items if f"- {l}" not in existing]
    if new:
        NEEDS_YOU.write_text(existing.rstrip("\n") + "\n" + "\n".join(new) + "\n", encoding="utf-8")
    return new


def fix_rules(failures):
    labels = []
    for rec in failures:
        labels += rec.get("blocked_sensitive_questions", []) + rec.get("unanswered_questions", [])
    labels = list(dict.fromkeys(l.strip() for l in labels if l and l.strip()))[:40]
    eng = llm.engine("site_fixer")
    if not labels or eng == "off":
        return [], labels
    if eng == "local":
        fixes = []
        for l in labels:
            m = local.rule_for_question(l)
            if m:
                fixes.append(RuleFix(label=l, pattern=m[0], answer=m[1], option_pattern=m[2],
                                     answer_comes_from_facts=True, fact_quote=m[3]))
        good = [f for f in fixes if _rule_ok(f)]
        added = _add_rules(good)
        answered = {f.label for f in good}
        return added, [l for l in labels if l not in answered]
    plan = llm.ask("site_fixer", "writer", RULE_SYSTEM, "Unanswered questions:\n" + "\n".join(f"- {l}" for l in labels), RulePlan)
    if plan is None:
        return [], labels
    good = [f for f in plan.rules if _rule_ok(f)]
    added = _add_rules(good)
    answered = {f.label for f in good}
    return added, [l for l in labels if l not in answered]


# ---------------------------------------------------------------- B. code fixes
def _git(*args):
    return subprocess.run(["git", *args], cwd=str(AUTOFILL), capture_output=True, text=True)


def _git_ready():
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0 and not _git("status", "--porcelain", "fill.py").stdout.strip()


def _excerpt(html_path, limit=40000):
    h = html_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"(?is)<form.*?</form>", h)
    h = m.group(0) if m else h
    return h[:limit]


CODE_SYSTEM = """You fix a Playwright job-application form filler (fill.py) that failed on one site.
You get the run log, the page HTML at the moment it failed, and fill.py. Return a minimal unified diff
against fill.py (paths a/fill.py and b/fill.py) that makes this page work without changing behavior on other
sites. Prefer narrow, site-specific handling. Do not touch answer content, profile rules, the sensitive-question
guard, the account guard, or anything that submits. If you are not confident, set confident=false and return
an empty diff."""


def fix_code(rec):
    if not (rec["_html"].exists() and _git_ready() and llm.active("site_fixer")):
        return None
    fill_src = (AUTOFILL / "fill.py").read_text(encoding="utf-8")
    log = rec["_log"].read_text(encoding="utf-8", errors="ignore")[-6000:] if rec["_log"].exists() else ""
    user = (f"Site: {rec.get('url', '')}\nStatus: {rec.get('status')}\n\n# RUN LOG (tail)\n{log}\n\n"
            f"# PAGE HTML AT FAILURE\n{_excerpt(rec['_html'])}\n\n# fill.py\n{fill_src}")
    fx = llm.ask("site_fixer", "expert", CODE_SYSTEM, user, CodeFix, effort="high")
    if fx is None or not fx.confident or "+++ b/fill.py" not in fx.unified_diff:
        return None
    FIX_DIR.mkdir(exist_ok=True)
    patch = FIX_DIR / f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{rec['_json'].stem[:40]}.patch"
    patch.write_text(fx.unified_diff, encoding="utf-8")
    before = {s: replay.replay(s) for s in replay.all_snapshots()}
    if _git("apply", "--check", str(patch)).returncode != 0:
        return {"patch": str(patch), "applied": False, "why": "patch does not apply"}
    _git("apply", str(patch))
    try:
        py_compile.compile(str(AUTOFILL / "fill.py"), doraise=True)
    except py_compile.PyCompileError:
        _git("checkout", "--", "fill.py")
        return {"patch": str(patch), "applied": False, "why": "does not compile"}
    after = {s: replay.replay(s) for s in before}
    worse = [s.name for s in before if (after[s]["error"] and not before[s]["error"])
             or after[s]["unanswered"] > before[s]["unanswered"]]
    tgt = rec["_html"]
    better = tgt in before and (
        (before[tgt]["error"] and not after[tgt]["error"]) or after[tgt]["unanswered"] < before[tgt]["unanswered"]
        or after[tgt]["filled"] > before[tgt]["filled"])
    if worse or not better:
        _git("checkout", "--", "fill.py")
        return {"patch": str(patch), "applied": False, "why": f"replay: worse on {worse[:3]}" if worse else "replay: no improvement"}
    _git("add", "fill.py")
    _git("commit", "-m", f"site_fixer: {fx.diagnosis[:60]}\n\nSite: {rec.get('url', '')}\nPatch: {patch.name}")
    return {"patch": str(patch), "applied": True, "why": fx.diagnosis}


def run(day=None):
    """Called by daily_run.py after the batch. Returns a summary dict for the briefing."""
    failures = _today_failures(day)
    summary = {"failures": len(failures), "rules_added": [], "needs_you": [], "code_fixes": []}
    if not failures:
        return summary
    added, open_q = fix_rules(failures)
    from . import smarts
    summary["retries"] = smarts.mark_retries(added)
    summary["rules_added"] = [f"{r['q']} -> {r['a']}" for r in added]
    summary["needs_you"] = _needs_you(open_q)
    stuck = [r for r in failures if r.get("status") in ("incomplete", "not_submitted") and not r.get("unanswered_questions")
             and not r.get("blocked_sensitive_questions")]
    for rec in stuck[:MAX_CODE_FIXES_PER_DAY]:
        res = fix_code(rec)
        if res:
            summary["code_fixes"].append(res)
    return summary
