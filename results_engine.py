"""
Results engine - shared logic that makes the pipeline aim for interviews, not just submissions.

  1. TARGETING   score_job()      fit score 0-10 from role category, eligibility, company, location
  2. THROUGHPUT  ats_priority()   order jobs by how often each ATS actually completes
  3. VISIBILITY  record_answer()  every answer saved per application (records/<date>/<job>.json)
                 should_block()   sensitive questions (legal/eligibility/EEO) are never guessed
  4. ACCOUNTS    auth_blocked()   a site that failed sign-in is not retried (prevents lockouts);
                 is_protected()   top-target companies are never auto-applied
  5. RESULTS     ledger_add()     results.csv: one row per attempt, used by outcomes.py

Settings: strategy.json (created with defaults on first use; edit it to change behavior).
Used by triage.py, batch_apply.py, fill.py and outcomes.py.
"""
import csv, datetime, json, pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
STRATEGY_FILE = HERE / "strategy.json"
RECORDS_DIR = HERE / "records"
LEDGER_FILE = HERE / "results.csv"
AUTH_STATE_FILE = HERE / "auth_state.json"

DEFAULT_STRATEGY = {
    "min_fit_score": 6,
    "daily_cap": 25,
    "block_sensitive_guesses": True,
    "max_auth_failures_per_site": 1,
    "max_failures_per_site_per_run": 2,
    "protected_companies": [
        "BlackRock", "American Express", "Amex", "Jane Street", "Goldman Sachs", "Delta Air Lines",
        "Cox Automotive", "Invesco", "McKinsey",
    ],
    "target_companies": [
        "BlackRock", "American Express", "Jane Street", "Goldman Sachs", "Delta", "Cox", "Invesco",
        "Home Depot", "Chick-fil-A", "McKinsey", "PwC", "Deloitte", "Intuit", "Databricks", "Atlassian",
        "Mercedes", "UPS", "Southern Company", "NCR", "Fiserv", "Truist", "Coca-Cola", "Global Payments",
        "Microsoft", "Google", "Salesforce", "Capital One", "JPMorgan", "Morgan Stanley",
    ],
    "home_metro": ["atlanta", "alpharetta", "georgia", "remote"],
    "ai_bonus": 2,
    "category_weights": {
        "product": 4, "ai_automation": 3, "analyst_data": 3, "business_systems": 3,
        "consulting_strategy": 2, "finance_tech": 2, "swe": 0, "other": 1,
    },
}


def strategy():
    if not STRATEGY_FILE.exists():
        STRATEGY_FILE.write_text(json.dumps(DEFAULT_STRATEGY, indent=2), encoding="utf-8")
    try:
        s = json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    return {**DEFAULT_STRATEGY, **s}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


NOISE = {"jobs", "job", "careers", "career", "external", "apply", "en", "us", "en-us", "boards", "posting", "postings"}


def _url_words(url, company=""):
    """Workday/Lever URLs carry the full job title in the path (queue titles are truncated).
    Tokens containing the company slug are dropped so e.g. 'veeamsoftware' doesn't read as 'software'."""
    path = re.sub(r"^https?://[^/]+", "", url or "").split("?")[0]
    c = norm(company)
    toks = [t for t in re.split(r"[-_/%,.]+", path.lower()) if t and t not in NOISE]
    toks = [t for t in toks if not (len(c) > 3 and (c in norm(t) or norm(t) in c and len(norm(t)) > 5))]
    return " ".join(toks)


# ---------------------------------------------------------------- 1. targeting
CATEGORIES = [  # first match wins; SWE is checked before AI so "AI Software Engineer" counts as SWE
    ("swe", r"software (engineer|developer|engineering)"),  # "Software Engineer Intern, Product" is still SWE
    ("ai_automation", r"\b(ai|ml|genai|gen ai|llm|machine learning)[ /-]+(engineer|engineering|developer|solutions|scientist|research)|"
                      r"applied (ai|ml|machine learning)|ai solutions|ai enablement|prompt engineer"),
    ("product", r"\bproduct\b|\bapm\b|\bpm\b|program manag"),
    ("ai_automation", r"\bai\b (business|process|enablement|solutions|product|strategy|analyst|agent)|automation analyst|"
                      r"business process"),
    ("swe", r"software|(web|app|mobile|game) developer|\bsde\b|embedded|firmware|front ?end|back ?end|full ?stack|"
            r"devops|\bsre\b|hardware|mechanical|electrical|\bios\b|android|network engineer|security engineer|"
            r"infrastructure"),
    ("ai_automation", r"\bai\b|artificial intelligence|automation|gen ?ai|\bllm|prompt|machine learning|agent"),
    ("analyst_data", r"analyst|analytics|data|business intelligence|\bbi\b|insight|research"),
    ("business_systems", r"business (systems|technology|process)|\berp\b|\bit\b|technology (ops|operations)|solutions|enablement"),
    ("consulting_strategy", r"consult|strategy|operations|transformation"),
    ("finance_tech", r"fintech|finance|treasury|investment|wealth|asset management|banking"),
]
DISQUALIFY = [
    ("grad students only", r"ph\.? ?d|doctoral|master'?s|\(ms\)|\bms\b intern|\bmba\b|\bgraduate\b"),
    ("high school program", r"high school"),
    ("long co-op (conflicts with school)", r"co-?op|6-8 months|\b(fall|spring) 202[67]\b"),
    ("not an internship (full-time / experienced)", r"\bnew grad|\bsenior\b|\bsr\.?\b|\bstaff\b|\bprincipal\b|"
                                                     r"\bmanager\b(?!.*\b(intern|int|in)\b)|engineer (i|ii|iii)\b|\bfull[- ]time\b|director"),
]


AI_RE = re.compile(r"\b(ai|a\.i\.|genai|gen ai|llm|machine learning|artificial intelligence|agentic|copilot)\b", re.I)


def classify_role(role, url="", company=""):
    text = f"{role} {_url_words(url, company)}".lower()
    for name, pat in DISQUALIFY:
        if re.search(pat, text):
            return "ineligible", name
    for name, pat in CATEGORIES:
        if re.search(pat, text):
            return name, ""
    return "other", ""


def is_protected(company):
    c = norm(company)
    return any(norm(p) and (norm(p) in c or c in norm(p)) for p in strategy()["protected_companies"] if len(norm(p)) > 2)


def score_job(company, role, url=""):
    """Returns (score 0-10, category, reasons). Score < min_fit_score = skip."""
    s = strategy()
    category, why_out = classify_role(role, url, company)
    if category == "ineligible":
        return 0, category, [why_out]
    try:  # Job Scout verdict (read the full job description) beats title rules when available
        from agents import job_scout
        sc = job_scout.cached(company, role, url)
        if sc:
            cat = sc["category"] if sc.get("eligible") else "ineligible"
            why = sc.get("reasons", []) if sc.get("eligible") else [sc.get("ineligible_reason") or "ineligible"]
            if cat == "ineligible":
                return 0.0, cat, ["scout"] + why
            sc_score, sc_why = _smart_adjust(company, role, url, cat, float(sc.get("fit_score", 0)), sc.get("deadline", ""))
            return sc_score, cat, ["scout"] + why + sc_why
    except Exception:
        pass
    score, reasons = 3.0, []
    w = s["category_weights"].get(category, 1)
    score += w; reasons.append(f"{category} (+{w})")
    c = norm(company)
    if any(norm(t) and norm(t) in c for t in s["target_companies"]):
        score += 1.5; reasons.append("target company (+1.5)")
    text = f"{role} {_url_words(url, company)}"
    if any(m in text.lower() for m in s["home_metro"]):
        score += 1.5; reasons.append("Atlanta/remote (+1.5)")
    if re.search(r"2027|summer", text, re.I):
        score += 0.5; reasons.append("summer 2027 (+0.5)")
    if category != "ai_automation" and AI_RE.search(text):
        b = s.get("ai_bonus", 2)
        score += b; reasons.append(f"AI-focused role (+{b})")
    score, extra = _smart_adjust(company, role, url, category, score, "")
    return score, category, reasons + extra


def _smart_adjust(company, role, url, category, score, deadline):
    """Freshness, deadline, existing contacts and (once trained) learned-from-outcomes adjustments."""
    why = []
    try:
        from agents import smarts
        for d, txt in (smarts.freshness_delta(url), smarts.deadline_delta(deadline), smarts.company_ties(company),
                       smarts.learned_delta(category, ats_of(url)[0], score)):
            if d:
                score += d; why.append(txt)
    except Exception:
        pass
    return max(0.0, min(round(score, 1), 10)), why


# ---------------------------------------------------------------- 2. throughput
ATS = [  # (name, url pattern, priority: lower runs first - based on observed completion rates)
    ("greenhouse", r"greenhouse\.io|gh_jid=", 1), ("lever", r"lever\.co", 1), ("ashby", r"ashbyhq\.com", 1),
    ("smartrecruiters", r"smartrecruiters\.com", 2), ("workday", r"myworkdayjobs\.com|myworkday", 3),
    ("icims", r"icims\.com", 4), ("jazzhr", r"applytojob\.com", 2), ("pinpoint", r"pinpointhq\.com", 2),
    ("oracle", r"oraclecloud\.com|taleo", 5), ("avature", r"avature\.net", 5), ("successfactors", r"successfactors", 5),
]


def ats_of(url):
    for name, pat, prio in ATS:
        if re.search(pat, url or "", re.I):
            return name, prio
    return "other", 4


def site_key(url):
    """One key per login realm (a Workday tenant, an iCIMS subdomain, ...)."""
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return host


def ats_priority(url):
    name, prio = ats_of(url)
    st = _auth_state().get(site_key(url), {})
    if st.get("successes"):
        prio -= 1  # we already have a working account there
    return prio


def job_key(company, role, url):
    """Same job posted on several career pages -> same key (used to drop duplicates)."""
    m = re.search(r"(?:_|/)(R-?\d{4,}|JR-?\d{4,}|RQ\d{4,}|R\d{5,})(?:-\d)?\b", url or "", re.I) or \
        re.search(r"/jobs/(\d{6,})|gh_jid=(\d{6,})", url or "")
    req = next((g for g in (m.groups() if m else []) if g), "")
    if req:  # same requisition on the same employer site = same job, whatever the queue calls the company
        host = site_key(url).split(".")[0]
        return f"{host}:{req.upper()}"
    return f"{norm(company)}:{norm(role)[:30]}"


# ---------------------------------------------------------------- 3. visibility
SENSITIVE_RE = re.compile(
    r"convict|felon|criminal|misdemeanor|arrest|terminat|discharged|dismissed|fired|"
    r"sponsor|visa|authori[sz]ed to work|legally (eligible|authori)|citizen|immigration|"
    r"clearance|non-?compete|non-?solicit|obligation|previously applied|applied (to|with) us before|"
    r"relative|family member|related to|background check|drug|export|\bitar\b|debar|exclu|"
    r"government (employ|official)|conflict of interest|at least 18|\bage\b|"
    r"gender|sex\b|race|ethnic|hispanic|latino|veteran|military|disabilit|orientation|pronoun|transgender",
    re.I)
EEO_RE = re.compile(r"gender|sex\b|race|ethnic|hispanic|latino|veteran|military|disabilit|orientation|pronoun|transgender", re.I)
DECLINE_RE = re.compile(r"decline|prefer not|choose not|not wish|don'?t wish|do not want|not to (self[- ]?)?identify|not to disclose|not to answer", re.I)

ANSWERS = []          # this process's answers (one fill.py process = one job)
SENSITIVE_HITS = []   # sensitive questions we refused to guess on
UNANSWERED = []       # required questions left empty (fed to the site fixer)


def should_block(label):
    return bool(strategy()["block_sensitive_guesses"] and SENSITIVE_RE.search(label or ""))


def record_answer(label, value, source):
    ANSWERS.append({"label": (label or "")[:200], "value": str(value)[:500], "source": source,
                    "sensitive": bool(SENSITIVE_RE.search(label or ""))})


def _slug(company, role):
    return (re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_") or "job")[:80]


def write_record(company, role, url, status):
    d = RECORDS_DIR / datetime.date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_slug(company, role)}.json"
    guesses = [a for a in ANSWERS if a["source"] != "rule"]
    path.write_text(json.dumps({
        "company": company, "role": role, "url": url, "status": status,
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "guessed_answers": len(guesses),
        "sensitive_guesses": [a for a in guesses if a["sensitive"]],
        "blocked_sensitive_questions": SENSITIVE_HITS,
        "unanswered_questions": list(dict.fromkeys(UNANSWERED)),
        "answers": ANSWERS,
    }, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 4. accounts
def _auth_state():
    try:
        return json.loads(AUTH_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def auth_blocked(url):
    st = _auth_state().get(site_key(url), {})
    return st.get("failures", 0) >= strategy()["max_auth_failures_per_site"]


def record_auth(url, ok, note=""):
    try:
        from tools.file_lock import FileLock
        lock_ctx = FileLock(AUTH_STATE_FILE)
    except Exception:
        from contextlib import nullcontext
        lock_ctx = nullcontext()

    with lock_ctx:
        data = _auth_state()
        st = data.setdefault(site_key(url), {"failures": 0, "successes": 0})
        if ok:
            st["successes"] = st.get("successes", 0) + 1
            st["failures"] = 0
        else:
            st["failures"] = st.get("failures", 0) + 1
            st["note"] = note or "sign-in failed - sign in by hand / reset password, then delete this entry"
        st["last"] = datetime.datetime.now().isoformat(timespec="seconds")
        AUTH_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 5. results ledger
LEDGER_COLS = ["date", "company", "role", "url", "ats", "category", "fit_score", "channel", "status",
               "response", "response_date", "record"]


def ledger_rows():
    if not LEDGER_FILE.exists():
        return []
    with open(LEDGER_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ledger_write(rows):
    import time
    try:
        from tools.file_lock import FileLock
        lock_ctx = FileLock(LEDGER_FILE)
    except Exception:
        from contextlib import nullcontext
        lock_ctx = nullcontext()

    with lock_ctx:
        for attempt in range(10):
            try:
                with open(LEDGER_FILE, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=LEDGER_COLS, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                return
            except (IOError, PermissionError):
                time.sleep(0.05 * (attempt + 1))


def ledger_add(company, role, url, status, channel="auto"):
    score, category, _ = score_job(company, role, url)
    new_row = {
        "date": datetime.date.today().isoformat(),
        "company": company,
        "role": role,
        "url": url,
        "ats": ats_of(url)[0],
        "category": category,
        "fit_score": score,
        "channel": channel,
        "status": status,
        "response": "",
        "response_date": "",
        "record": f"records/{datetime.date.today().isoformat()}/{_slug(company, role)}.json"
    }
    try:
        from tools.file_lock import FileLock
        lock_ctx = FileLock(LEDGER_FILE)
    except Exception:
        from contextlib import nullcontext
        lock_ctx = nullcontext()

    with lock_ctx:
        write_header = not LEDGER_FILE.exists() or LEDGER_FILE.stat().st_size == 0
        for attempt in range(10):
            try:
                with open(LEDGER_FILE, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=LEDGER_COLS, extrasaction="ignore")
                    if write_header:
                        w.writeheader()
                    w.writerow(new_row)
                break
            except (IOError, PermissionError):
                time.sleep(0.05 * (attempt + 1))


def submitted_today():
    today = datetime.date.today().isoformat()
    # distinct jobs: a submission can be written to the ledger twice (fill.py + batch_apply), which hit the cap at 51 real
    return len({job_key(r["company"], r["role"], r["url"]) for r in ledger_rows() if r["date"] == today and r["status"] == "submitted"})


def already_applied_keys():
    keys = set()
    p = ROOT / "applications.csv"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("Stage") and r["Stage"] not in ("Found", "Scored", "Tailored", "Skipped (low fit)", "Needs decision"):
                    keys.add(job_key(r.get("Company", ""), r.get("Role", ""), r.get("Job URL", "")))
    for r in ledger_rows():
        if r["status"] == "submitted":
            keys.add(job_key(r["company"], r["role"], r["url"]))
    return keys


# ---------------------------------------------------------------- queue parsing (shared)
HOLD_RE = re.compile(r"\((?=[^)]*(?<![A-Za-z])(?:AJ|first|confirm|OK)(?![A-Za-z]))[^)]*\)", re.I)


def parse_queue_file(path):
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        m = re.search(r"(https?://\S+)", raw)
        if not m:
            continue
        prefix = raw[:m.start()].strip()
        hold = HOLD_RE.search(prefix)
        prefix = " ".join(HOLD_RE.sub("", prefix).split())
        parts = prefix.split(" ", 1)
        out.append({"line": raw, "company": parts[0] if parts else "", "role": parts[1] if len(parts) > 1 else "",
                    "url": m.group(1), "resume": raw[m.end():].strip() or None,
                    "hold": hold.group(0) if hold else None})
    return out
