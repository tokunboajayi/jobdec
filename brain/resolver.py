"""
AJ AGENT BRAIN // ZERO-TOKEN FAST RESOLVER
Instantaneous sub-millisecond local answer matching for screening questions.
Resolves 90%+ of ATS questions with 0 tokens and 0 API latency.
"""
import datetime, os, re
from typing import Any, Dict, List, Optional, Tuple

# Pre-compiled canonical answer mappings (Regex Pattern -> Canonical Answer)
CANONICAL_RULES: List[Tuple[str, str]] = [
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
    (r"(?i)cumulative\s+gpa", "3.35"),
    (r"(?i)^gpa\b", "3.35"),
    (r"(?i)academic\s+(status|standing)", "Junior"),
    (r"(?i)year\s+in\s+school", "Junior"),
    (r"(?i)class\s+(standing|status)", "Junior"),
    (r"(?i)current\s+enrollment\s+class\s+status", "Junior"),
    (r"(?i)complete\s+your\s+current\s+degree\s+program", "December 2027"),
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
    (r"(?i)pronoun", "He/Him/His"),
    (r"(?i)^gender\b", "Male"),
    (r"(?i)hispanic.*latino", "No"),
    (r"(?i)race|ethnicity", "Black or African American"),
    (r"(?i)veteran\s+status", "I am not a protected veteran"),
    (r"(?i)disability\s+status", "No, I do not have a disability"),
    (r"(?i)(in-office|onsite|on-site).*culture", "Yes"),
    (r"(?i)how\s+did\s+you\s+(hear|find|learn)", "LinkedIn"),

    # Academic & Location Defaults
    (r"(?i)(name\s+of\s+(?:school|university|institution|college)|^(?:school|university|institution|college)\b|current\s+(?:school|university|institution|college)|what\s+(?:school|university|college))", os.getenv("CANDIDATE_UNIVERSITY", "State University")),
    (r"(?i)(major|field\s+of\s+study)", os.getenv("CANDIDATE_MAJOR", "Computer Science")),
    (r"(?i)degree\s+level", os.getenv("CANDIDATE_DEGREE", "Bachelor's")),
    (r"(?i)(expected\s+)?graduation\s+(date|year)", os.getenv("CANDIDATE_EXPECTED_GRAD_DATE", "May 2027")),
    (r"(?i)graduation\s+month", os.getenv("CANDIDATE_EXPECTED_GRAD_MONTH", "May")),
    (r"(?i)desired\s+start\s+date", os.getenv("CANDIDATE_AVAILABLE_START_DATE", "06/01/2027")),
    (r"(?i)start\s+month", "June"),
    (r"(?i)start\s+year", "2027"),
    (r"(?i)city", os.getenv("CANDIDATE_CITY", "Atlanta")),
    (r"(?i)county\s*\/?\s*state|state\s*\/?\s*(?:province|county|region)|state\s+or\s+province|\bstate\b.*(reside|live|residence|located)|(reside|live|residence|located).*state|which.*state|indicate.*state|\bstate\b", os.getenv("CANDIDATE_STATE", "Georgia")),
    (r"(?i)\bcounty\b", os.getenv("CANDIDATE_COUNTY", "Fulton")),
    (r"(?i)postal.*code|zip\s*code", os.getenv("CANDIDATE_ZIP_CODE", "30303")),
    (r"(?i)\baddress\s+line\s+1\b|\bstreet\s+address\b", os.getenv("CANDIDATE_ADDRESS_LINE_1", "123 Main St")),
    (r"(?i)\baddress\s+line\s+[23]\b|\b(apartment|suite|unit)\b", os.getenv("CANDIDATE_ADDRESS_LINE_2", "")),
    (r"(?i)(?:legally\s+)?eligible\s+to\s+work|authorized\s+to\s+work|legal\s+right\s+to\s+work", "Yes"),
    (r"(?i)^country\b|country\s*of\s*(?:residence|citizenship)|\baddress.*country|^(?:current\s+|residence\s+)?country\b", os.getenv("CANDIDATE_COUNTRY", "United States of America")),
    (r"(?i)country\s*\/?\s*territory\s*phone\s*code", "United States of America (+1)"),
    (r"(?i)phone\s*code", "+1"),
    (r"(?i)(consider.*other\s+opportunities|talent\s+community|talent\s+pool|future.*opportunities)", "Yes"),
    (r"(?i)(twitter|facebook(\s*profile)?|instagram)", ""),
    (r"(?i)linkedin", os.getenv("CANDIDATE_LINKEDIN_URL", "https://www.linkedin.com")),
    (r"(?i)github", os.getenv("CANDIDATE_GITHUB_URL", "https://github.com")),
    (r"(?i)(graduated within the past 6 months|active student)", "Yes"),
    (r"(?i)share.*personal information with its (advertising|marketing) partners", "Yes"),
    (r"(?i)website|portfolio", os.getenv("CANDIDATE_PORTFOLIO_URL", os.getenv("CANDIDATE_LINKEDIN_URL", "https://www.linkedin.com"))),
    (r"(?i)\bdate\b.*day|^\s*day\s*$", datetime.date.today().strftime("%d")),
    (r"(?i)\bdate\b.*month|^\s*month\s*$", datetime.date.today().strftime("%m")),
    (r"(?i)\bdate\b.*year|^\s*year\s*$", datetime.date.today().strftime("%Y")),
    (r"(?i)^\s*date\s*(\*|\b)?$", datetime.date.today().strftime("%m/%d/%Y")),
    (r"(?i)^location\b|work.*location|job.*location|primary.*location", os.getenv("CANDIDATE_LOCATION_TEXT", f"{os.getenv('CANDIDATE_CITY', 'Atlanta')}, {os.getenv('CANDIDATE_STATE', 'GA')}")),
    (r"(?i)duration.*(allowed.*to\s+do\s+your\s+)?internship", "10-12 weeks"),
    (r"(?i)(share\s+any\s+)?relationship\s+you\s+have\s+with", "None"),
    (r"(?i)preference\s+to\s+receive\s+notification\s+updates|notification\s+updates", "Email"),
    (r"(?i)ready\s*to\s*submit", "Yes"),
    (r"(?i)signature", os.getenv("CANDIDATE_FULL_NAME", "Candidate")),
]

# Standardized high-scoring answers for open-ended prompts (grounded in candidate's experience)
OPEN_ENDED_TEMPLATES: List[Tuple[str, str]] = [
    (
        r"(?i)(why.*work\s+here|why.*interested\s+in|why\s+this\s+role)",
        os.getenv("CANDIDATE_ELEVATOR_PITCH", "I have built agentic automation workflows, data systems, and enterprise process automations. I am eager to apply my technical, automation, and problem-solving skills to deliver measurable impact in this role.")
    ),
    (
        r"(?i)(describe.*project|automation\s+experience|technical\s+achievement)",
        os.getenv("CANDIDATE_PROUDEST_ACHIEVEMENT", "I designed and deployed automated multi-agent operational pipelines handling enterprise data and process workflows, cutting manual coordination time significantly while delivering robust, reliable results.")
    ),
    (
        r"(?i)(what\s+are\s+your\s+)?(strengths|greatest\s+strength)\b",
        "My key strengths are process automation, analytical problem-solving, and cross-functional communication. I specialize in turning complex, messy operational requirements into reliable automated systems using Python, SQL, and data visualization tools like Tableau and Power BI."
    ),
    (
        r"(?i)(how\s+did\s+you\s+hear|source|referral)",
        "LinkedIn"
    )
]


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
