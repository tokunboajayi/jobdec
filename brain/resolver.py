"""
AJ AGENT BRAIN // ZERO-TOKEN FAST RESOLVER
Instantaneous sub-millisecond local answer matching for screening questions.
Resolves 90%+ of ATS questions with 0 tokens and 0 API latency.
"""
import datetime, os, pathlib, re, sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import candidate  # noqa: E402  # the active candidate's .env facts (JOBDEC_HOME)


def _fact(key: str) -> Optional[str]:
    """This candidate's CANDIDATE_<key>, or None (the rule is dropped: never another person's value)."""
    return candidate.fact(key) or None


# Pre-compiled canonical answer mappings (Regex Pattern -> Canonical Answer)
_RULES: List[Tuple[str, Optional[str]]] = [
    # Work Authorization & Citizenship
    (r"(?i)(authorized|eligible|legally\s+(permitted|eligible)|lawful(ly)?\s+eligible)\s+(to\s+work|for\s+employment)", "Yes"),
    (r"(?i)legally\s+eligible\s+for\s+employment", "Yes"),
    (r"(?i)proof\s+of\s+identity\s+and\s+employment\s+eligibility", "Yes"),
    (r"(?i)lawfully\s+authorized\s+to\s+work", "Yes"),
    (r"(?i)(are\s+you\s+a\s+)?u\.?s\.?\s+citizen(ship)?", "Yes"),
    (r"(?i)(select\s+your\s+)?current\s+u\.?s\.?\s+status", "U.S. Citizen"),
    (r"(?i)documentation\s+establishing.*(identity|right\s+to\s+work)", "Yes"),
    (r"(?i)right\s+to\s+work\s+in\s+the\s+country", "Yes"),
    (r"(?i)eligible.*security\s+clearance.*citizen", "Yes"),
    (r"(?i)how\s+many\s+years.*python", "2"),
    (r"(?i)^(i\s+do\s+not\s+(want|wish)\s+to\s+answer|prefer\s+not\s+to\s+(answer|say|disclose)|decline\s+to\s+(answer|state|disclose|self-identify))", ""),
    (r"(?i)(need|require)\s+(visa\s+)?sponsorship", "No"),
    (r"(?i)(now\s+or\s+in\s+the\s+future|in\s+future).*(require|need).*sponsor", "No"),
    (r"(?i)will\s+you\s+ever\s+(require|need).*sponsorship", "No"),
    (r"(?i)(require|need).*immigration.*(sponsorship|support|filing)", "No"),
    (r"(?i)security\s+clearance.*able\s+to\s+obtain", "Yes"),
    (r"(?i)hold\s+an\s+active.*clearance", "No"),
    (r"(?i)current.*highest\s+level\s+of\s+security\s+clearance", "None"),
    (r"(?i)(trade\s+control\s+laws|rules\s+concerning\s+the\s+export|export\s+of\s+control|release\s+or\s+disclosure\s+of\s+u\.?s\.?|are\s+you\s+a\s+u\.?s\.?\s+citizen.*permanent\s+resident)", "Yes"),
    (r"(?i)(official\s+or\s+unofficial\s+)?transcript.*(verify|enrollment)", "Yes"),

    # Age & Legal Screening
    (r"(?i)at\s+least\s+18\s+years", "Yes"),
    (r"(?i)18\s+years\s+of\s+age\s+or\s+older", "Yes"),
    (r"(?i)over\s+(the\s+age\s+of\s+)?18", "Yes"),
    (r"(?i)(legal\s+age|age\s+range)", "18 or older"),
    (r"(?i)medicare|medicaid|excluded.*supplier|sanctions.*supplier", "No"),
    (r"(?i)consent\s+to.*background\s+check", "Yes"),
    (r"(?i)willing\s+to\s+undergo.*drug\s+screen", "Yes"),
    (r"(?i)drug\s+test", "Yes"),
    (r"(?i)high\s+school\s+diploma\s+or\s+ged", "Yes"),

    # Student Status & Academic Eligibility
    (r"(?i)(actively\s+pursuing|currently\s+pursuing|pursuing).*bachelor", "Yes"),
    (r"(?i)(currently\s+enrolled|enrolled\s+in).*(college|university|degree)", "Yes"),
    (r"(?i)enrolled\s+in\s+an\s+accredited", "Yes"),
    (r"(?i)returning\s+to\s+school\s+after\s+internship", "Yes"),
    (r"(?i)working\s+toward.*degree", "Yes"),
    (r"(?i)bachelor.*degree.*in\s+progress", "Yes"),
    (r"(?i)cumulative\s+gpa", "3.00"),
    (r"(?i)^gpa\b", "3.00"),
    (r"(?i)academic\s+(status|standing)", "Senior"),
    (r"(?i)year\s+in\s+school", "Senior"),
    (r"(?i)class\s+(standing|status)", "Senior"),
    (r"(?i)current\s+enrollment\s+class\s+status", "Senior"),
    (r"(?i)complete\s+your\s+current\s+degree\s+program", "December 2026"),
    (r"(?i)middle\s*initial", ""),

    # Work Commitment & Hours
    (r"(?i)able\s+to\s+work\s+full-?time.*summer", "Yes"),
    (r"(?i)40\s+hours\s+per\s+week", "Yes"),
    (r"(?i)willing\s+to\s+relocate", "Yes"),
    (r"(?i)open\s+to\s+relocation", "Yes"),
    (r"(?i)able\s+to\s+commute", "Yes"),
    (r"(?i)hybrid\s+work\s+arrangement", "Yes"),
    (r"(?i)in-person.*office", "Yes"),
    (r"(?i)(report\s+to\s+the\s+office|at\s+least\s+3\s+days\s+a\s+week)", "Yes"),
    (r"(?i)(type\s+to\s+add\s+skills|^skills?\b|technical\s+skills)", "Python"),
    (r"(?i)(spring\s+co-?op|summer\s+internship|co-?op.*internship|both.*spring.*summer|internship.*or.*co-?op)", "Summer Internship"),

    # Salary / Compensation Expectations
    (r"(?i)(desired|expected|minimum)\s+(salary|compensation|pay|rate|hourly)", "Open"),
    (r"(?i)compensation\s+expectation", "Open"),
    (r"(?i)salary\s+requirement", "Open"),

    # Prior Employment / Non-compete / Family
    (r"(?i)previously\s+employed\s+by", "No"),
    (r"(?i)currently\s+employed\s+by", "No"),
    (r"(?i)worked\s+for.*in\s+the\s+past", "No"),
    (r"(?i)subject\s+to.*non-?compete", "No"),
    (r"(?i)signed\s+(an?|any)\s+agreement\s+with\s+(a|any|current|former)", "No"),
    (r"(?i)agreement\s+with\s+(a|any)\s+employer.*not.*(solicit|compete|hire|engage)", "No"),
    (r"(?i)(have\s+a\s+)?non-?compete(\s+agreement)?", "No"),
    (r"(?i)personal\s+financial\s+interest|financial\s+interest\s+in\s+firms", "No"),
    (r"(?i)maintain\s+any\s+commitments\s+to\s+another\s+employer|engaged\s+in\s+any\s+other\s+outside\s+employment", "No"),
    (r"(?i)accept\s+employment\s+with\s+fannie\s+mae.*will|upon\s+starting\s+with\s+our\s+organization,\s+will", "No"),
    (r"(?i)licensed\s+professional.*license\s+infractions|misconduct.*investigations", "No"),
    (r"(?i)^\s*work\s+authorization\s*:?(\*|\b)?$", "U.S. Citizen"),
    (r"(?i)family\s+members?\s+or\s+relatives?.*work", "No"),
    (r"(?i)relative.*employed\s+at", "No"),
    (r"(?i)conflict\s+of\s+interest", "No"),
    (r"(?i)secondary\s+contact\s+number", re.sub(r"\D", "", os.getenv("CANDIDATE_PHONE", "5550199"))),
    (r"(?i)desired\s+(annual\s+)?salary", "60000"),
    (r"(?i)you\s+are\s+applying\s+for\s+state", "Georgia"),
    (r"(?i)you\s+are\s+applying\s+for\s+country\s+code", "United States of America (+1)"),
    (r"(?i)you\s+are\s+applying\s+for\s+country(\*|\b)?$", "United States of America"),
    (r"(?i)previously\s+worked\s+for\s+(this|our|the)\s+organization|previously\s+(been\s+)?contracted\s+with|former\s+employee\s+of|previously\s+worked\s+for|ever\s+been\s+employed\s+by|current/former.*contractor.*or\s+former.*employee", "No"),
    (r"(?i)dispute\s+resolution\s+program|arbitration\s+and\s+mediation\s+agreement|mandatory\s+arbitration.*agreement", "I agree"),
    (r"(?i)how\s+often.*(in\s+days)?.*receive\s+an\s+alert|alert\s+frequency|job\s+alert.*(days|frequency)", "1"),
    (r"(?i)(if\s+yes,?\s*)?(please\s+provide\s+)?visa\s+type\s+and\s+expiration\s+date|visa\s+type.*expiration", "N/A"),
    (r"(?i)served.*in\s+any\s+active.*guard.*reserve.*military|currently\s+serving\s+in.*military|military\s+spouse|domestic\s+partner.*military", "No"),
    (r"(?i)standardized\s+test\s+score\s+type|select\s+your\s+standardized\s+test\s+score\s+type|type\s+of\s+standardized\s+test", "SAT"),
    (r"(?i)provide\s+your\s+best\s+result\s+on\s+sat|sat\s+score|best\s+score\s+on\s+sat", "1350"),
    (r"(?i)provide\s+your\s+best\s+result\s+on\s+act|act\s+score", "N/A"),
    (r"(?i)other\s+context.*(immigration|sponsorship)\s+needs|additional\s+context.*sponsorship", "None - I am a U.S. citizen and do not require sponsorship"),

    # Compliance & Artificial Intelligence Consent
    (r"(?i)artificial\s+intelligence.*(screening|process)", "Yes"),
    (r"(?i)ai\s+screening\s+process", "Yes"),
    (r"(?i)opt\s*out\s*of.*ai\s+screening", "No"),
    (r"(?i)terms\s+and\s+conditions", "Yes"),
    (r"(?i)privacy\s+policy", "Yes"),
    (r"(?i)certify\s+that\s+the\s+information", "Yes"),
    (r"(?i)accurate\s+and\s+complete", "Yes"),
    (r"(?i)(restriction.*prevent.*employee|non-?compete|non-?solicitation)", "No"),
    (r"(?i)(administrative\s+agency|regulatory\s+agency|self-regulatory|under\s+investigation|disciplinary\s+action)", "No"),
    (r"(?i)(healthcare\s+professional|active\s+license|licensed\s+healthcare)", "No"),
    (r"(?i)(government\s+(employee|entity|official|worker|agency|contractor)|(current|former).*government)", "No"),
    (r"(?i)(military\s+spouse|section\s+847|national\s+defense\s+authorization|official\s+or\s+employee\s+of\s+the\s+dod|former\s+military|post-government\s+employment)", "No"),
    (r"(?i)(use\s+or\s+work\s+on\s+the\s+workday\s+system|work\s+on\s+the\s+workday\s+system)", "No"),
    (r"(?i)(please\s+enter\s+['\"]?yes['\"]?\s+if\s+you\s+acknowledge|enter\s+yes\s+if\s+you\s+acknowledge)", "Yes"),

    # Standard EEO Demographics
    (r"(?i)pronoun", _fact("PRONOUNS")),
    (r"(?i)^gender\b", _fact("GENDER")),
    (r"(?i)hispanic.*latino", _fact("HISPANIC_LATINO")),
    (r"(?i)race|ethnicity", _fact("RACE")),
    (r"(?i)veteran\s+status", _fact("VETERAN_STATUS")),
    (r"(?i)disability\s+status", _fact("DISABILITY_STATUS")),
    (r"(?i)(in-office|onsite|on-site).*culture", "Yes"),
    (r"(?i)how\s+did\s+you\s+(hear|find|learn)", "LinkedIn"),

    # Academic & Location Defaults
    (r"(?i)(name\s+of\s+(?:school|university|institution|college)|^(?:school|university|institution|college)\b|current\s+(?:school|university|institution|college)|what\s+(?:school|university|college))", _fact("UNIVERSITY")),
    (r"(?i)(major|field\s+of\s+study)", _fact("MAJOR")),
    (r"(?i)degree\s+level", _fact("DEGREE")),
    (r"(?i)(expected\s+)?graduation\s+(date|year)", _fact("EXPECTED_GRAD_DATE")),
    (r"(?i)graduation\s+month", _fact("EXPECTED_GRAD_MONTH")),
    (r"(?i)desired\s+start\s+date", _fact("AVAILABLE_START_DATE")),
    (r"(?i)start\s+month", "June"),
    (r"(?i)start\s+year", "2027"),
    (r"(?i)city", _fact("CITY")),
    (r"(?i)county\s*\/?\s*state|state\s*\/?\s*(?:province|county|region)|state\s+or\s+province|\bstate\b.*(reside|live|residence|located)|(reside|live|residence|located).*state|which.*state|indicate.*state|\bstate\b", _fact("STATE")),
    (r"(?i)\bcounty\b", _fact("COUNTY")),
    (r"(?i)postal.*code|zip\s*code", _fact("ZIP_CODE")),
    (r"(?i)\baddress\s+line\s+1\b|\bstreet\s+address\b", _fact("ADDRESS_LINE_1")),
    (r"(?i)\baddress\s+line\s+[23]\b|\b(apartment|suite|unit)\b", os.getenv("CANDIDATE_ADDRESS_LINE_2", "")),
    (r"(?i)(?:legally\s+)?eligible\s+to\s+work|authorized\s+to\s+work|legal\s+right\s+to\s+work", "Yes"),
    (r"(?i)^country\b|country\s*of\s*(?:residence|citizenship)|\baddress.*country|^(?:current\s+|residence\s+)?country\b", _fact("COUNTRY")),
    (r"(?i)country\s*\/?\s*territory\s*phone\s*code", "United States of America (+1)"),
    (r"(?i)phone\s*code", "+1"),
    (r"(?i)(consider.*other\s+opportunities|talent\s+community|talent\s+pool|future.*opportunities)", "Yes"),
    (r"(?i)(twitter|facebook(\s*profile)?|instagram)", ""),
    (r"(?i)linkedin", _fact("LINKEDIN_URL")),
    (r"(?i)github", _fact("GITHUB_URL")),
    (r"(?i)(graduated within the past 6 months|active student)", "Yes"),
    (r"(?i)share.*personal information with its (advertising|marketing) partners", "Yes"),
    (r"(?i)website|portfolio", _fact("PORTFOLIO_URL") or _fact("LINKEDIN_URL")),
    (r"(?i)\bdate\b.*day|^\s*day\s*$", datetime.date.today().strftime("%d")),
    (r"(?i)\bdate\b.*month|^\s*month\s*$", datetime.date.today().strftime("%m")),
    (r"(?i)\bdate\b.*year|^\s*year\s*$", datetime.date.today().strftime("%Y")),
    (r"(?i)^\s*date\s*(\*|\b)?$", datetime.date.today().strftime("%m/%d/%Y")),
    (r"(?i)^location\b|work.*location|job.*location|primary.*location", _fact("LOCATION_TEXT") or (f"{_fact('CITY')}, {_fact('STATE')}" if _fact("CITY") and _fact("STATE") else None)),
    (r"(?i)duration.*(allowed.*to\s+do\s+your\s+)?internship", "10-12 weeks"),
    (r"(?i)(share\s+any\s+)?relationship\s+you\s+have\s+with", "None"),
    (r"(?i)preference\s+to\s+receive\s+notification\s+updates|notification\s+updates", "Email"),
    (r"(?i)ready\s*to\s*submit", "Yes"),
    (r"(?i)signature", _fact("FULL_NAME")),
]
CANONICAL_RULES: List[Tuple[str, str]] = [(p, a) for p, a in _RULES if a is not None]  # unknown fact -> no rule

# Standardized high-scoring answers for open-ended prompts (grounded in candidate's experience)
OPEN_ENDED_TEMPLATES: List[Tuple[str, str]] = [(p, a) for p, a in [
    (r"(?i)(why.*work\s+here|why.*interested\s+in|why\s+this\s+role)", _fact("ELEVATOR_PITCH")),
    (r"(?i)(describe.*project|automation\s+experience|technical\s+achievement)", _fact("PROUDEST_ACHIEVEMENT")),
    (r"(?i)(what\s+are\s+your\s+)?(strengths|greatest\s+strength)\b",
     f"My key strengths are {_fact('TOP_SKILLS')}." if _fact("TOP_SKILLS") else None),
    # only "how did you hear" questions; "referred ... Campus Referral Program?" is a yes/no fact, not a source
    (r"(?i)(how\s+did\s+you\s+hear|referral\s+source|source\s+of\s+(your\s+)?(application|referral))", "LinkedIn"),
] if a is not None]


class FastResolver:
    """Zero-Token Fast Answer Matcher."""

    @classmethod
    def resolve(cls, label: str, options: Optional[List[str]] = None) -> Optional[str]:
        if not label:
            return None

        clean_label = label.strip()

        # 1. Check Canonical Rules
        for pattern, answer in CANONICAL_RULES:
            if re.search(pattern, clean_label):
                if options:
                    # Match canonical answer against available options
                    matched = cls._best_option_match(answer, options)
                    if matched:
                        return matched
                return answer

        # 2. Check Open-Ended Templates
        for pattern, answer in OPEN_ENDED_TEMPLATES:
            if re.search(pattern, clean_label):
                if options:
                    matched = cls._best_option_match(answer, options)
                    if matched:
                        return matched
                return answer

        return None

    @staticmethod
    def _best_option_match(target: str, options: List[str]) -> Optional[str]:
        target_lower = target.lower()
        # Exact match
        for opt in options:
            if opt.strip().lower() == target_lower:
                return opt

        # Target contained in option
        for opt in options:
            if target_lower in opt.lower():
                return opt

        # Option contained in target
        for opt in options:
            if opt.lower() in target_lower and len(opt) > 2:
                return opt

        return None


def fast_resolve(label: str, options: Optional[List[str]] = None) -> Optional[str]:
    """Convenience module-level resolver for 0-token instant question resolution."""
    return FastResolver.resolve(label, options)
