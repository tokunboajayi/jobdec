"""
Rule-based engine: the no-API-key version of every agent. Free, instant, deterministic.
Each agent module calls these when llm.engine(agent) == "local" (no key, or "engine": "local").
Same output shapes as the AI versions, so the rest of the pipeline can't tell the difference.

Uses only: the full job description (fetched over plain HTTP), the master resume, profile.json.
"""
import datetime, os, re
from . import context

# ---------------------------------------------------------------- vocabulary
def _resume_skills():
    """Skill phrases the resume actually backs up (from the ADDITIONAL INFORMATION lines)."""
    out = set()
    for s in context.MASTER["sections"]:
        for _, txt in s.get("labeled", []):
            for part in re.split(r"[,;()]", txt):
                p = part.strip().lower()
                if 2 <= len(p) <= 40 and p not in ("english – fluent", "yoruba – conversational"):
                    out.add(p)
    return out


RESUME_SKILLS = _resume_skills() | {
    "process mapping", "requirements", "stakeholder", "product specs", "roadmap", "workflow", "automation",
    "data validation", "dashboard", "excel", "sql", "python", "tableau", "power bi", "valuation", "dcf",
    "financial analysis", "market research", "competitive analysis", "build-vs-buy", "api", "llm", "ai",
    "machine learning", "prompt", "agentic", "project management", "training", "process improvement",
    "real estate", "fintech", "payments", "stripe", "website", "astro", "git", "sharepoint", "microsoft 365",
}
# skills a posting may require that the resume does NOT show (become "gaps")
HARD_SKILLS = {"java", "c++", "c#", "javascript", "typescript", "react", "node", "go", "golang", "rust", "kotlin",
               "swift", "aws", "azure", "gcp", "kubernetes", "docker", "spark", "hadoop", "scala", "r programming",
               "sas", "matlab", "salesforce", "sap", "figma", "jira", "data structures", "algorithms", "linux",
               "cad", "solidworks", "verilog", "embedded", "computer vision", "deep learning"}
CATEGORY_TERMS = {
    "product": ["product manag", "product owner", "roadmap", "user research", "prd", "requirements", "product strategy",
                "go-to-market", "feature", "customer needs", "prioritiz", "product spec", "process map", "stakeholder"],
    "analyst_data": ["analytics", "data analysis", "sql", "tableau", "power bi", "dashboard", "insights", "reporting",
                     "excel", "kpi", "metrics", "data visualization"],
    "ai_automation": ["artificial intelligence", "generative ai", "llm", "machine learning", "automation", "prompt",
                      "ai tools", "copilot", "agent", "chatgpt", "claude", "automat", "workflow"],
    "business_systems": ["business systems", "erp", "process improvement", "business process", "systems analyst",
                         "implementation", "enablement", "operations"],
    "swe": ["software engineer", "data structures", "algorithms", "backend", "frontend", "full stack", "java", "c++",
            "distributed systems", "code review", "production code", "computer science degree", "unit test"],
}


def _norm_text(t):
    return re.sub(r"\s+", " ", (t or "").lower())


def jd_keywords(jd):
    t = _norm_text(jd)
    return sorted({k for k in RESUME_SKILLS if len(k) > 1 and re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t)},
                  key=lambda k: -t.count(k))


# ---------------------------------------------------------------- 1. job scout
def _eligibility(title, jd):
    t = _norm_text(jd)
    tt = _norm_text(title)
    if re.search(r"(pursuing|enrolled in|candidate for) (a |an )?(master'?s|ph\.?d|mba|graduate degree)", t) and \
            not re.search(r"bachelor'?s (or|and/or) (master|graduate)|undergraduate (or|and/or) graduate", t):
        return "requires a graduate program"
    years = []
    for m in re.finditer(r"graduat\w*[^.]{0,90}", t):
        years += [int(y) for y in re.findall(r"20(2\d)", m.group(0))]
    years = [2000 + y for y in years if 24 <= y <= 31]
    if years and max(years) < 2028:
        return f"graduation window ends {max(years)} (AJ graduates May 2028)"
    if years and min(years) > 2028:
        return f"graduation window starts {min(years)}"
    if re.search(r"(active|current) (secret|top secret|ts/sci)[^.]{0,30}clearance (is )?required|must (hold|have) an? active (secret|ts)", t):
        return "requires an active security clearance"
    if "intern" not in tt and "co-op" not in tt and re.search(r"\bfull[- ]time (position|role|employee)|new grad", t + " " + tt):
        return "full-time / new-grad role"
    if re.search(r"\bco-?op\b[^.]{0,60}(semester|6 months|six months)", t):
        return "co-op requires leaving school for a semester"
    return ""


def scout(company, role, url, jd):
    import results_engine as RE
    t = _norm_text(jd)
    why_out = _eligibility(role, jd)
    first_line = (jd.splitlines() or [role])[0][:120]
    title = first_line if len(first_line) > len(role) else role
    hits = {c: sum(t.count(term) for term in terms) for c, terms in CATEGORY_TERMS.items()}
    title_cat, _ = RE.classify_role(title, url, company)
    cat = title_cat if title_cat not in ("other", "ineligible") else max(hits, key=lambda c: hits[c])
    if cat != "swe" and hits["swe"] >= 6 and hits["swe"] > 2 * max(hits[c] for c in hits if c != "swe"):
        cat = "swe"  # the description is really an engineering job
    kws = jd_keywords(jd)
    gaps = [g for g in sorted(HARD_SKILLS) if re.search(rf"(?<![a-z+#]){re.escape(g)}(?![a-z+#])", t)][:6]
    s = RE.strategy()
    score = 3 + s["category_weights"].get(cat, 1)
    score += min(2.0, len(kws) * 0.25)          # resume coverage of what the posting asks for
    score -= min(2.0, len(gaps) * 0.5)          # hard skills it asks for that the resume lacks
    sem = None
    try:  # neural meaning match between the posting and the resume (local model, free)
        from . import semantic
        if semantic.available():
            sem = semantic.fit_signal(jd, _resume_texts())
            if sem is not None:
                score += max(-1.5, min(1.5, (sem - 0.45) * 15))
    except Exception:
        sem = None
    if any(RE.norm(x) in RE.norm(company) for x in s["target_companies"] if len(RE.norm(x)) > 2):
        score += 1
    loc_m = re.search(r"location:\s*([^\n]+)", jd, re.I)
    location = loc_m.group(1).strip() if loc_m else ""
    if any(m in (location + " " + role).lower() for m in s["home_metro"]):
        score += 1
    ai_hits = hits["ai_automation"] + len(re.findall(r"\b(ai|genai|llm|machine learning|artificial intelligence)\b", t))
    if cat != "ai_automation" and (RE.AI_RE.search(title) or ai_hits >= 8):
        score += s.get("ai_bonus", 2)   # AI-focused product / analyst / ops role
    if re.search(r"\b(fall|spring|winter) (20)?2[67]\b", _norm_text(title)) and "summer" not in _norm_text(title):
        why_out = why_out or "not a summer internship"
    try:
        from . import smarts
        wb, wtxt = smarts.winner_similarity(jd)
        score += wb
        deadline = smarts.extract_deadline(jd)
    except Exception:
        wb, wtxt, deadline = 0.0, "", ""
    eligible = not why_out
    reasons = [f"{cat} role"] + (["AI-focused"] if ai_hits >= 8 else []) + ([f"meaning match {sem:.2f}"] if sem else []) + ([f"matches: {', '.join(kws[:4])}"] if kws else [])
    return {"title": title, "category": cat, "is_internship": "intern" in _norm_text(title) or "intern" in t[:400],
            "term": "Summer 2027" if "2027" in t else "", "eligible": eligible, "ineligible_reason": why_out,
            "location": location, "fit_score": int(round(max(0, min(10, score)))) if eligible else 0,
            "reasons": reasons, "gaps": [f"posting asks for {g}" for g in gaps], "keywords": kws[:8], "engine": "local",
            "company": company, "url": url, "deadline": deadline} | ({"winner_match": wtxt} if wtxt else {})


def _resume_texts():
    return ([b for s in context.MASTER["sections"] for e in s.get("entries", []) for b in e.get("bullets", [])]
            + [v for s in context.MASTER["sections"] for _, v in s.get("labeled", [])])


# ---------------------------------------------------------------- 2. resume tailor
def tailor_overlay(jd, category=""):
    """Bullets and skills lines that share the most words with the posting go first.
    Terms typical of the role's category (e.g. product specs for PM roles) count extra."""
    t = _norm_text(jd)
    kws = set(jd_keywords(jd))
    cat_terms = [w for term in CATEGORY_TERMS.get(category, []) for w in term.split() if len(w) > 3]
    jd_words = {w for w in re.findall(r"[a-z][a-z+#.-]{3,}", t)} - {"with", "from", "that", "this", "will", "your", "have", "team"}

    def rel(text):
        lt = text.lower()
        return (2 * sum(1 for k in kws if k in lt) + 3 * sum(1 for w in cat_terms if w in lt)
                + len(set(re.findall(r"[a-z][a-z+#.-]{3,}", lt)) & jd_words) * 0.2)

    neural = {}
    try:  # meaning similarity of every bullet / skills line to the posting (local model)
        from . import semantic
        if semantic.available():
            texts = _resume_texts()
            sc = semantic.bullet_scores(jd, texts)
            if sc:
                neural = dict(zip(texts, sc))
    except Exception:
        neural = {}
    base_rel = rel
    rel = lambda text: base_rel(text) + 8 * neural.get(text, 0)

    bullet_order, labeled = {}, []
    for s in context.MASTER["sections"]:
        for e in s.get("entries", []):
            b = e.get("bullets", [])
            if len(b) > 1:
                bullet_order[e["org"]] = sorted(range(len(b)), key=lambda i: (-rel(b[i]), i))
        if s.get("labeled"):
            labeled = [k for k, _ in sorted(s["labeled"], key=lambda kv: -rel(kv[1]))]
            labeled = [k for k in labeled if k not in ("Languages", "Interests")] + [k for k in ("Languages", "Interests") if k in dict(s["labeled"])]
            if category == "ai_automation" or len(re.findall(r"\b(ai|llm|genai|machine learning)\b", t)) >= 8:
                labeled = ["AI & Automation"] + [k for k in labeled if k != "AI & Automation"]   # lead with AI for AI roles
    return {"bullet_order": bullet_order, "labeled_order": labeled,
            "section_order": [s["title"] for s in context.MASTER["sections"]]}


# ---------------------------------------------------------------- 4. outreach drafter
HOOKS = {
    "product": "at Delta I turned station requirements into product specs and process maps",
    "analyst_data": "at Delta I built trackers and cleaned 3,000+ workflow records",
    "ai_automation": "I build with the Claude API and automated bid workflows at Delta",
    "business_systems": "at Delta I automated shift-bid workflows for frontline teams",
    "consulting_strategy": "I've done acquisition research and benchmarking at W. A Investments",
    "finance_tech": "I built DCF and comparable-company analyses as a JPMorgan extern",
}
LOOK_FOR = {
    "product": "product manager", "analyst_data": "data / analytics team member", "ai_automation": "AI or automation team member",
    "business_systems": "business systems analyst", "consulting_strategy": "consultant", "finance_tech": "analyst",
}


def outreach(company, role, category):
    short = re.sub(r"\s*[\(\[].*$", "", role).strip()
    short = short[:60]
    first = os.getenv("CANDIDATE_FIRST_NAME", "Tokunbo")
    uni = os.getenv("CANDIDATE_UNIVERSITY", "Georgia State")
    hook = HOOKS.get(category, "at Delta I automated workflows for frontline teams")
    note = f"Hi! I just applied to the {short} role at {company}. I'm a student at {uni}, and {hook}. I'd like to connect and learn how your team works. - {first}"
    if len(note) > 300:
        note = f"Hi! I just applied to the {short[:40]} role at {company}. I'm a student at {uni} and would like to connect and learn how your team works. - {first}"
    look = ["campus / university recruiter", f"Georgia State or MLT alum at {company}", LOOK_FOR.get(category, "team member in that function")]
    return {"look_for": look, "search_keywords": "university recruiter OR \"Georgia State\"", "note": note, "hook": hook}


# ---------------------------------------------------------------- 5. inbox analyst
KINDS = [
    ("offer", r"offer (letter|of employment)|pleased to (offer|extend)|we('d| would) like to offer"),
    ("interview", r"\binterview|schedule (a|your) (call|time|conversation|chat)|phone screen|meet with (our|the) team|availability for|superday"),
    ("assessment", r"assessment|hirevue|codility|hackerrank|codesignal|online test|coding challenge|pymetrics|case study"),
    ("rejection", r"unfortunately|not (be )?moving forward|other candidates|no longer (being )?considered|position has been filled|"
                  r"decided to pursue|will not be proceeding|regret to inform"),
    ("confirmation", r"thank you for (applying|your application|your interest)|application (was |has been )?received|"
                     r"we('ve| have) received your application"),
]
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"


def _deadline(text, sent):
    t = text.lower()
    base = datetime.date.fromisoformat(sent) if sent else datetime.date.today()
    m = re.search(rf"(?:by|before|due|deadline[:\s]*|complete .{{0,30}} by)\s+(?:\w+day,?\s+)?({MONTHS})\.?\s+(\d{{1,2}})", t)
    if m:
        try:
            d = datetime.datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {base.year}", "%b %d %Y").date()
            return (d.replace(year=d.year + 1) if d < base - datetime.timedelta(days=30) else d).isoformat()
        except ValueError:
            pass
    m = re.search(r"(?:by|before|due)\s+(\d{1,2})/(\d{1,2})", t)
    if m:
        try:
            return datetime.date(base.year, int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            pass
    m = re.search(r"within (\d{1,3}) (hours|days)", t)
    if m:
        n = int(m.group(1))
        return (base + datetime.timedelta(days=n // 24 if m.group(2) == "hours" else n)).isoformat()
    return ""


def read_email(sender, subject, body, sent=""):
    text = f"{subject}\n{body}"
    kind = next((k for k, pat in KINDS if re.search(pat, text, re.I)), "other")
    about = kind != "other" or bool(re.search(r"your application|candidate|recruit|position|role", text, re.I))
    if re.search(r"unsubscribe|job alert|jobs you may|recommended jobs|newsletter", text, re.I) and kind in ("other", "confirmation"):
        about, kind = False, "other"
    times = re.findall(rf"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?(?:(?:{MONTHS})\.?\s+\d{{1,2}},?\s+)?(?:at\s+)?\d{{1,2}}(?::\d{{2}})?\s?(?:am|pm)(?:\s?(?:et|est|edt|ct|pt))?", text, re.I)
    deadline = _deadline(text, sent)
    company = re.sub(r"[<\"].*$", "", sender).strip() or sender
    action = {"assessment": "Complete the assessment", "interview": "Reply with your availability",
              "offer": "Review the offer", "rejection": "", "confirmation": ""}.get(kind, "")
    soon = bool(deadline) and deadline <= (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    return {"is_about_application": about, "company": company[:60], "kind": kind, "deadline": deadline,
            "proposed_times": [x.strip() for x in times[:5]], "action_needed": action,
            "urgent": about and (kind in ("assessment", "interview", "offer") or soon),
            "summary": subject[:120], "engine": "local"}


# ---------------------------------------------------------------- 6. site fixer (rules only)
def _gpa_rule(label):
    m = re.search(r"gpa[^0-9]{0,40}(\d\.\d{1,2})", label, re.I)
    if not m:
        return None
    need = float(m.group(1))
    yes = 3.35 >= need if re.search(r"above|at least|minimum|or (higher|greater|better)|exceed", label, re.I) else None
    if yes is None:
        return None
    return ("Yes" if yes else "No"), ("^Yes" if yes else "^No"), "Cumulative GPA: 3.35"


FACT_MAP = [  # (question regex, answer, option regex, fact it comes from)
    (r"pursu\w* .{0,30}(bachelor|undergraduate)|currently (an? )?(undergraduate|college) student|currently enrolled",
     "Yes", "^Yes", "Bachelor of Business Administration"),
    (r"expected graduation|graduation (date|month|year|term)|when (do|will) you graduate", "May 2028", "May 2028|2028",
     "Expected Graduation: May 2028"),
    (r"(current )?(year in school|class standing|academic (year|level|standing)|school year|year of study)|what year .{0,25}in (school|college)",
     "Junior", "Junior|Third|3rd",
     "Undergraduate junior"),
    (r"authori[sz]ed to work|legally (eligible|authori[sz]ed)|eligible to work in the (u\.?s|united states)", "Yes", "^Yes",
     "authorized to work in the US"),
    (r"sponsor", "No", "^No", "never needs visa sponsorship"),
    (r"u\.?s\.? citizen|citizen of the united states", "Yes", "^Yes", "US citizen"),
    (r"at least 18|18 years|over 18|age of 18", "Yes", "^Yes", "Undergraduate junior"),
    (r"willing to relocate|open to relocat|relocation", "Yes", "^Yes", "Open to relocating"),
    (r"\b(major|field of study|area of study|concentration)\b", "Computer Information Systems",
     "Computer Information Systems|Information Systems|Management Information", "Computer Information Systems"),
    (r"(school|university|college|institution) (name|attending)|which (school|university)", "Georgia State University",
     "Georgia State", "Georgia State University"),
    (r"transcript|official or unofficial transcript|provide.*transcript", "Yes", "^Yes", "Able to provide official or unofficial academic transcripts upon request."),
    (r"documentation establishing.*(identity|right to work)|identity and right to work|right to work in the country", "Yes", "^Yes", "authorized to work in the US"),
    (r"current us status|select your current us status", "U.S. Citizen", "U\\.?S\\.? Citizen|Citizen", "US citizen"),
    (r"current enrollment class status|enrollment.*class.*status|class status", "Junior", "Junior|Undergraduate", "Undergraduate junior"),
    (r"signed any agreement with a current or former employer|agreement.*not.*compete|restrictive covenant", "No", "^No", "No non-compete agreements"),
    (r"held an active u\\.?s\\.? security clearance|active.*clearance", "No", "^No", "Never held a U.S. security clearance"),
    (r"need.*sponsorship|immigration support|immigration filing", "No", "^No", "never needs visa sponsorship"),
    (r"personal financial interest|financial interest in firms", "No", "^No", "No conflict of interest or personal financial interest"),
    (r"non-?compete agreement|have a non-?compete", "No", "^No", "No non-compete agreements"),
    (r"^\s*work\s+authorization", "U.S. Citizen", "U\\.?S\\.? Citizen|Citizen|^Yes", "US citizen"),
    (r"licensed professional.*license infractions|misconduct.*investigations", "No", "^No", "No professional license infractions"),
    (r"maintain any commitments to another employer|engaged in any other outside employment", "No", "^No", "Will not maintain outside employment"),
    (r"desired (annual )?salary", "60000", "", "Salary expectation is flexible and open"),
    (r"secondary contact number", re.sub(r"\D", "", os.getenv("CANDIDATE_PHONE", "5550199")), "", "Secondary contact number from candidate profile"),
    (r"previously worked for (?:this|our|the) organization|previously (?:been )?contracted with|former employee of|previously worked for|ever been employed by|current/former.*contractor.*or former.*employee",
     "No", "^No", "Previously employed by Delta Air Lines and W. A. Investments. Never previously worked, interned, or contracted for any other company or organization."),
    (r"dispute resolution program|arbitration and mediation agreement|mandatory arbitration.*agreement",
     "I agree", "^I agree|^I accept|^Yes|Agree", "Agrees to mandatory arbitration and dispute resolution program terms."),
    (r"how often.*(?:in days)?.*receive an alert|alert frequency|job alert.*(?:days|frequency)",
     "1", "^1$|Daily", "Preferred job alert frequency is as frequent as possible (1 day or Daily)."),
    (r"(?:if yes,?\s*)?(?:please provide )?visa type and expiration date|visa type.*expiration",
     "N/A", "N/A|Not Applicable|U\\.?S\\.? Citizen", "U.S. Citizen with no visa requirement: visa type and expiration date are not applicable (N/A)."),
    (r"served.*in any active.*guard.*reserve.*military|currently serving in.*military|military spouse|domestic partner.*military",
     "No", "^No", "has never served in the U.S. military; not a military spouse."),
]


def rule_for_question(label):
    """Returns (pattern, answer, option, fact) for a question the facts answer, else None."""
    g = _gpa_rule(label)
    if g:
        pat = re.escape(re.sub(r"\s+", " ", label.strip(" *:?")).lower()[:60])
        return pat, g[0], g[1], g[2]
    for pat, ans, opt, fact in FACT_MAP:
        if re.search(pat, label, re.I):
            return pat, ans, opt, fact
    return None
