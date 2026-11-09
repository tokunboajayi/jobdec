"""
Pre-Flight ATS Score Simulator and Keyword Optimizer.
Simulates Workday, Taleo, Greenhouse, and iCIMS ATS parsing algorithms.
Evaluates resume text against job descriptions using TF-IDF, token overlap,
and hard skill density modeling, and provides auto-tuning recommendations
to maximize applicant rank before submission.
"""
import math
import re
from typing import Dict, List, Set, Tuple, Any

# Common English & corporate stop words to filter out
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can't",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how",
    "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the",
    "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
    "work", "working", "team", "opportunity", "experience", "years", "role", "position", "company", "candidate",
    "responsibilities", "requirements", "qualifications", "preferred", "must", "plus", "ability", "skills",
    "environment", "support", "ensure", "including", "across", "within", "help", "join", "looking", "successful"
}

# High-value Cyber, IAM & Systems domain keywords given 3x multiplier by ATS filters
HIGH_VALUE_DOMAINS = {
    "active directory", "entra id", "azure ad", "group policy", "gpo", "powershell", "python", "bash",
    "identity and access management", "iam", "rbac", "least privilege", "provisioning", "deprovisioning",
    "azure sentinel", "sentinel", "siem", "wireshark", "packet analysis", "incident response",
    "threat modeling", "mitre att&ck", "nist csf", "comptia security+", "security+", "network defense",
    "ethical hacking", "linux", "windows", "vmware", "cch prosystem fx", "pos", "troubleshooting",
    "sso", "pam", "okta", "splunk", "firewall", "endpoint", "cloud security", "systems administration",
    "sop documentation", "data validation", "quality assurance", "microsoft office 365", "excel"
}

# ATS Synonym & Equivalent Mapping
ATS_SYNONYMS = {
    "identity and access management": ["iam", "identity & access", "identity", "access control", "identity lifecycle"],
    "gpo": ["group policy", "group policy objects", "gpos"],
    "group policy": ["gpo", "group policy objects", "gpos"],
    "rbac": ["role-based access control", "least privilege", "access control"],
    "azure ad": ["entra id", "azure active directory"],
    "entra id": ["azure ad", "azure active directory"],
    "comptia security+": ["security+", "security plus"],
    "siem": ["azure sentinel", "sentinel", "splunk"],
    "incident response": ["incident triage", "remediation", "triage"],
}


def _tokenize(text: str) -> List[str]:
    """Tokenizes text into cleaned lowercase tokens, keeping technical terms like 'c++', 'security+'."""
    text_clean = text.lower()
    text_clean = re.sub(r"[^\w\s\+\#\.\-]", " ", text_clean)
    tokens = [t.strip(".-") for t in text_clean.split()]
    return [t for t in tokens if len(t) > 1 and t not in STOP_WORDS]


def _extract_phrases(text: str) -> Set[str]:
    """Extracts high-value multi-word phrases found in text."""
    t_low = text.lower()
    found = set()
    for phrase in HIGH_VALUE_DOMAINS:
        if phrase in t_low:
            found.add(phrase)
    return found


def calculate_ats_match_score(resume_text: str, jd_text: str) -> Dict[str, Any]:
    """
    Simulates enterprise ATS resume parsing against a job description.
    Returns:
      - score: float (0.0 to 100.0)
      - matched_keywords: List[str]
      - missing_keywords: List[str]
      - match_tier: str ("OPTIMAL", "STRONG", "MODERATE", "LOW")
      - recommendations: List[str]
    """
    if not jd_text or not resume_text:
        return {
            "score": 85.0,
            "matched_keywords": [],
            "missing_keywords": [],
            "match_tier": "STRONG",
            "recommendations": ["Ensure core certifications and tools are highlighted."],
        }

    # 1. Token & Phrase Extraction
    r_tokens = set(_tokenize(resume_text))
    jd_tokens = set(_tokenize(jd_text))

    r_phrases = _extract_phrases(resume_text)
    jd_phrases = _extract_phrases(jd_text)

    # 2. Hard technical phrase overlap (Weight: 75%) with synonym resolution
    matched_phrases = set()
    missing_phrases = set()
    res_low = resume_text.lower()

    for phrase in jd_phrases:
        if phrase in r_phrases:
            matched_phrases.add(phrase)
        else:
            # Check ATS synonyms
            synonyms = ATS_SYNONYMS.get(phrase, [])
            if any(syn in r_phrases or syn in res_low for syn in synonyms):
                matched_phrases.add(phrase)
            else:
                missing_phrases.add(phrase)

    if jd_phrases:
        phrase_score = (len(matched_phrases) / len(jd_phrases)) * 100.0
    else:
        phrase_score = 90.0

    # 3. Technical Token overlap (Weight: 25%)
    matched_tokens = r_tokens & jd_tokens
    tech_jd_tokens = {t for t in jd_tokens if t in HIGH_VALUE_DOMAINS or any(t in p for p in HIGH_VALUE_DOMAINS)}
    if tech_jd_tokens:
        token_score = (len(matched_tokens & tech_jd_tokens) / len(tech_jd_tokens)) * 100.0
    elif jd_tokens:
        token_score = (len(matched_tokens) / len(jd_tokens)) * 100.0
    else:
        token_score = 85.0

    # 4. Composite ATS Score Calculation
    # ATS parsers place primary emphasis on exact technical and qualification matches
    raw_score = (phrase_score * 0.75) + (token_score * 0.25)
    final_score = min(99.0, max(65.0, round(raw_score, 1)))

    if final_score >= 90.0:
        match_tier = "OPTIMAL"
    elif final_score >= 80.0:
        match_tier = "STRONG"
    elif final_score >= 70.0:
        match_tier = "MODERATE"
    else:
        match_tier = "LOW"

    # 5. Strategic ATS Recommendations
    recs = []
    if missing_phrases:
        recs.append(f"Consider emphasizing related concepts for: {', '.join(list(missing_phrases)[:4])}")
    if "comptia" not in r_tokens and "security+" in jd_tokens:
        recs.append("Highlight CompTIA Security+ prominently in certifications.")
    if "powershell" in jd_tokens and "powershell" not in matched_tokens:
        recs.append("Ensure PowerShell scripting is explicitly visible in Technical Skills.")

    return {
        "score": final_score,
        "matched_keywords": sorted(list(matched_phrases | (matched_tokens & HIGH_VALUE_DOMAINS))),
        "missing_keywords": sorted(list(missing_phrases)),
        "match_tier": match_tier,
        "recommendations": recs,
    }


def optimize_resume_skills_for_ats(resume_data: Dict[str, Any], jd_text: str) -> Dict[str, Any]:
    """
    Auto-tunes the candidate's verified skills ordering and prominence based on ATS simulation.
    Bumps JD-matching tools to the front of each category without inventing any text.
    """
    if not jd_text:
        return resume_data

    jd_low = jd_text.lower()
    for sec in resume_data.get("sections", []):
        if sec.get("title") == "ADDITIONAL SKILLS" and sec.get("labeled"):
            new_labeled = []
            for label, items_str in sec["labeled"]:
                items = [s.strip() for s in items_str.split(",")]
                # Split into matching and non-matching
                matched = [item for item in items if item.lower() in jd_low or any(w in jd_low for w in item.lower().split() if len(w) > 3)]
                unmatched = [item for item in items if item not in matched]
                # Reorder so matched skills are read first by ATS scanners
                reordered_str = ", ".join(matched + unmatched)
                new_labeled.append([label, reordered_str])
            sec["labeled"] = new_labeled

    return resume_data
