"""
AI Response Generator for Job Application Screening Questions.
Generates tailored, concise, and recruiter-ready responses grounded in
the candidate's master resume and candidate playbook.
"""
import json
import os
import pathlib
import re
import urllib.request
import urllib.error

try:  # Agent 3: answers from verified facts first; the rules below are the fallback
    from agents import form_answerer as _FA
except Exception:
    _FA = None

HERE = pathlib.Path(__file__).resolve().parent
CACHE_FILE = HERE / "response_cache.json"

_NAME = os.getenv("CANDIDATE_FULL_NAME", "Candidate")
_UNI = os.getenv("CANDIDATE_UNIVERSITY", "Georgia State University")
_DEG = os.getenv("CANDIDATE_DEGREE_EXACT", os.getenv("CANDIDATE_DEGREE", "BBA Computer Information Systems (AI & Analytics)"))
_GRAD = os.getenv("CANDIDATE_EXPECTED_GRAD_DATE", "May 2028")
_GPA = os.getenv("CANDIDATE_GPA", "3.35")
_LOC = os.getenv("CANDIDATE_LOCATION_TEXT", f"{os.getenv('CANDIDATE_CITY', 'Atlanta')}, {os.getenv('CANDIDATE_STATE', 'GA')}")
_PITCH = os.getenv("CANDIDATE_ELEVATOR_PITCH", "Software engineer and automation builder specializing in agentic workflows, data pipelines, and full-stack systems.")
_EXP = os.getenv("CANDIDATE_PROUDEST_ACHIEVEMENT", "Led the automation of enterprise coordination workflows handling 50,000+ records, cutting manual coordination overhead by 150+ hours.")

CANDIDATE_PROFILE = f"""
Candidate: {_NAME}
Education: {_UNI}, {_DEG}. Expected Graduation: {_GRAD}. GPA: {_GPA}.
Work Authorization: US Citizen, authorized to work in the US, no visa sponsorship required now or in the future.
Location: {_LOC}. Open to relocation, hybrid, and remote.

Key Experience:
1. Enterprise Process Automation & Agentic Systems:
   - {_EXP}
2. Technical & Functional Skills:
   - Tools: Python, SQL, Tableau, Power BI, Advanced Excel, Git, Playwright browser automation.
   - Disciplines: Product management, agentic AI workflows, process automation, requirements documentation, data validation.
"""


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


_LLM_AVAILABLE = None

def call_local_llm(prompt, max_tokens=150, timeout=2):
    """Attempts to call local llama.cpp server at 127.0.0.1:8080/v1/chat/completions."""
    global _LLM_AVAILABLE
    if _LLM_AVAILABLE is False:
        return None
    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are assisting candidate {_NAME} with job application screening questions. "
                    "Write concise, polished, professional answers in first person. "
                    "Never invent experiences or skills not in the candidate profile. "
                    "Keep answers under 3-4 sentences unless explicitly requested otherwise."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _LLM_AVAILABLE = True
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        _LLM_AVAILABLE = False
        return None


def template_fallback(question, company="", role=""):
    """Answers for common open-ended questions, using only facts from the master resume.
    Returns "" when the question doesn't match a known type, so the job pauses/skips and logs it
    instead of pasting a generic paragraph into an unrelated field (e.g. 'County')."""
    q = question.lower()
    co = company or "your organization"
    rl = role or "this role"

    if re.search(r"why (do you want to (work|join)|are you interested|this company|join us|us\b)|interest in (this|the) (role|position|company)", q):
        try:  # a real specific from the posting + a matching resume fact
            from agents import smarts
            specific = smarts.why_answer(company, role)
            if specific:
                return specific
        except Exception:
            pass
        return (
            f"I'm interested in {co} because the {rl} role lines up with the work I've enjoyed most. "
            f"At Delta Air Lines I automated shift-bid workflows handling 50,000+ employee bids, and at W. A Investments "
            f"I delivered a build-vs-buy analysis of payment platforms. I want to keep doing that kind of product and process work."
        )
    if re.search(r"(describe|tell us about|example of|share).*(project|accomplishment|achievement)", q):
        return (
            "At Delta Air Lines I automated shift-selection and bid-processing workflows handling 50,000+ employee bids, "
            "which cut manual coordination by 150+ hours. I also built 6 Excel trackers and produced 10+ process maps "
            "that turned station requirements into product specs and training steps."
        )
    if re.search(r"(challenge|obstacle|difficult situation|conflict)", q):
        return (
            "Before a shift-marketplace platform at Delta Air Lines rolled out more broadly, I cleaned 3,000+ workflow records "
            "and flagged about 2,500 exceptions that needed fixing first. I tracked them in the issue logs I'd built so they "
            "could be resolved before adoption."
        )
    if re.search(r"strength|what (skills|do you bring)", q):
        return (
            "I'm strongest where product work meets automation and data: turning operational requirements into specs, "
            "building trackers and analyses in Excel, SQL and Python, and working through review cycles with stakeholders, "
            "including executive leadership at W. A Investments."
        )
    if re.search(r"short-?term goal|career goal", q):
        return (
            "In the near term I want an internship where I can apply product, process automation and analytics skills to real "
            "business problems while I finish my Computer Information Systems degree at Georgia State (May 2028)."
        )
    if re.search(r"additional information|anything else", q):
        return f"Thank you for considering my application. I'd welcome the chance to talk about how my product and automation experience could help {co}."

    return ""


def pick_best_option(question, options):
    """Picks the most suitable option from a list for multiple choice questions,
    with smart guessing heuristics so forms never get stuck."""
    if not options:
        return ""
    if _FA is not None:
        a = _FA.answer(question, "select", options)
        if a:
            return a
        # "" = agent declined (not in facts); None = agent unavailable -> rules below
    q = question.lower()
    lowered = [str(o).lower() for o in options]

    # STRICT USER CONSTRAINTS: Sponsorship is ALWAYS NO (US Citizen)
    if any(k in q for k in ["sponsor", "visa"]):
        # Compound question: asks if you have unrestricted work authorization OR require sponsorship
        if any(u in q for u in ["unrestricted", "authorized to work", "legally authorized", "eligible to work"]):
            for i, opt in enumerate(lowered):
                if any(kw in opt for kw in ["unrestricted", "authorized", "do not require", "no sponsorship", "citizen", "permanent resident"]):
                    return options[i]
                if re.match(r"^yes\b|^true\b", opt) and "require sponsorship" not in opt:
                    return options[i]
        for i, opt in enumerate(lowered):
            if re.match(r"^no\b|^not required\b", opt):
                return options[i]
        return "No"

    # STRICT USER CONSTRAINTS: Felony, Termination, Relative, Government, Military, Prior employment are ALWAYS NO
    if any(k in q for k in [
        "felon", "convict", "criminal", "terminated", "discharged",
        "relative", "family member", "familial", "romantic", "personal relationship", "friend or relative",
        "prior employee", "previously employed", "currently employed", "directly employed", "former employee",
        "government", "military", "armed forces", "dod", "national defense",
        "conflict of interest", "previously interviewed", "interviewed with", "interviewed before",
        "client", "work at a", "disciplinary", "regulatory agency", "investigation", "sanction"
    ]):
        for i, opt in enumerate(lowered):
            if re.match(r"^no\b|^not applicable\b|^none\b|^false\b", opt):
                return options[i]
        return "No"

    # State / Province -> Georgia / GA
    if any(k in q for k in ["state", "province", "region"]):
        for i, opt in enumerate(lowered):
            if opt in ("georgia", "ga") or re.search(r"^georgia\b|\bga\b", opt):
                return options[i]

    # Affirmative / authorization / willingness / compliance questions -> YES
    if any(k in q for k in [
        "authorized", "eligible", "18 year", "18 or older", "age of 18", "at least 18", "legal right", "right to work",
        "drug", "background", "relocate", "overtime", "weekend", "agree", "acknowledge", "consent", "certify",
        "understand", "willing", "capable", "able to perform", "confirm",
        "available", "travel", "shift", "transportation", "commute", "gpa", "transcript", "driver"
    ]):
        for i, opt in enumerate(lowered):
            if re.match(r"^yes\b|^authorized\b|^eligible\b|^agree\b|^i agree\b|^true\b", opt):
                return options[i]

    # Education / degree
    if any(k in q for k in ["degree", "education", "level of education"]):
        for i, opt in enumerate(lowered):
            if any(b in opt for b in ["bachelor", "undergraduate", "some college", "college"]):
                return options[i]

    # Academic year / classification
    if any(k in q for k in ["year in school", "classification", "class standing", "academic year", "standing"]):
        for i, opt in enumerate(lowered):
            if "junior" in opt or "3rd" in opt or "third" in opt:
                return options[i]

    # Language
    if "language" in q:
        for i, opt in enumerate(lowered):
            if "english" in opt or "fluent" in opt or "native" in opt:
                return options[i]

    # Demographics: Decline to self-identify across gender, race, disability, veteran
    if any(k in q for k in ["gender", "race", "ethnicity", "disability", "veteran", "orientation", "hispanic", "latino"]):
        for i, opt in enumerate(lowered):
            if any(d in opt for d in ["decline", "prefer not", "choose not", "not to disclose", "i do not wish", "do not wish"]):
                return options[i]

    # Referral / How did you hear about us
    if re.search(r"hear about|\bsource\b|\breferral\b|how did you find", q):  # not "Human Resource suppliers"
        for i, opt in enumerate(lowered):
            if any(s in opt for s in ["linkedin", "company website", "job board", "internet", "career site"]):
                return options[i]

    # General Yes/No questions fallback:
    # If question contains restrictive/investigative terms, guess "No"
    if any(neg in q for neg in ["lawsuit", "investigation", "disciplinary", "suspended", "misconduct", "violation", "sanction", "debarred"]):
        for i, opt in enumerate(lowered):
            if re.match(r"^no\b|^none\b|^false\b", opt):
                return options[i]

    # If it's a binary Yes/No field, default to Yes (most are affirmative requirements)
    for i, opt in enumerate(lowered):
        if re.match(r"^yes\b|^true\b", opt):
            return options[i]
    for i, opt in enumerate(lowered):
        if re.match(r"^no\b|^false\b", opt):
            return options[i]

    # Fallback guess: pick first non-placeholder option
    for i, opt in enumerate(options):
        clean = str(opt).strip().lower()
        if clean and not any(p in clean for p in ["select", "choose", "please select", "-- select --"]):
            return options[i]

    return options[0] if options else ""


try:
    from brain.resolver import FastResolver
    from brain.vault import get_vault
except Exception:
    try:
        from .brain.resolver import FastResolver
        from .brain.vault import get_vault
    except Exception:
        FastResolver = None
        get_vault = None

def generate_response(question_label, field_type="text", options=None, company="", role=""):
    """Main entrypoint for dynamic question answering with smart guessing."""
    clean_label = re.sub(r"[\*\:]+", "", question_label).strip()

    # 0. Check Agent Brain Dynamic Overrides & Zero-Token Fast Resolver
    if get_vault:
        override = get_vault().get_field_override(clean_label)
        if override:
            return override

    if FastResolver:
        fast_ans = FastResolver.resolve(clean_label, options)
        if fast_ans:
            return fast_ans

    cache = load_cache()

    cache_key = f"{company.lower()}:{clean_label.lower()}"
    if cache_key in cache and cache[cache_key]:
        return cache[cache_key]

    if (field_type in ("listbox", "select", "radio", "dropdown", "yesno") or options) and options:
        choice = pick_best_option(clean_label, options)
        if choice:
            cache[cache_key] = choice
            save_cache(cache)
        return choice

    if _FA is not None:
        a = _FA.answer(clean_label, field_type, None, company, role)
        if a is not None:          # agent ran: use its answer, or nothing if facts don't cover it
            if a:
                cache[cache_key] = a
                save_cache(cache)
            return a

    # Fast template / keyword heuristics first (0ms latency)
    ans = template_fallback(clean_label, company=company, role=role)

    # Keyword heuristics for specific text fields
    if not ans:
        q = clean_label.lower()
        # Screening / Yes-No keywords
        if any(k in q for k in [
            "felon", "convict", "criminal", "terminated", "discharged",
            "relative", "family member", "familial", "romantic", "personal relationship", "friend or relative",
            "prior employee", "previously employed", "currently employed", "directly employed", "former employee",
            "conflict of interest", "previously interviewed", "interviewed with", "interviewed before",
            "require sponsorship", "need sponsorship", "now or in the future require", "client"
        ]):
            ans = "No"
        elif any(k in q for k in [
            "18", "authorized", "eligible", "legal right", "right to work", "background check",
            "agree", "consent", "certify", "understand", "willing", "able to perform", "driver"
        ]):
            ans = "Yes"
        elif any(k in q for k in ["salary", "compensation", "pay", "rate", "hourly", "expectation"]):
            if any(h in q for h in ["hourly", "hour", "dollar amount", "no decimal"]):
                ans = "35"
            else:
                ans = "Open / Negotiable"
        elif any(k in q for k in ["gpa", "grade point"]):
            ans = "3.35"
        elif any(k in q for k in ["graduat"]):
            ans = "05/2028"
        elif any(k in q for k in ["start date", "availability", "available"]):
            ans = os.getenv("CANDIDATE_AVAILABLE_START_DATE", "06/01/2027")
        elif any(k in q for k in ["notice period", "notice required", "your notice"]):
            ans = "2 weeks"
        elif "county" in q:
            ans = os.getenv("CANDIDATE_COUNTY", "Fulton")
        elif "city" in q:
            ans = os.getenv("CANDIDATE_CITY", "Atlanta")
        elif re.search(r"\bstate\b", q) or "province" in q:
            ans = os.getenv("CANDIDATE_STATE", "Georgia")
        elif any(k in q for k in ["zip", "postal"]):
            ans = os.getenv("CANDIDATE_ZIP_CODE", "30303")
        elif any(k in q for k in ["phone", "sms", "mobile", "cell"]):
            ans = re.sub(r"\D", "", os.getenv("CANDIDATE_PHONE", "5550199"))
        elif re.search(r"\b(?:date|dob|birth|graduation|graduating|calendar|signature)\b", q) and re.search(r"\bday\b", q) and not re.search(r"day-to-day|day to day|everyday|workday|holiday", q):
            ans = "01"
        elif re.search(r"\b(?:date|dob|birth|graduation|graduating|calendar)\b", q) and re.search(r"\bmonth\b", q) and not re.search(r"months? of experience|per month|a month", q):
            ans = "06"
        elif re.search(r"\b(?:date|dob|birth|graduation|graduating|calendar)\b", q) and re.search(r"\byear\b", q) and not re.search(r"years? of experience", q):
            ans = "2027"
        elif any(k in q for k in ["signature", "sign here", "type your name", "full legal name"]):
            ans = os.getenv("CANDIDATE_FULL_NAME", "Candidate")
        elif any(k in q for k in ["twitter", "x handle", "facebook", "instagram", "social media", "blog"]):
            return ""
        elif any(k in q for k in ["linkedin", "linkedin url"]):
            ans = os.getenv("CANDIDATE_LINKEDIN_URL", "https://www.linkedin.com")
        elif any(k in q for k in ["website", "portfolio", "url"]):
            ans = os.getenv("CANDIDATE_PORTFOLIO_URL", os.getenv("CANDIDATE_LINKEDIN_URL", "https://www.linkedin.com"))
        elif "github" in q:
            ans = os.getenv("CANDIDATE_GITHUB_URL", "https://github.com")
        elif re.search(r"\b(?:referred by|employee referral|referral name|name of referrer|who referred you)\b", q):
            if company:
                try:
                    from brain.knowledge_graph import get_kg
                    paths = get_kg().find_referral_paths(company)
                    if paths and paths[0].get("warmth_score", 0) >= 30:
                        ans = paths[0]["name"]
                except Exception:
                    pass
            if not ans:
                ans = "N/A"

    # Try local LLM for open-ended questions if still unanswered (with short timeout)
    if not ans:
        kg_evidence = []
        try:
            from brain.knowledge_graph import get_kg
            ev_list = get_kg().graph_rag_evidence(clean_label, top_k=2)
            kg_evidence = [f"- {e.get('text') or e.get('role')}" for e in ev_list]
        except Exception:
            pass

        evidence_block = ("\nRelevant Verified Project Facts:\n" + "\n".join(kg_evidence) + "\n") if kg_evidence else ""

        prompt = (
            f"Job Application Question for {company or 'the company'} ({role or 'Internship'}):\n"
            f"\"{clean_label}\"\n\n"
            f"Context from Candidate Profile:\n{CANDIDATE_PROFILE}{evidence_block}\n"
            f"Write a concise, natural, professional answer (2-3 sentences max):"
        )
        ans = call_local_llm(prompt, max_tokens=120, timeout=3)

    # Universal professional fallback guess if still empty
    if not ans:
        q = clean_label.lower()
        LANGUAGES = (
            "dutch", "hindi", "arabic", "danish", "turkish", "portuguese", "hebrew", "swedish", "norwegian",
            "italian", "vietnamese", "tagalog", "khmer", "hmong", "telugu", "bengali", "marathi", "urdu",
            "gujarati", "lithuanian", "korean", "polish", "spanish", "french", "german", "mandarin",
            "cantonese", "japanese", "russian"
        )
        if any(lang in q for lang in LANGUAGES) and not any(k in q for k in ["programming", "scripting", "software", "code"]):
            ans = "None"
        elif re.search(r"^(are|do|have|will|can|is|did|should)\b|\b(yes|no)\b|select one", q):
            ans = "Yes"
        else:
            ans = (
                f"As a Computer Information Systems student at Georgia State University, "
                f"I have led process automation and data analysis projects at Delta Air Lines and W. A Investments. "
                f"I am eager to contribute my technical and problem-solving skills to {company or 'this role'}."
            )

    # Clean up output
    ans = (ans or "").strip(' "\'\n\r')
    if ans:
        cache[cache_key] = ans
        save_cache(cache)
    return ans


if __name__ == "__main__":
    # Self-test
    test_q = "Why are you interested in this position at The Home Depot?"
    print("Testing answer generation for:", test_q)
    print("Response:\n", generate_response(test_q, company="The Home Depot", role="Product Management Intern"))

