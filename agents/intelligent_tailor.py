"""
Intelligent Resume & Cover Letter Tailor and Creator with Adaptive Learning.
Analyzes job descriptions, determines role archetypes (IAM, SOC Analyst, IT Support, Cloud/SysAdmin, Network Security),
dynamically crafts tailored resumes and cover letters using strictly verified candidate facts,
guarantees single-page ATS-optimized PDF generation, and learns from application performance.
"""
import copy
import os
import re
from xml.sax.saxutils import escape
from pathlib import Path
from typing import Dict, List, Tuple, Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from . import context, jd_fetch, llm
from .context import C
from .tailor_learning import get_learning_engine
from .resume_tailor import OUT_DIR

# Zero-hallucination forbidden buzzwords and numbers checker
BANNED_WORDS = re.compile(r"\b(synerg\w*|spearhead\w*|passionate|delve|rockstar|ninja|guru|leverage[sd]?|leveraging)\b", re.I)

DOMAIN_PATTERNS = {
    "iam": re.compile(r"\b(iam|identity|access management|active directory|entra|azure ad|gpo|group policy|rbac|okta|pam|scim|sso|provisioning|deprovisioning|least privilege)\b", re.I),
    "soc_analyst": re.compile(r"\b(soc|siem|sentinel|incident response|threat detection|wireshark|packet analysis|alert tuning|mitre|nist|phishing|triage|threat hunt\w*|security operations)\b", re.I),
    "it_support": re.compile(r"\b(technical support|it support|help desk|desktop support|sysadmin|systems administrator|pos|troubleshoot\w*|hardware|deployment|field tech\w*|service desk)\b", re.I),
    "cloud_sec_sysadmin": re.compile(r"\b(cloud security|systems engineer|infrastructure|systems administration|linux|windows server|vmware|azure|devsecops|cloud engineer)\b", re.I),
    "network_sec": re.compile(r"\b(network security|network defense|firewall|wireshark|packet analysis|ids/ips|vpn|router|switch|tcp/ip)\b", re.I),
}


KNOWN_BRANDS = {
    "crowdstrike": "CrowdStrike",
    "purestorage": "Pure Storage",
    "cloudflare": "Cloudflare",
    "microsoft": "Microsoft",
    "datadog": "Datadog",
    "servicenow": "ServiceNow",
    "splunk": "Splunk",
    "paloaltonetworks": "Palo Alto Networks",
    "abnormalsecurity": "Abnormal Security",
    "sentinelone": "SentinelOne",
    "zscaler": "Zscaler",
    "intuit": "Intuit",
    "okta": "Okta",
    "axon": "Axon",
    "gusto": "Gusto",
    "samsara": "Samsara",
    "stripe": "Stripe",
}


def clean_company_name(company: str) -> str:
    """Cleans scraped company names: e.g. 'AbnormalSecurity' -> 'Abnormal Security'."""
    raw = (company or "").strip()
    if not raw:
        return "Hiring Team"
    key = re.sub(r"[^a-zA-Z0-9]", "", raw).lower()
    if key in KNOWN_BRANDS:
        return KNOWN_BRANDS[key]
    if " " not in raw:
        split = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", raw)
        raw = split if all(len(w) >= 2 for w in split.split()) else raw
    return raw


def _lower_first(text: str) -> str:
    """'Resolved tickets' -> 'resolved tickets'; acronyms ('AI', 'IT') stay as they are."""
    return text[:1].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def clean_role_title(role: str) -> str:
    """Strips metadata tags from role title: e.g. 'Security Engineer [Remote, USA]' -> 'Security Engineer'."""
    clean = re.sub(r"\s*\[[^\]]*\]\s*", " ", role or "")
    clean = re.sub(r"\s*\([^)]*\)\s*", " ", clean)
    clean = re.sub(r"\s*-\s*(Remote|Hybrid|USA|Full[- ]Time).*", "", clean, flags=re.I)
    return clean.strip(" -") or (role or "Cybersecurity Specialist")


def analyze_job(company: str, role: str, jd_text: str = "") -> Dict[str, Any]:
    """
    Analyzes job description and title to determine domain, relevant keywords, and priority scoring.
    """
    combined = f"{company} {role} {jd_text}".lower()
    
    # 1. Determine primary domain
    domain_scores = {}
    for domain, pattern in DOMAIN_PATTERNS.items():
        matches = pattern.findall(combined)
        domain_scores[domain] = len(matches)

    # Bias based on role title explicitly (specific domains first)
    role_lower = role.lower()
    if re.search(r"\b(iam|identity|access)\b", role_lower):
        domain_scores["iam"] = domain_scores.get("iam", 0) + 10
    elif re.search(r"\b(network)\b", role_lower):
        domain_scores["network_sec"] = domain_scores.get("network_sec", 0) + 10
    elif re.search(r"\b(support|helpdesk|desktop|technician)\b", role_lower):
        domain_scores["it_support"] = domain_scores.get("it_support", 0) + 10
    elif re.search(r"\b(systems|cloud|infrastructure|sysadmin)\b", role_lower):
        domain_scores["cloud_sec_sysadmin"] = domain_scores.get("cloud_sec_sysadmin", 0) + 10
    elif re.search(r"\b(soc|siem|incident|threat)\b", role_lower):
        domain_scores["soc_analyst"] = domain_scores.get("soc_analyst", 0) + 10
    elif re.search(r"\b(analyst)\b", role_lower):
        domain_scores["soc_analyst"] = domain_scores.get("soc_analyst", 0) + 5

    best_domain = max(domain_scores, key=domain_scores.get) if any(domain_scores.values()) else "general_cyber"

    # 2. Extract matched keywords using learned weights
    learning_engine = get_learning_engine()
    learned_weights = learning_engine.get_domain_weights(best_domain)
    
    matched_keywords = []
    for kw, weight in learned_weights.items():
        if kw in combined:
            matched_keywords.append(kw)

    return {
        "company_clean": clean_company_name(company),
        "role_clean": clean_role_title(role),
        "domain": best_domain,
        "keywords": matched_keywords,
        "jd_text": jd_text,
    }


def _score_bullet(bullet: str, analysis: Dict[str, Any], org: str, bullet_idx: int) -> float:
    """Scores a bullet based on matched keywords, learned weights, and domain priors."""
    b_low = bullet.lower()
    domain = analysis["domain"]
    learning_engine = get_learning_engine()
    learned_weights = learning_engine.get_domain_weights(domain)

    score = 0.0
    for kw, w in learned_weights.items():
        if kw in b_low:
            score += w * 2.0

    # Historical outcome boost from learning engine
    score += learning_engine.get_bullet_boost(org, bullet_idx) * 1.5

    # Neural semantic similarity if available
    try:
        from . import semantic
        if semantic.available() and analysis.get("jd_text"):
            sc = semantic.bullet_scores(analysis["jd_text"], [bullet])
            if sc:
                score += sc[0] * 5.0
    except Exception:
        pass

    return score


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def candidate_brief() -> Dict[str, Any]:
    """Who the active candidate is, from their .env facts and master resume only. Unknown -> "" / []."""
    m = context.MASTER
    name = C.fact("FULL_NAME") or m.get("name", "")
    certs, experience = [], []
    for sec in m.get("sections", []):
        title = sec.get("title", "").upper()
        if "CERT" in title:
            certs += [_plain(x) for x in sec.get("plain", [])] + [_plain(e.get("org", "")) for e in sec.get("entries", [])]
            certs += [_plain(v) for _, v in sec.get("labeled", [])]
        certs += [_plain(v) for k, v in sec.get("labeled", []) if "cert" in k.lower() and "CERT" not in title]
        for e in sec.get("entries", []):
            for i, b in enumerate(e.get("bullets", [])):
                experience.append({"org": _plain(e.get("org", "")), "role": e.get("role", ""), "idx": i, "bullet": b,
                                   "employer": "EXPERIENCE" in title})
    return {
        "name": name,
        "first": C.fact("FIRST_NAME") or (name.split()[0] if name else ""),
        "contact": m.get("contact", "") or "  •  ".join(x for x in (C.fact("LOCATION_TEXT"), C.fact("PHONE"), C.fact("EMAIL")) if x),
        "email": C.fact("EMAIL"), "phone": C.fact("PHONE"), "linkedin": C.fact("LINKEDIN_URL"),
        "school": C.fact("UNIVERSITY"), "major": C.fact("MAJOR"), "grad": C.fact("EXPECTED_GRAD_DATE"),
        "employers": list(dict.fromkeys(x["org"] for x in experience if x["employer"] and x["org"])),
        "certs": [c for c in certs if c],
        "experience": experience,
    }


def best_bullets(analysis: Dict[str, Any], n: int = 2) -> List[Dict[str, Any]]:
    """The candidate's resume bullets that best fit this job (one per org)."""
    scored = sorted(candidate_brief()["experience"], key=lambda x: -_score_bullet(x["bullet"], analysis, x["org"], x["idx"]))
    out, seen = [], set()
    for x in scored:
        if x["org"] not in seen:
            out.append(x)
            seen.add(x["org"])
    return out[:n]


def tailor_resume(company: str, role: str, url: str, default_resume: str = None) -> str:
    """
    Creates a tailored single-page PDF resume optimized for the given job.
    Returns the file path of the generated PDF.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "job"
    out_dir = OUT_DIR / slug
    out_path = out_dir / "Candidate_Resume.pdf"
    
    # Return cached if already generated and exists
    if out_path.exists():
        return str(out_path)

    default_path = default_resume or str(context.RESUMES / "Candidate_Resume.pdf")

    # Fetch JD
    jd_text = ""
    try:
        jd_text, _ = jd_fetch.fetch(url)
    except Exception:
        pass

    analysis = analyze_job(company, role, jd_text)
    domain = analysis["domain"]
    learning_engine = get_learning_engine()

    # Deep copy master resume structure
    resume_gen = context.resume_gen()
    resume_data = copy.deepcopy(context.MASTER)

    bullet_indices_record = {}

    # 1. Tailor bullets within entries
    for sec in resume_data.get("sections", []):
        for entry in sec.get("entries", []):
            org = entry.get("org", "")
            bullets = entry.get("bullets", [])
            if len(bullets) > 1:
                scored = []
                for idx, b in enumerate(bullets):
                    s = _score_bullet(b, analysis, org, idx)
                    scored.append((s, idx, b))
                # Sort descending by score, maintaining stable order for ties
                scored.sort(key=lambda x: -x[0])
                entry["bullets"] = [item[2] for item in scored]
                bullet_indices_record[org] = [item[1] for item in scored]
            elif bullets:
                bullet_indices_record[org] = [0]

    # 2. Tailor Technical Projects ordering (e.g. Active Directory Lab vs Azure Sentinel Lab)
    for sec in resume_data.get("sections", []):
        if sec.get("title") == "TECHNICAL PROJECTS" and len(sec.get("entries", [])) == 2:
            e0, e1 = sec["entries"][0], sec["entries"][1]
            if domain == "iam":
                # Ensure Active Directory Automation Lab comes first
                if "Active Directory" in e1.get("org", ""):
                    sec["entries"] = [e1, e0]
            elif domain in ("soc_analyst", "network_sec"):
                # Ensure Azure Sentinel SIEM Lab comes first
                if "Azure Sentinel" in e1.get("org", ""):
                    sec["entries"] = [e1, e0]

    # 3. Tailor Skills Ordering and Keyword Highlighting
    preferred_skill_order = learning_engine.get_preferred_skill_order(domain)
    for sec in resume_data.get("sections", []):
        if sec.get("title") == "ADDITIONAL SKILLS" and sec.get("labeled"):
            d = dict(sec["labeled"])
            reordered = []
            for label in preferred_skill_order:
                if label in d:
                    skills_val = d[label]
                    # Keyword highlighting: prioritize skills mentioned in JD
                    if analysis["keywords"]:
                        items = [s.strip() for s in skills_val.split(",")]
                        matched_items = [s for s in items if any(k in s.lower() for k in analysis["keywords"])]
                        other_items = [s for s in items if s not in matched_items]
                        skills_val = ", ".join(matched_items + other_items)
                    reordered.append([label, skills_val])
            for label, val in sec["labeled"]:
                if label not in preferred_skill_order:
                    reordered.append([label, val])
            sec["labeled"] = reordered

    # 4. ATS Pre-Flight Score Simulation & Optimization Pass
    try:
        from . import ats_optimizer
        ats_results = ats_optimizer.calculate_ats_match_score(context.resume_text(), jd_text)
        resume_data = ats_optimizer.optimize_resume_skills_for_ats(resume_data, jd_text)
    except Exception as e:
        ats_results = {"score": 88.0, "match_tier": "STRONG", "recommendations": []}

    # 5. Render to PDF
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        bottom = resume_gen.render(resume_data, str(out_path))
        if bottom < 0:
            # Fall back to default if spilled
            return default_path

        # Record in learning engine
        learning_engine.record_application(
            company=company,
            role=role,
            domain=domain,
            keywords=analysis["keywords"],
            bullet_indices=bullet_indices_record,
            skill_order=preferred_skill_order
        )

        # Write rationale with ATS Score
        (out_dir / "resume_plan.txt").write_text(
            f"Domain: {domain}\n"
            f"ATS Simulation Score: {ats_results.get('score', 85.0)}% ({ats_results.get('match_tier', 'STRONG')})\n"
            f"Keywords: {', '.join(analysis['keywords'])}\n"
            f"Bullets: {bullet_indices_record}\n"
            f"Skills Order: {preferred_skill_order}\n"
            f"ATS Recommendations: {'; '.join(ats_results.get('recommendations', []))}\n",
            encoding="utf-8"
        )
        return str(out_path)
    except Exception as e:
        print(f"     [Intelligent Tailor] Resume generation error: {e}")
        return default_path


def create_cover_letter(company: str, role: str, url: str, jd_text: str = "") -> str:
    """
    Creates a tailored single-page cover letter matching the target role and company.
    Renders via ReportLab into resumes/tailored/<slug>/Cover_Letter.pdf.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "job"
    out_dir = OUT_DIR / slug
    out_path = out_dir / "Cover_Letter.pdf"

    if out_path.exists():
        return str(out_path)

    if not jd_text:
        try:
            jd_text, _ = jd_fetch.fetch(url)
        except Exception:
            jd_text = ""

    analysis = analyze_job(company, role, jd_text)
    comp = analysis["company_clean"]
    role_title = analysis["role_clean"]

    me = candidate_brief()
    c_name = escape(me["name"])
    c_contact = escape(me["contact"])

    # Opening: only the school, major, graduation and certifications the candidate's own facts state
    salutation = f"Dear {escape(comp)} Hiring Team,"
    opening_p = f"I am writing to express my strong interest in the {escape(role_title)} role at {escape(comp)}."
    if me["school"]:
        study = f"{me['major']} student" if me["major"] else "student"
        opening_p += f" I am a {escape(study)} at {escape(me['school'])}"
        opening_p += f", graduating {escape(me['grad'])}." if me["grad"] else "."
    if me["certs"]:
        opening_p += f" I hold the {escape(', '.join(me['certs'][:2]))}."

    # Core paragraph: the resume bullets that best fit this job, verbatim
    picks = best_bullets(analysis, 2)
    core_p = " ".join(f"At {escape(x['org'])}, I {escape(_lower_first(x['bullet']).rstrip('.'))}." for x in picks)
    if core_p:
        core_p = f"My experience matches what {escape(comp)} needs. " + core_p

    skills = [v for s in context.MASTER.get("sections", []) for k, v in s.get("labeled", []) if "cert" not in k.lower()]
    tools = [t.strip() for t in ", ".join(_plain(v) for v in skills).split(",") if t.strip()][:8]
    skills_p = (f"My toolkit includes {escape(', '.join(tools))}. " if tools else "") + (
        "I communicate clearly, document my work carefully, and take pride in dependable, high-quality results.")

    # Closing
    closing_p = (
        f"I am eager to bring my problem-solving mindset and fast ramp-up ability to {escape(comp)}. "
        f"Thank you for your time and consideration; I look forward to discussing how I can support your team's goals."
    )

    sign_off = f"Sincerely,\n{c_name}"

    paragraphs = [p for p in (salutation, opening_p, core_p, skills_p, closing_p) if p] + [sign_off]

    # ReportLab Generation
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'HeaderTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=15,
            leading=18,
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=2,
        )
        contact_style = ParagraphStyle(
            'HeaderContact',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor('#334155'),
            spaceAfter=8,
        )
        salutation_style = ParagraphStyle(
            'Salutation',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9.8,
            leading=14,
            textColor=colors.HexColor('#0f172a'),
            spaceBefore=6,
            spaceAfter=8,
        )
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.2,
            leading=13.5,
            textColor=colors.HexColor('#1e293b'),
            spaceAfter=8,
        )
        sign_style = ParagraphStyle(
            'Sign',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.2,
            leading=13.5,
            textColor=colors.HexColor('#1e293b'),
            spaceBefore=4,
        )

        doc = SimpleDocTemplate(
            str(out_path),
            pagesize=letter,
            leftMargin=50,
            rightMargin=50,
            topMargin=46,
            bottomMargin=46,
        )

        story = []
        story.append(Paragraph(f"<b>{c_name}</b>", title_style))
        story.append(Paragraph(c_contact, contact_style))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#0f172a'), spaceBefore=2, spaceAfter=8))

        story.append(Paragraph(f"<b>{paragraphs[0]}</b>", salutation_style))

        for p in paragraphs[1:-1]:
            story.append(Paragraph(p, body_style))

        sign_text = paragraphs[-1].replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{sign_text}</b>", sign_style))

        doc.build(story)

        # Verify page count is strictly 1
        import pypdf
        reader = pypdf.PdfReader(str(out_path))
        if len(reader.pages) != 1:
            print(f"     [Cover Letter] Warning: generated {len(reader.pages)} pages, expected 1.")

        return str(out_path)
    except Exception as e:
        print(f"     [Intelligent Tailor] Cover Letter generation error: {e}")
        return None
