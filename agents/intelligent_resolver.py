"""
Intelligent Autonomous Form Question Resolver (Job Deck AI Brain 2.0)
Inspired by AIHawk & modern autonomous ATS application agents.
Grounded in the active candidate's master resume and .env facts (candidate.py).

Architecture:
1. Tier 1: Local Fast Vector & Rule Match (0 tokens, <2ms) via profile.json and semantic embeddings.
2. Tier 2: Candidate Invariant Engine (0 tokens, <1ms) mapping standard ATS screening facts.
3. Tier 3: OpenRouter model reasoning (agents/openrouter.py) for novel, behavioral, or complex questions.
4. Tier 4: Resume-Grounded Local Synthesis Fallback (0 tokens) ensuring 100% resilience.
5. Self-Healing Memory: Automatically persists resolved answers into profile.json and answers.json
   so future occurrences resolve instantly with 0 tokens.
"""
import os
import re
import json
import time
import urllib.request
import urllib.error
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from . import context
from .context import C  # the active candidate (JOBDEC_HOME): facts, profile.json, data folder

PROFILE_PATH = C.PROFILE
ANSWERS_PATH = C.DATA / "answers.json"

# invariant name -> CANDIDATE_<KEY> in the candidate's .env; missing facts are left out, never filled in
INVARIANT_FACTS = {
    "full_name": "FULL_NAME", "first_name": "FIRST_NAME", "last_name": "LAST_NAME", "email": "EMAIL",
    "phone": "PHONE", "phone_device_type": "PHONE_DEVICE_TYPE", "address": "ADDRESS_LINE_1", "city": "CITY",
    "county": "COUNTY", "state": "STATE", "state_code": "STATE_CODE", "zip_code": "ZIP_CODE", "country": "COUNTRY",
    "linkedin": "LINKEDIN_URL", "github": "GITHUB_URL", "school": "UNIVERSITY", "degree": "DEGREE", "major": "MAJOR",
    "current_standing": "CURRENT_YEAR", "graduation_date": "EXPECTED_GRAD_DATE", "gpa": "GPA",
    "citizenship": "CITIZENSHIP_COUNTRY", "us_citizen": "US_CITIZEN", "work_authorization": "LEGALLY_AUTHORIZED_US",
    "requires_sponsorship": "REQUIRES_SPONSORSHIP", "future_sponsorship": "WILL_REQUIRE_FUTURE_SPONSORSHIP",
    "security_clearance": "SECURITY_CLEARANCE", "age_18_or_older": "AGE_18_OR_OLDER", "date_of_birth": "DATE_OF_BIRTH",
    "non_compete": "NON_COMPETE_RESTRICTIONS", "previous_employment_at_target": "PREVIOUSLY_EMPLOYED_AT_TARGET",
    "relatives_at_target": "RELATIVES_AT_TARGET", "gender": "GENDER", "pronouns": "PRONOUNS",
    "hispanic_latino": "HISPANIC_LATINO", "race_ethnicity": "RACE", "veteran_status": "VETERAN_STATUS",
    "disability_status": "DISABILITY_STATUS", "willing_to_relocate": "WILLING_TO_RELOCATE",
    "able_to_commute": "ABLE_TO_COMMUTE", "referral_source": "REFERRAL_SOURCE",
}


def get_resume_text() -> str:
    """Plain text of the active candidate's master resume (agents/context.py MASTER)."""
    return context.resume_text()


def get_profile_invariants() -> Dict[str, str]:
    """The active candidate's verified facts from their .env; unknown facts are absent."""
    facts = {k: C.fact(v) for k, v in INVARIANT_FACTS.items()}
    return {k: v for k, v in facts.items() if v}


def _best_resume_line(keywords: List[str]) -> Optional[Tuple[str, str]]:
    """(org, bullet) of the resume bullet sharing the most keywords, or None when none matches."""
    best, best_hits = None, 0
    for sec in context.MASTER.get("sections", []):
        for e in sec.get("entries", []):
            for b in e.get("bullets", []):
                hits = sum(k in b.lower() for k in keywords)
                if hits > best_hits:
                    best, best_hits = (re.sub(r"<[^>]+>", "", e.get("org", "")).strip(), b), hits
    return best



def load_profile_rules() -> List[Dict[str, Any]]:
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            return data.get("rules", [])
        except Exception:
            return []
    return []


def save_learned_rule(question: str, answer: str, option_pattern: Optional[str] = None):
    """Logs an AI-resolved answer to answers.json (audit trail; profile.json holds only the candidate's rules)."""
    try:
        clean_q = question.strip()
        if not clean_q or not answer:
            return

        # AI answers are logged, not added to profile.json: saved at the top of the rules they outranked the
        # candidate's verified answers and kept AI mistakes forever ('Winter 2027', 'Search C3 AI' -> name)
        # 2. Append to answers.json
        answers_dict = {}
        if ANSWERS_PATH.exists():
            try:
                answers_dict = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
            except Exception:
                answers_dict = {}

        answers_dict[clean_q] = {
            "answer": answer,
            "option": option_pattern,
            "date": str(date.today())
        }
        ANSWERS_PATH.write_text(json.dumps(answers_dict, indent=2), encoding="utf-8")
        print(f"  [AI Brain Learner] Cached rule: '{clean_q[:50]}' -> '{answer}'")
    except Exception as e:
        print(f"[AI Brain Learner Error] {e}")


def pick_best_matching_option(answer_text: str, options: List[str]) -> Optional[str]:
    """Fuzzy matches an answer string against an ATS dropdown/radio option list."""
    if not options or not answer_text:
        return None

    ans_low = answer_text.strip().lower()
    clean_opts = [str(o).strip() for o in options if str(o).strip()]

    # 1. Exact match
    for opt in clean_opts:
        if opt.lower() == ans_low:
            return opt

    # 2. Whole-word match
    pattern = rf"\b{re.escape(ans_low)}\b"
    for opt in clean_opts:
        if re.search(pattern, opt, re.I):
            return opt

    # 3. Yes / No normalization
    if ans_low in ["yes", "true", "y"]:
        for opt in clean_opts:
            if re.match(r"^(yes|authorized|eligible|i agree|agree|consent)\b", opt, re.I):
                return opt
    if ans_low in ["no", "false", "n"]:
        for opt in clean_opts:
            if re.match(r"^(no|not|neither|decline|none)\b", opt, re.I):
                return opt

    # 4. The shared strict matcher (aliases, dates, months). No token overlap: one shared word picked
    #    "A person lawfully admitted for permanent residence" for "U.S. person" on 9 Anduril applications.
    from agents import options as OPTS
    return OPTS.resolve("", answer_text, clean_opts, semantic_ok=False)


def synthesize_from_resume(
    label: str,
    field_type: str = "text",
    options: Optional[List[str]] = None,
    company: str = "",
    role: str = ""
) -> Optional[Dict[str, Any]]:
    """Zero-Token Local Resume-Grounded Synthesis Fallback. None when nothing the candidate stated answers it."""
    lab_low = label.lower()

    if options:
        # Self-identification questions: only the candidate's own stated answer, else leave for a human
        facts = get_profile_invariants()
        for pat, key in ((r"gender\b", "gender"), (r"race|ethnic", "race_ethnicity"),
                         (r"disabilit", "disability_status"), (r"veteran", "veteran_status")):
            if re.search(pat, lab_low):
                m = pick_best_matching_option(facts[key], options) if facts.get(key) else None
                if m:
                    return {"answer": m, "option": f"^{re.escape(m)}$", "confidence": "high", "src": "resume_synthesis"}
                return None

        # Accepting terms is the only option answered without a stated fact. Experience, legal and
        # employment questions were answered "Yes"/"No"/first option here and went out false (2026-11-10:
        # "Carnegie Mellon University", "Yes" to a referral program, "Yes" to humanoid-robot experience).
        if re.search(r"\b(i accept|i agree|i acknowledge|consent to|agree to the)\b", lab_low):
            m = pick_best_matching_option("Yes", options) or next((o for o in options if re.search(r"accept|agree|acknowledge", str(o), re.I)), None)
            if m:
                return {"answer": m, "option": f"^{re.escape(m)}$", "confidence": "high", "src": "resume_synthesis"}
        return None

    if re.search(r"\b(resume|cv|cover letter|transcript|upload|attach)", lab_low):
        return None  # a file field's text box never gets prose
    # site search boxes and "if other / please specify" follow-ups got the pitch on 2026-11-11 ("Search",
    # "START YOUR JOB SEARCH HERE"): prose only for a real open-ended question
    if re.search(r"\b(search|keyword|filter)\b|^\s*if\b|please (specify|list)|if other", lab_low):
        return None
    if re.search(r"licen[cs]e|certif", lab_low) and not re.match(r"\s*(do|does|are|is|have|has)\b", lab_low):
        # the candidate's own certificate lines (William Blair's "Licenses/Certifications" got the pitch)
        certs = [re.split(r"\s*\|\s*", l.strip(" -*•"))[0] for l in get_resume_text().splitlines()
                 if re.search(r"certificat|certified|license", l, re.I) and len(l.strip()) < 140 and not l.lstrip().startswith("#")]
        return {"answer": "; ".join(dict.fromkeys(certs)) or "None", "option": None, "confidence": "high", "src": "resume_synthesis"}
    # yes/no questions ("Do you identify as disabled?") never get prose: William Blair, 2026-11-11
    if re.match(r"\s*(do|does|are|is|have|has|will|would|can|could|did|were|was|should|if)\b", lab_low):
        return None
    if not (field_type == "textarea" or
            re.match(r"\s*(what|why|how|describe|tell|explain|share|please (describe|explain|tell|share)|in your own words)\b", lab_low)):
        return None

    # Open-ended responses: the candidate's own pitch / skills facts, or a resume bullet quoted as written
    def _said(ans, conf="high"):
        return {"answer": ans, "option": None, "confidence": conf, "src": "resume_synthesis"} if ans else None

    if any(k in lab_low for k in ["why", "interest", "seek", "apply for this role"]):
        return _said(C.fact("ELEVATOR_PITCH"))

    if any(k in lab_low for k in ["strength", "greatest strength", "skills"]):
        top = C.fact("TOP_SKILLS")
        return _said(f"My core strengths are {top}." if top else "")

    for keys in (["iam", "identity", "active directory", "provisioning", "access"],
                 ["siem", "sentinel", "threat", "incident", "detection"],
                 ["troubleshoot", "support", "technical error", "fault"]):
        if any(k in lab_low for k in keys):
            hit = _best_resume_line(keys + re.findall(r"[a-z]{4,}", lab_low))
            if hit:
                return _said(f"At {hit[0]}, I {hit[1][:1].lower() + hit[1][1:]}." if hit[0] else hit[1])

    # General fallback: the candidate's own pitch, or nothing (a human answers it)
    return _said(C.fact("ELEVATOR_PITCH"), "medium")


def resolve_with_ai(
    label: str,
    field_type: str = "text",
    options: Optional[List[str]] = None,
    company: str = "",
    role: str = ""
) -> Optional[Dict[str, Any]]:
    """Asks the OpenRouter model (agents/openrouter.py) to answer from the resume and facts. None on any failure."""
    from agents import openrouter
    if not openrouter.available():
        return None

    resume = get_resume_text()
    facts = get_profile_invariants()
    facts_str = "\n".join([f"- {k}: {v}" for k, v in facts.items()] + [f"- {s}" for s in C.standing_facts()])

    opts_str = ""
    valid_opts = []
    if options:
        valid_opts = [str(o).strip() for o in options if str(o).strip() and not re.match(r"^(select|choose|--)", str(o), re.I)][:60]
        if valid_opts:
            opts_str = f"Available Options (Select EXACTLY ONE, copied verbatim; if none is true for the candidate, answer \"\"):\n" + "\n".join(f"  * {o}" for o in valid_opts)

    system_prompt = (
        f"You are an expert AI Form Question Resolver for job applications, representing candidate {facts.get('full_name', 'the candidate')}.\n"
        "Your task is to accurately and concisely answer the application question using ONLY the candidate's real resume and verified facts.\n\n"
        "=== CANDIDATE MASTER RESUME ===\n"
        f"{resume}\n"
        "==============================\n\n"
        "=== CANDIDATE INVARIANTS ===\n"
        f"{facts_str}\n"
        "============================\n\n"
        "STRICT ANSWERING RULES:\n"
        "1. Never hallucinate facts or numbers not in the resume.\n"
        "2. If options are provided, your answer MUST match one of the available options exactly.\n"
        "3. For Yes/No and personal questions (citizenship, sponsorship, age, demographics, legal history): use ONLY the CANDIDATE INVARIANTS; if the fact is not listed, return an empty answer with confidence \"low\".\n"
        "4. For technical experience: claim only what the resume shows.\n"
        "5. For open-ended questions: write 1-3 concise, authentic, professional sentences in first person.\n"
        "Output strictly valid JSON with this format:\n"
        '{"answer": "exact answer value", "option": "matching option if dropdown/radio else null", "confidence": "high"|"medium"|"low", "rationale": "one sentence reason"}'
    )

    user_prompt = (
        f"Company: {company or 'Target Company'}\n"
        f"Role: {role or 'Internship'}\n"
        f"Field Type: {field_type}\n"
        f"Question Label: {label}\n"
        f"{opts_str}\n"
    )

    try:
        raw_text, _ = openrouter.chat(system_prompt, [{"role": "user", "content": user_prompt}],
                                      max_tokens=1200, temperature=0.1, json_mode=True, timeout=15)  # model spends ~200 tokens thinking first
        parsed = json.loads(raw_text)
    except (openrouter.OpenRouterError, ValueError):
        return None
    ans = str(parsed.get("answer") or "").strip()
    opt = parsed.get("option")
    if parsed.get("confidence") == "low":  # the model itself says the facts don't support an answer
        return None
    if valid_opts:  # a choice must be one of the real options, never free text the field would reject or misread
        by_norm = {" ".join(o.split()).lower(): o for o in valid_opts}
        chosen = by_norm.get(" ".join(str(opt or ans).split()).lower()) or pick_best_matching_option(str(opt or ans), valid_opts)
        if not chosen:
            return None
        ans, opt = chosen, "^" + re.escape(chosen) + "$"
    return {"answer": ans, "option": opt, "confidence": parsed.get("confidence", "low"),
            "src": "openrouter", "rationale": parsed.get("rationale", "")}



def resolve_field(
    label: str,
    field_type: str = "text",
    options: Optional[List[str]] = None,
    company: str = "",
    role: str = ""
) -> Optional[Dict[str, Any]]:
    """Master Multi-Tier Question Resolver. Call from fill.py to intelligently resolve any ATS field."""
    lab = label.strip()
    if not lab or len(lab) < 2:
        return None

    # (profile.json rules are matched by fill.rule_for before this is called; a second, unguarded substring
    #  match here let a learned 'No' rule answer any label containing 'no')

    # TIER 2: Fast Invariant Check
    lab_low = lab.lower()

    # Fast Language Proficiency Invariant (resolves 50+ language lists in 0ms)
    lang_match = re.search(r"\b(english|spanish|hindi|french|german|mandarin|cantonese|japanese|arabic|portuguese|russian|italian|korean|vietnamese|telugu|marathi|tamil|urdu|gujarati|bengali|lithuanian|khmer|hmong|tagalog|polish|dutch|turkish)\b", lab_low)
    if lang_match:
        lang = lang_match.group(1).lower()
        if lang == "english":
            ans = "Native / Fluent"
            if options:
                ans = pick_best_matching_option("Fluent", options) or pick_best_matching_option("Native", options) or pick_best_matching_option("Professional", options) or pick_best_matching_option("Yes", options) or ans
            return {"answer": ans, "option": f"^{re.escape(ans)}$", "src": "language_invariant", "confidence": "high"}
        else:
            ans = "None"
            if options:
                ans = pick_best_matching_option("None", options) or pick_best_matching_option("Not Applicable", options) or pick_best_matching_option("No proficiency", options) or pick_best_matching_option("No", options) or ans
            return {"answer": ans, "option": f"^{re.escape(ans)}$", "src": "language_invariant", "confidence": "high"}

    # Split Digit Zip Code Fields (e.g. Dropbox / Greenhouse)
    m_zip_digit = re.search(r"(?:zip|postal).*digit\s*([1-5])\b", lab_low)
    if m_zip_digit:
        digit_idx = int(m_zip_digit.group(1))
        zip_str = C.fact("ZIP_CODE")
        if len(zip_str) >= digit_idx:
            ans_char = zip_str[digit_idx - 1]
            return {"answer": ans_char, "option": f"^{ans_char}$", "src": "zip_digit_invariant", "confidence": "high"}

    # Yes/No screening facts: answered only when the candidate's .env states them (no age is ever derived)
    for pat, key in ((r"authorized.*to.*work|legal(ly)?.*authoriz|right.*to.*work", "LEGALLY_AUTHORIZED_US"),
                     (r"require.*sponsor|visa.*sponsor|sponsorship.*future", "REQUIRES_SPONSORSHIP"),
                     (r"at least 18|18 or older|over 18", "AGE_18_OR_OLDER"),
                     (r"date of birth|birth date|\bdob\b|birthdate", "DATE_OF_BIRTH"),
                     (r"non-?compete|non-?solicit", "NON_COMPETE_RESTRICTIONS"),
                     (r"security.*clearance", "SECURITY_CLEARANCE")):
        if re.search(pat, lab_low):
            ans = C.fact(key)
            if ans:
                return {"answer": ans, "option": rf"^{re.escape(ans)}\b", "src": "invariant", "confidence": "high"}
            break

    # TIER 3: DeepMind Gemini Reasoning Engine
    print(f"  [AI Brain Reasoning] Evaluating novel field '{lab[:60]}' for {company}...")
    ai_res = resolve_with_ai(lab, field_type=field_type, options=options, company=company, role=role)
    if ai_res and ai_res.get("answer"):
        # only high-confidence choices become rules: an essay names this company and would be reused at the next one
        if ai_res.get("confidence") == "high" and options:
            save_learned_rule(lab, ai_res["answer"], ai_res.get("option"))
        return ai_res

    # TIER 4: Local Resume-Grounded Synthesis Fallback
    fallback_res = synthesize_from_resume(lab, field_type=field_type, options=options, company=company, role=role)
    if fallback_res and fallback_res.get("answer"):
        # Only persist high-confidence grounded answers, never generic fallback text
        if fallback_res.get("confidence") == "high":
            save_learned_rule(lab, fallback_res["answer"], fallback_res.get("option"))
        return fallback_res

    return None
