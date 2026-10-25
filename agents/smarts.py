"""
Smarter decisions across the pipeline - rule-based + local models, no API needed.

  1 learning    learner_train() / learned_delta(): outcome-weighted scoring once ~150 outcomes exist;
                weekly_review(): one concrete suggestion per week from reply rates
  2 finding     record_posted() / freshness_delta(): postings <= 3 days old get priority;
                extract_deadline() / deadlines_soon(): application deadlines from job descriptions
  3 choosing    company_ties(): contacts already in tracker.csv; winner_similarity(): like jobs that replied
  4 applying    site memory (sites.json): per-site attempts / submits / duration -> timeout + ordering;
                should_attempt(): don't repeat failures unless a new rule now answers the blocking question
  5 answers     why_answer(): "why this company" built from the posting's real specifics + resume facts
  6 outreach    referral-first drafts for fit >= 9 and 7-day follow-ups (in outreach_drafter.py)
  7 after       build_prep_pack(): interview / assessment prep sheet; urgent deadlines in the briefing
"""
import csv, datetime, json, pathlib, re
from . import llm, context

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
SITES = llm.CACHE_DIR / "sites.json"
POSTED = llm.CACHE_DIR / "posted.json"
MODEL = llm.CACHE_DIR / "learned_model.json"
PREP_DIR = AUTOFILL / "prep"
TODAY = lambda: datetime.date.today()


def _load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(p, d):
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def _ukey(url):
    return (url or "").split("?")[0].rstrip("/").lower()


# ---------------------------------------------------------------- 2. freshness + deadlines
def record_posted(url, age_days):
    d = _load(POSTED)
    k = _ukey(url)
    if k not in d:
        d[k] = (TODAY() - datetime.timedelta(days=int(age_days or 0))).isoformat()
        _save(POSTED, d)


def age_days(url):
    p = _load(POSTED).get(_ukey(url))
    return (TODAY() - datetime.date.fromisoformat(p)).days if p else None


def freshness_delta(url):
    a = age_days(url)
    if a is None:
        return 0.0, ""
    if a <= 3:
        return 1.0, f"posted {a}d ago (+1)"
    if a >= 30:
        return -1.0, f"posted {a}d ago (-1)"
    return 0.0, ""


MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"


def extract_deadline(jd):
    """ISO date of an application deadline stated in the posting, or ''."""
    t = (jd or "").lower()
    m = re.search(rf"(?:apply by|application deadline|deadline to apply|applications? (?:close|due|accepted until|will be accepted until)|"
                  rf"last day to apply|closing date)[:\s]*(?:\w+day,?\s+)?({MONTHS})\.?\s+(\d{{1,2}})(?:,?\s*(20\d\d))?", t)
    if m:
        try:
            y = int(m.group(3)) if m.group(3) else TODAY().year
            d = datetime.datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {y}", "%b %d %Y").date()
            if not m.group(3) and d < TODAY() - datetime.timedelta(days=60):
                d = d.replace(year=y + 1)
            return d.isoformat()
        except ValueError:
            return ""
    m = re.search(r"(?:apply by|deadline|applications? close)[:\s]*(\d{1,2})/(\d{1,2})/(20\d\d|\d\d)", t)
    if m:
        try:
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            return datetime.date(y, int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return ""
    return ""


def deadline_delta(deadline):
    if not deadline:
        return 0.0, ""
    days = (datetime.date.fromisoformat(deadline) - TODAY()).days
    if days < 0:
        return -10.0, "deadline passed"
    if days <= 7:
        return 0.5, f"deadline in {days}d (+0.5)"
    return 0.0, ""


def deadlines_soon(days=7):
    """Queued, not-yet-applied jobs whose posting deadline is within `days` (from scout results)."""
    import results_engine as RE
    applied = RE.already_applied_keys()
    out = []
    for k, v in _load(llm.CACHE_DIR / "scout.json").items():
        dl = v.get("deadline")
        if dl and k not in applied:
            n = (datetime.date.fromisoformat(dl) - TODAY()).days
            if 0 <= n <= days and v.get("eligible"):
                out.append((n, f"{v.get('company', '')} - {v.get('title', '')[:60]} (fit {v.get('fit_score')}) due {dl}"))
    return [s for _, s in sorted(out)]


# ---------------------------------------------------------------- 3. company ties + winners
def _tracker_rows():
    p = AUTOFILL.parent.parent / "tracker.csv"
    try:
        with open(p, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def company_ties(company):
    """Contacts at this company already in the outreach tracker (accepted / replied / chatted count most)."""
    import results_engine as RE
    c = RE.norm(company)
    if len(c) < 3:
        return 0.0, ""
    hits = [r for r in _tracker_rows() if c in RE.norm(r.get("Firm", "")) or RE.norm(r.get("Firm", "")) in c and len(RE.norm(r.get("Firm", ""))) > 3]
    warm = [r for r in hits if r.get("Stage", "") in ("Accepted", "Thanked", "Thanked/Asked", "Replied", "Chat Scheduled", "Chat Done", "Messaged")]
    if warm:
        return 1.0, f"{len(warm)} warm contact(s) in tracker (+1)"
    if hits:
        return 0.5, f"{len(hits)} contact(s) in tracker (+0.5)"
    return 0.0, ""


def winner_texts():
    """Job descriptions of applications that got an assessment / interview / offer."""
    import results_engine as RE
    from . import jd_fetch
    urls = [r["url"] for r in RE.ledger_rows() if r.get("response") in ("assessment", "interview", "offer") and r.get("url")]
    p = AUTOFILL.parent / "applications.csv"
    try:
        with open(p, encoding="utf-8") as f:
            urls += [r["Job URL"] for r in csv.DictReader(f)
                     if r.get("Job URL") and re.search(r"interview|offer|\boa\b|assessment", r.get("Stage", ""), re.I)]
    except Exception:
        pass
    texts = []
    for u in dict.fromkeys(urls):
        t, _ = jd_fetch.fetch(u)
        if t:
            texts.append(t)
    return texts


def winner_similarity(jd):
    """+0..1 when this posting reads like ones that already got replies (needs >= 2 winners)."""
    try:
        from . import semantic
        if not semantic.available():
            return 0.0, ""
        wins = winner_texts()
        if len(wins) < 2:
            return 0.0, ""
        import numpy as np
        a = semantic.embed([jd[:2000]])[0]
        sims = semantic.embed([w[:2000] for w in wins]) @ a
        s = float(np.max(sims))
        bonus = max(0.0, min(1.0, (s - 0.55) * 4))
        return (round(bonus, 2), f"similar to a posting that replied ({s:.2f})") if bonus > 0 else (0.0, "")
    except Exception:
        return 0.0, ""


# ---------------------------------------------------------------- 4. site memory
def site_record(url, outcome, seconds):
    import results_engine as RE
    d = _load(SITES)
    s = d.setdefault(RE.site_key(url), {"attempts": 0, "submits": 0, "timeouts": 0, "secs": []})
    s["attempts"] += 1
    s["submits"] += outcome == "submitted"
    s["timeouts"] += outcome == "timeout"
    s["secs"] = (s.get("secs", []) + [round(seconds)])[-20:]
    s["last"] = TODAY().isoformat()
    _save(SITES, d)


def site_stats(url):
    import results_engine as RE
    return _load(SITES).get(RE.site_key(url), {})


def site_timeout(url, default):
    """Longer timeout for sites that are slow but do submit; never shorter than the default."""
    s = site_stats(url)
    ok = [x for x in s.get("secs", [])]
    if s.get("submits") and ok:
        return int(max(default, min(600, max(ok) * 1.3)))
    return default


def ats_success():
    """Submit rate per ATS from the results ledger (only ATSs with >= 5 attempts)."""
    import results_engine as RE
    att, sub = {}, {}
    for r in RE.ledger_rows():
        a = r.get("ats", "other")
        att[a] = att.get(a, 0) + 1
        sub[a] = sub.get(a, 0) + (r.get("status") == "submitted")
    return {a: sub[a] / att[a] for a in att if att[a] >= 5}


def _after_last_fix(row):
    """A failure only counts if it happened after the filler / profile last changed: every fix earns a retry."""
    import results_engine as RE
    ledger = getattr(RE, "LEDGER_FILE", AUTOFILL / "results.csv")
    if ledger.parent != AUTOFILL:
        return True
    code = max((AUTOFILL / f).stat().st_mtime for f in ("fill.py", "auth_manager.py", "account_verifier.py", "gmail_auth.py", "profile.json", "agents/options.py", "agents/smarts.py")
               if (AUTOFILL / f).exists())
    rec = AUTOFILL / (row.get("record") or "")
    if row.get("record") and rec.exists():
        return rec.stat().st_mtime > code
    # If no record file exists on disk, this was an unrecorded abort/timeout prior to the current fixes
    return False


def should_attempt(company, role, url):
    """Skip jobs that already failed twice, unless a new rule now answers what blocked them."""
    import results_engine as RE
    k = RE.job_key(company, role, url)
    fails = [r for r in RE.ledger_rows() if RE.job_key(r["company"], r["role"], r["url"]) == k and r["status"] != "submitted"
             and _after_last_fix(r)]
    if len(fails) < 2:
        return True, ""
    retry = _load(llm.CACHE_DIR / "retry.json")
    if k in retry:
        why = retry.pop(k)                       # one retry per new rule
        _save(llm.CACHE_DIR / "retry.json", retry)
        return True, "retrying: " + why
    return False, f"failed {len(fails)}x before - waiting for a fix"


def mark_retries(rules_added):
    """After the site fixer adds rules: queue a retry for failed jobs whose blocking question they now answer."""
    import results_engine as RE
    if not rules_added:
        return []
    pats = []
    for r in rules_added:
        try:
            pats.append(re.compile(r["q"], re.I))
        except (re.error, KeyError, TypeError):
            pass
    retry = _load(llm.CACHE_DIR / "retry.json")
    found = []
    for p in (AUTOFILL / "records").glob("*/*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("status") == "submitted":
            continue
        blockers = rec.get("unanswered_questions", []) + rec.get("blocked_sensitive_questions", [])
        hit = next((b for b in blockers for pt in pats if pt.search(b)), None)
        if hit:
            k = RE.job_key(rec.get("company", ""), rec.get("role", ""), rec.get("url", ""))
            retry[k] = f"new rule answers '{hit[:60]}'"
            found.append(f"{rec.get('company')} - {rec.get('role')}")
    _save(llm.CACHE_DIR / "retry.json", retry)
    return found


# ---------------------------------------------------------------- 5. better "why this company"
def _scout_for(company, role=""):
    import results_engine as RE
    c = RE.norm(company)
    best = None
    for v in _load(llm.CACHE_DIR / "scout.json").values():
        if c and c in RE.norm(v.get("company", "") or ""):
            if not best or (role and RE.norm(role)[:20] in RE.norm(v.get("title", ""))):
                best = v
    return best


GENERIC_TOOLS = {"ai", "excel", "sharepoint", "microsoft 365", "git", "git and github", "training", "website", "api"}


def why_answer(company, role):
    """2-3 sentences: a real specific from the posting + a matching resume fact. '' if nothing specific."""
    from . import jd_fetch, local
    sc = _scout_for(company, role)
    if not sc or not sc.get("url"):
        return ""
    jd, _ = jd_fetch.fetch(sc["url"])
    if not jd:
        return ""
    prefer = ["automation", "process improvement", "machine learning", "llm", "workflow", "data analysis", "analytics",
              "requirements", "product strategy", "market research", "stakeholder", "dashboard", "prompt", "agentic", "python", "sql"]
    have = [k for k in sc.get("keywords", []) if len(k) > 2]
    kws = ([k for k in prefer if k in have] + [k for k in have if k not in prefer and k not in GENERIC_TOOLS])[:2]
    focus = " and ".join(kws) if kws else "the work this team does"
    cat = sc.get("category", "")
    proof = {
        "ai_automation": "At Delta I automated shift-bid workflows handling 50,000+ employee bids, and I build with the Claude API.",
        "product": "At Delta I turned station requirements into product specs and 10+ process maps.",
        "analyst_data": "At Delta I built 6 Excel trackers and cleaned 3,000+ workflow records ahead of a platform rollout.",
        "business_systems": "At Delta I automated shift-selection workflows and built trackers across 8+ workstreams.",
    }.get(cat, "At Delta I automated workflows and built trackers for frontline operations.")
    title = re.sub(r"^(job application for|apply for)\s+", "", role or sc.get("title") or "", flags=re.I)
    title = re.sub(r"\s+(at\s+\S.*|back to jobs.*)$|\s*[\(\[].*$", "", title, flags=re.I).strip() or "this"
    text = f"I'm interested in {company} because the {title} role focuses on {focus}, which is the work I've enjoyed most. {proof}"
    if context.BANNED.search(text) or context.unsupported_numbers(text):
        return ""
    return text


# ---------------------------------------------------------------- 7. interview / assessment prep
LIKELY_QS = {
    "ai_automation": ["Walk me through an automation you built end to end.", "How would you decide where AI helps a business process - and where it doesn't?",
                      "How do you check that an AI tool's output is correct?"],
    "product": ["Tell me about a time you turned messy requirements into a clear spec.", "How do you prioritize when stakeholders disagree?",
                "Pick a product you use - how would you improve it?"],
    "analyst_data": ["Describe a dataset you cleaned and what you found.", "How do you explain a finding to a non-technical audience?",
                     "Walk me through how you'd build a dashboard for this team."],
}
COMMON_QS = ["Tell me about yourself.", "Why this company and this role?", "Tell me about a challenge and how you handled it.",
             "What questions do you have for us?"]


def build_prep_pack(company, role, url, stage):
    """prep/<company>.md - requirements from the posting, likely questions, and the resume stories that answer them."""
    from . import jd_fetch, local
    PREP_DIR.mkdir(exist_ok=True)
    out = PREP_DIR / f"{re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')}.md"
    if out.exists():
        return None
    jd, _ = jd_fetch.fetch(url) if url else ("", "")
    reqs = [l.strip(" -•*") for l in re.split(r"\n+|(?<=[.;!?])\s+", jd or "")
            if 25 < len(l.strip()) < 220 and re.search(r"\b(you will|you'll|responsib|require|qualif|experience with|familiar|ability to|skills?)\b", l, re.I)][:10]
    cat = (local.scout(company, role, url, jd)["category"] if jd else "other")
    bullets = [b for s in context.MASTER["sections"] for e in s.get("entries", []) for b in e.get("bullets", [])]
    stories = []
    try:
        from . import semantic
        if semantic.available() and reqs:
            for r in reqs[:6]:
                i, sim = semantic.nearest(r, bullets)
                if i is not None and sim > 0.35:
                    stories.append((r, bullets[i]))
    except Exception:
        stories = []
    lines = [f"# Prep: {company} - {role}", "", f"Stage: **{stage}** (prepared {TODAY().isoformat()})", f"Posting: {url or 'n/a'}", ""]
    lines += ["## What they're asking for"] + ([f"- {r}" for r in reqs] or ["- (posting text not available)"]) + [""]
    if stories:
        lines += ["## Your matching stories (from your resume - tell them as Situation / Task / Action / Result)"]
        lines += [f"- **{r[:90]}**\n  -> {b}" for r, b in stories] + [""]
    lines += ["## Likely questions"] + [f"- {q}" for q in LIKELY_QS.get(cat, []) + COMMON_QS] + [""]
    if stage == "assessment":
        lines += ["## Assessment tips", "- Do it in one sitting, on a laptop, in a quiet room; test camera/mic first for video ones.",
                  "- Check the deadline in agents/inbox_actions.md.", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    try:
        return str(out.relative_to(AUTOFILL))
    except ValueError:
        return str(out)


def build_prep_packs():
    """Prep sheets for every application that reached assessment / interview (from outcomes)."""
    import results_engine as RE
    made = []
    for r in RE.ledger_rows():
        if r.get("response") in ("assessment", "interview"):
            m = build_prep_pack(r["company"], r["role"], r["url"], r["response"])
            if m:
                made.append(m)
    p = AUTOFILL.parent / "applications.csv"
    try:
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                st = r.get("Stage", "")
                if re.search(r"interview|\boa\b|assessment", st, re.I):
                    m = build_prep_pack(r["Company"], r["Role"], r.get("Job URL", ""), "interview" if "interview" in st.lower() else "assessment")
                    if m:
                        made.append(m)
    except Exception:
        pass
    return made


# ---------------------------------------------------------------- 1. learning from outcomes
MIN_OUTCOMES = 150


def _features(r):
    import results_engine as RE
    cats = ["product", "ai_automation", "analyst_data", "business_systems", "swe", "other"]
    atss = ["greenhouse", "lever", "ashby", "workday", "other"]
    cat = r.get("category", "other"); ats = r.get("ats", "other")
    return ([1.0 if cat == c else 0.0 for c in cats] + [1.0 if ats == a else 0.0 for a in atss]
            + [float(r.get("fit_score") or 0) / 10, 1.0 if r.get("channel") == "manual" else 0.0])


def learner_train():
    """Fit a logistic regression on outcomes once there are enough; saves weights. Returns a status line."""
    import results_engine as RE
    rows = [r for r in RE.ledger_rows() if r.get("status") == "submitted"]
    labeled = [r for r in rows if (datetime.date.fromisoformat(r["date"]) <= TODAY() - datetime.timedelta(days=14)) or r.get("response")]
    if len(labeled) < MIN_OUTCOMES:
        return f"learning: {len(labeled)}/{MIN_OUTCOMES} applications with outcomes - keeping hand-set weights"
    y = [1 if r.get("response") in ("assessment", "interview", "offer") else 0 for r in labeled]
    if sum(y) < 5:
        return f"learning: only {sum(y)} positive outcomes - need 5+ to learn"
    from sklearn.linear_model import LogisticRegression
    X = [_features(r) for r in labeled]
    m = LogisticRegression(C=0.5, max_iter=500).fit(X, y)
    _save(MODEL, {"coef": m.coef_[0].tolist(), "intercept": float(m.intercept_[0]), "n": len(labeled), "pos": sum(y),
                  "trained": TODAY().isoformat()})
    return f"learning: trained on {len(labeled)} outcomes ({sum(y)} positive)"


def learned_delta(category, ats, fit):
    """-1..+1 adjustment from the trained model (0 until trained)."""
    mdl = _load(MODEL)
    if not mdl:
        return 0.0, ""
    import math
    x = _features({"category": category, "ats": ats, "fit_score": fit, "channel": "auto"})
    z = mdl["intercept"] + sum(w * v for w, v in zip(mdl["coef"], x))
    p = 1 / (1 + math.exp(-z))
    base = mdl["pos"] / max(1, mdl["n"])
    d = max(-1.0, min(1.0, (p - base) * 5))
    return (round(d, 2), f"learned from {mdl['n']} outcomes ({d:+.1f})") if abs(d) >= 0.1 else (0.0, "")


def weekly_review():
    """One concrete suggestion from reply rates (shown in Sunday's briefing)."""
    import results_engine as RE
    rows = [r for r in RE.ledger_rows() if r.get("status") == "submitted"]
    if len(rows) < 20:
        return f"Weekly review: {len(rows)} auto-submitted so far - too few to compare yet (need 20+)."
    by = {}
    for r in rows:
        g = by.setdefault(r.get("category", "other"), [0, 0])
        g[0] += 1
        g[1] += r.get("response") in ("rejection", "assessment", "interview", "offer")
    rates = {c: v[1] / v[0] for c, v in by.items() if v[0] >= 5}
    if len(rates) < 2:
        return "Weekly review: not enough applications per category to compare yet."
    best = max(rates, key=lambda c: rates[c]); worst = min(rates, key=lambda c: rates[c])
    return (f"Weekly review: '{best}' roles get replies {rates[best]:.0%} of the time vs '{worst}' {rates[worst]:.0%}. "
            f"Suggestion: raise category_weights.{best} by 1 in strategy.json.")
