"""
Answer -> option matching, shared by every dropdown / radio / listbox path in fill.py.

Most failed submissions on 2026-10-14 had an answer that didn't fit the field: "2027" for a Yes/No
question, "Yes" for "which state do you live in", "08" where the site lists "August". The site rejected
the field and the filler retried the same answer five times. This module turns (question, answer, options)
into the option to click - or None, so a wrong option is never picked silently.

Also: fact questions (school, country, state, degree, ...) are answered from AJ's own profile.json facts,
never guessed - a guess once picked "Harvard University".
"""
import re

PLACEHOLDER = re.compile(
    r"^\s*("
    r"select(\s+one)?"
    r"|choose(\s+one)?"
    r"|please\s+select"
    r"|--.*--"
    r"|-+"
    r"|none\s+selected"
    r"|no\s+options(\s+available)?"
    r"|no\s+results(\s+(were\s+)?found)?"
    r"|no\s+matching\s+(results|records|options)"
    r"|loading\.*"
    r"|searching\.*"
    r")\s*\.{0,3}\s*$",
    re.I
)

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
ALIASES = [{"united states", "united states of america", "usa", "us", "u.s.", "u.s.a.", "america", "united states of america (+1)", "(+1) united states of america", "united states (+1)", "(+1) united states"},
           {"georgia", "ga"}, {"georgia state university", "georgia state", "gsu"},
           {"bachelor's degree", "bachelors", "bachelor's", "bachelor", "undergraduate"},
           {"junior", "3rd year", "third year"},
           {"computer information systems", "information systems", "cis"}]
YES = re.compile(r"^\s*(yes|y|true|i am|i do|i will|i have|i can|correct|i consent|consent|i agree|agree|accept)\b", re.I)
NO = re.compile(r"^\s*(no|n|false|i am not|i do not|i don'?t|i will not|i won'?t|i have not|i can'?t|i cannot|i do not consent|decline|opt out|i opt out)\b(?!.*(?:results|matching|options|records|available))", re.I)


def norm(s):
    return " ".join(str(s or "").split()).strip().lower()


def core_question(label):
    """The actual question inside a long label: 'To be eligible ... must be in the US. Please indicate the
    state in which you currently reside.*' -> 'please indicate the state in which you currently reside'."""
    t = re.sub(r"[*:]+\s*$", "", " ".join(str(label or "").split()))
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", t) if p.strip()]
    if not parts:
        return t
    q = [p for p in parts if p.endswith("?")]
    return re.sub(r"[.?!*]+$", "", (q[-1] if q else parts[-1])).strip()


def _month_index(want):
    w = norm(want)
    m = re.match(r"^(\d{1,2})(?:/\d{2,4})?$", w)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1)) - 1
    for i, name in enumerate(MONTHS):
        if w == name or (len(w) >= 3 and name.startswith(w)) or re.match(rf"^{name[:3]}\b", w):
            return i
    return None


def _yes_no_options(options):
    yes = [o for o in options if YES.search(o)]
    no = [o for o in options if NO.search(o)]
    return (yes[0] if yes else None, no[0] if no else None) if yes and no else (None, None)


def _year_logic(question, want):
    """'Is your expected graduation date in 2028 or later?' + 'December 2027' -> False."""
    q = norm(question)
    m = re.search(r"(20\d\d)\s*(or later|or after|and later|or beyond|or earlier|or before|and earlier)?", q)
    y = re.search(r"(20\d\d)", norm(want))
    if not m or not y:
        return None
    asked, have = int(m.group(1)), int(y.group(1))
    rel = m.group(2) or ""
    if "later" in rel or "after" in rel or "beyond" in rel:
        return have >= asked
    if "earlier" in rel or "before" in rel:
        return have <= asked
    if re.search(rf"\b(after|later than)\s+(\w+\s+)?{asked}", q):
        return have > asked
    if re.search(rf"\b(before|prior to|by)\s+(\w+\s+)?{asked}", q):
        return have < asked
    if re.search(rf"\b(in|during)\s+(\w+\s+)?{asked}\b", q):
        return have == asked
    return None


def resolve(label, want, options, pattern=None, semantic_ok=True):
    """Best option for answer `want` to question `label`, or None if nothing fits."""
    opts = [o for o in options if o and not PLACEHOLDER.search(str(o))]
    if not opts or want is None:
        return None
    w = norm(want)
    if not w:
        return None
    # dial-code list answered with a phone number ("Phone Number" label on both fields): pick US +1, never the first code
    dial = [o for o in opts if re.search(r"\+\s?\d{1,4}\b", str(o))]
    if len(dial) >= 0.6 * len(opts) and re.fullmatch(r"[\d\s()+.-]{7,}", w):
        us = [o for o in dial if re.search(r"united states|\busa?\b", str(o), re.I) and re.search(r"\+\s?1\b", str(o))]
        return us[0] if us else next((o for o in dial if re.search(r"\+\s?1\)?\s*$", str(o))), None)
    # 1. exact, then whole-word ("Male" never matches "Female"), then the rule's own option pattern
    for o in opts:
        if norm(o) == w:
            return o
    for group in ALIASES:
        if w in group:
            al = [o for o in opts if norm(o) in group]
            if al:
                return al[0]
    word = [o for o in opts if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", norm(o))]
    if word:
        return min(word, key=lambda o: len(o))
    if pattern:
        try:
            pat = [o for o in opts if re.search(pattern, o, re.I)]
        except re.error:
            pat = []
        if pat:
            pat_word = [o for o in pat if not re.search(r"(?<=[a-z])" + re.escape(w), norm(o))]
            return (pat_word or pat)[0]
    # 2. Yes / No questions: map yes-ish answers, or reason about years ("2028 or later?" + "2027")
    yes, no = _yes_no_options(opts)
    if yes and no:
        if YES.search(w):
            return yes
        if NO.search(w):
            return no
        yl = _year_logic(core_question(label) or label, want)
        if yl is not None:
            return yes if yl else no
        return None   # a fact like "Georgia" can't be turned into yes/no safely
    # 3. dates: "05/2028" -> "May/June 2028" (same year; the month breaks ties)
    y = re.search(r"(20\d\d)", w)
    if y:
        same = [o for o in opts if y.group(1) in str(o)]
        mm = re.match(r"^(\d{1,2})[/-]", w)
        mi = int(mm.group(1)) - 1 if mm and 1 <= int(mm.group(1)) <= 12 else _month_index(w.replace(y.group(1), "").strip(" /-,"))
        if mi is not None and len(same) > 1:
            same = [o for o in same if MONTHS[mi][:3] in norm(o)] or same
        if len(same) == 1 or (same and mi is not None):
            return same[0]
    # 4. months: "08" / "Aug" / "August"
    mi = _month_index(want)
    if mi is not None:
        name = MONTHS[mi]
        for o in opts:
            on = norm(o)
            if on in (name, name[:3], str(mi + 1), f"{mi + 1:02d}") or on.startswith(name[:3] + " ") or re.match(rf"^0?{mi + 1}\b(?![/\d])", on):
                return o
    # 4. option contained in the answer: "Information Systems" for "Computer Information Systems"
    inside = [o for o in opts if len(norm(o)) > 3 and re.search(r"(?<![a-z])" + re.escape(norm(o)) + r"(?![a-z])", w)]
    if inside:
        return max(inside, key=lambda o: len(o))
    # 5. meaning match (local embeddings): "United States" ~ "USA", "Georgia State Univ." ~ "Georgia State University"
    if semantic_ok and len(opts) <= 300:
        try:
            from . import semantic
            if semantic.available():
                i, s = semantic.nearest(str(want), [str(o) for o in opts])
                if i is not None and s >= 0.78:
                    return opts[i]
        except Exception:
            pass

    # 6. Fallback for fact questions (school, major, degree): if user's fact is not in options, choose 'Other' or 'Not Listed'
    cat, _ = fact_category(label)
    if cat in ("school", "major", "degree"):
        other_opts = [o for o in opts if re.match(r"^\s*(other|not listed|other\s*[\/\-]\s*not listed|none of the above)\b", str(o), re.I)]
        if other_opts:
            return other_opts[0]

    return None


# ---------------------------------------------------------------- fact questions: answer from profile, never guess
FACTS = [  # (category, question pattern on the core question, probe label that AJ's profile.json rules answer)
    ("school", r"\b(university|college|school|institution)\b.*\b(attend|attending|enrolled|currently|confirm|name)\b|"
               r"\b(attend|name of|which)\b.*\b(university|college|school|institution)\b|^(school|university|college|institution)( name)?$",
     "name of school"),
    ("country", r"\bcountry\b.*\b(reside|live|residence|located|based|currently)\b|country of residence|which country|^country$",
     "country"),
    ("country_code", r"country\s*(?:phone\s*)?code|phone\s*country", "country code"),
    ("state", r"\bstate\b.*\b(reside|live|residence|located|based)\b|\b(reside|live)\b.*\bstate\b|which (us |u\.s\. )?state|^state$",
     "state/province"),
    ("city", r"\bcity\b.*\b(reside|live|located|based)\b|which city|current city|^city$", "city"),
    ("zip", r"\b(zip|postal)\b", "zip"),
    ("degree", r"\bdegree\b.*\b(pursuing|pursue|type|level|currently|earning|seeking)\b|highest level of education|^degree$",
     "degree type"),
    ("major", r"\b(major|field of study|discipline|area of study|concentration)\b", "major"),
    ("graduation", r"\bgraduat", "expected graduation"),
    ("gpa", r"\bgpa\b|grade point", "gpa"),
    ("year_in_school", r"year in school|class standing|classification|what year are you|academic\s*(status|standing)", "current year in school"),
    ("race", r"\brace\b|racial|ethnicity", "race"),
    ("veteran", r"veteran", "veteran status"),
]


def fact_category(label):
    q = norm(core_question(label))
    for cat, pat, probe in FACTS:
        if re.search(pat, q, re.I):
            return cat, probe
    return None, None


def fact_rule(label, rule_for):
    """(category, rule) for a fact question. rule is None when AJ's profile has no answer -> leave it empty."""
    cat, probe = fact_category(label)
    if not cat:
        return None, None
    r = rule_for(probe)
    if r and r.get("a") not in (None, "", "SKIP", "ASK"):
        return cat, {**r, "q": re.escape(label), "src": "fact"}
    return cat, None
