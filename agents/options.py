"""
Option picker: picks the right option from a select / radio / listbox based on
the answer string, field label, and strategy. Handles synonyms, fuzzy matches,
negatives ("do not consent"), and country/state dropdowns.
"""
import difflib, re

# labels that are binary yes/no questions (not multi-choice)
YESNO_LABELS = re.compile(
    r"\b(sponsorship|authorized|legally authorized|require.*sponsor|authorized.*work|"
    r"18.*older|age.*18|felony|convicted|background.*check|drug.*screen|"
    r"terms|consent|agree|certif|signature|confirm)\b", re.I
)

# options that mean "this is a placeholder, don't pick it"
PLACEHOLDER = re.compile(
    r"^(select|choose|please select|--|none|n/a|- select -|select one|select an option)\b", re.I
)

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
ALIASES = [{"united states", "united states of america", "usa", "us", "u.s.", "u.s.a.", "america", "united states of america (+1)", "(+1) united states of america", "united states (+1)", "(+1) united states"},
           {"georgia", "ga"},
           {"kennesaw state university", "kennesaw state", "ksu", "kennesaw", "georgia state university", "georgia state", "gsu"},
           {"bachelor's degree", "bachelors", "bachelor's", "bachelor", "undergraduate", "bachelor's (in progress)", "bachelor of business administration", "bba"},
           {"senior", "4th year", "fourth year", "junior", "3rd year", "third year"},
           {"cybersecurity", "cyber security", "information security", "infosec", "computer information systems", "information systems", "cis"}]
YES = re.compile(r"^\s*(yes|y|true|i am|i do|i will|i have|i can|correct|i consent|consent|i agree|agree|accept)\b", re.I)
NO = re.compile(r"^\s*(no|n|false|i am not|i do not|i don'?t|i will not|i won'?t|i have not|i can'?t|i cannot|i do not consent|decline|opt out|i opt out)\b(?!.*(?:results|matching|options|records|available))", re.I)

# common label categories -> candidate answers
FACTS = {
    "gender": ("Male", r"\bmale\b(?!.*fe)"),
    "race": ("Black or African American", r"\b(black|african american)\b"),
    "veteran": ("I am not a protected veteran", r"not a (protected )?veteran|non-veteran|no\b"),
    "disability": ("No, I don't have a disability", r"no.*disability|not.*disab|i do not have a disability"),
    "hispanic": ("No", r"^no\b"),
    "work_auth": ("Yes", r"^yes\b"),
    "sponsorship": ("No", r"^no\b"),
    "clearance": ("No", r"^no\b|none"),
}


def resolve(label: str, answer: str, options: list, rule_option_pat: str = None) -> str:
    """Pick the best option from `options` for `answer` given `label` and optional regex."""
    if not options:
        return ""
    clean_opts = [o for o in options if o and not PLACEHOLDER.search(o.strip())]
    if not clean_opts:
        return ""

    ans_str = str(answer or "").strip()
    ans_lower = ans_str.lower()
    lbl_lower = (label or "").lower()

    # 1. explicit rule pattern
    if rule_option_pat:
        try:
            pat = re.compile(rule_option_pat, re.I)
            for o in clean_opts:
                if pat.search(o.strip()):
                    return o
        except re.error:
            pass

    # 2. yes/no intent
    is_yes = bool(YES.search(ans_lower))
    is_no = bool(NO.search(ans_lower))
    if is_yes and not is_no:
        # Avoid false matches like "Results (0)" or "No matching records"
        for o in clean_opts:
            if YES.search(o.strip()) and not NO.search(o.strip()):
                return o
    if is_no and not is_yes:
        for o in clean_opts:
            if NO.search(o.strip()) and not YES.search(o.strip()):
                return o

    # 3. exact match (case-insensitive)
    for o in clean_opts:
        if o.strip().lower() == ans_lower:
            return o

    # 4. aliases (US / Georgia / CIS / etc)
    for alias_set in ALIASES:
        if ans_lower in alias_set:
            for o in clean_opts:
                if o.strip().lower() in alias_set:
                    return o

    # 5. whole-word containment (prefer starts-with)
    for o in clean_opts:
        ol = o.strip().lower()
        if ol.startswith(ans_lower) or re.search(r"(?<![a-z])" + re.escape(ans_lower) + r"(?![a-z])", ol):
            return o

    # 6. answer contains the option ("United States of America" -> "United States")
    for o in clean_opts:
        ol = o.strip().lower()
        if len(ol) >= 3 and ol in ans_lower:
            return o

    # 7. fuzzy match for free text (only if similarity is high)
    # Never fuzzy-match a yes/no answer against arbitrary text options
    if not (is_yes or is_no):
        matches = difflib.get_close_matches(ans_lower, [o.strip().lower() for o in clean_opts], n=1, cutoff=0.75)
        if matches:
            best_lower = matches[0]
            for o in clean_opts:
                if o.strip().lower() == best_lower:
                    return o

    # If the user answered Yes/No or this is a yes/no question, don't fall back to picking an arbitrary option
    if is_yes or is_no or YESNO_LABELS.search(lbl_lower):
        return ""

    # Don't pick arbitrary options for state / country / location dropdowns either
    if re.search(r"\b(state|country|province|region|citizenship|nationality)\b", lbl_lower):
        return ""

    return ""


def fact_rule(label: str, rule_for_fn=None):
    """Fallback: check if `label` matches a known EEO/legal fact category."""
    lbl = (label or "").lower()
    for cat, (ans, pat) in FACTS.items():
        if cat in lbl or re.search(rf"\b{cat}\b", lbl):
            return cat, {"a": ans, "option": pat, "src": f"fact_{cat}"}
    return None, None
