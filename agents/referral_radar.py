"""
Warm Referral Radar & Recruiter Outreach Dossier Generator.
Identifies target decision makers, constructs Boolean LinkedIn search queries,
finds potential Kennesaw State University alumni at target employers,
and drafts hyper-personalized connection notes strictly within LinkedIn's 300-char limit.
"""
import csv
import os
import re
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from . import context, intelligent_tailor

OUTREACH_CSV = Path(__file__).resolve().parent.parent / "outreach_drafts.csv"
DOSSIERS_DIR = Path(__file__).resolve().parent.parent / "briefings" / "referrals"


def build_referral_dossier(company: str, role: str, job_url: str = "") -> Dict[str, Any]:
    """
    Constructs a warm referral and recruiter outreach dossier for a target company and role.
    """
    analysis = intelligent_tailor.analyze_job(company, role)
    comp_clean = analysis["company_clean"]
    role_clean = analysis["role_clean"]
    domain = analysis["domain"]

    # 1. Targeted LinkedIn Search Queries
    encoded_comp = urllib.parse.quote(f'"{comp_clean}"')
    
    # Query A: Hiring Manager / Lead Search
    if domain == "iam":
        lead_keywords = urllib.parse.quote('("IAM Manager" OR "Identity Lead" OR "Directory Services Lead" OR "Security Manager")')
    elif domain == "soc_analyst":
        lead_keywords = urllib.parse.quote('("SOC Manager" OR "Incident Response Lead" OR "Security Operations Manager")')
    elif domain == "it_support":
        lead_keywords = urllib.parse.quote('("IT Support Manager" OR "Service Desk Lead" OR "IT Director")')
    else:
        lead_keywords = urllib.parse.quote('("Security Engineering Manager" OR "Director of Information Security" OR "CISO")')
    
    lead_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_comp}%20{lead_keywords}"

    # Query B: Kennesaw State University Alumni Warm Path
    ksu_keywords = urllib.parse.quote('("Kennesaw State University" OR "KSU") ("Security" OR "Cyber" OR "IT" OR "Systems")')
    alumni_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_comp}%20{ksu_keywords}"

    # Query C: Technical Recruiter / Talent Lead
    recruiter_keywords = urllib.parse.quote('("Technical Recruiter" OR "Security Recruiter" OR "University Recruiter")')
    recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_comp}%20{recruiter_keywords}"

    # 2. Connection Notes (< 300 characters each)
    # Variant A: Warm Alumni Outreach
    alumni_note = (
        f"Hi [Name], I noticed you're at {comp_clean} and went to KSU! I'm a Cybersecurity senior at KSU "
        f"(CompTIA Security+) and just applied for the {role_clean[:30]} opening. Would love to connect and hear about your team! - Michael Azuka"
    )
    if len(alumni_note) > 298:
        alumni_note = (
            f"Hi [Name], I saw you're at {comp_clean} and went to KSU! I'm a KSU Cyber senior with Security+ "
            f"and just applied for {role_clean[:25]}. Would value connecting! - Michael Azuka"
        )

    # Variant B: Hiring Manager / Lead Note
    if domain == "iam":
        skill_highlight = "Active Directory & PowerShell automation"
    elif domain == "soc_analyst":
        skill_highlight = "Azure Sentinel SIEM tuning & packet analysis"
    elif domain == "it_support":
        skill_highlight = "enterprise technical support & diagnostics"
    else:
        skill_highlight = "infrastructure defense & CompTIA Security+"

    lead_note = (
        f"Hi [Name], I recently applied for {role_clean[:30]} at {comp_clean}. With practical experience in "
        f"{skill_highlight} and CompTIA Security+, I'm eager to contribute to your security mission. Would love to connect! - Michael Azuka"
    )
    if len(lead_note) > 298:
        lead_note = (
            f"Hi [Name], I applied for {role_clean[:25]} at {comp_clean}. Bringing hands-on {skill_highlight[:30]} "
            f"and Security+, I'm eager to support your team. Would love to connect! - Michael Azuka"
        )

    # Variant C: Recruiter Note
    recruiter_note = (
        f"Hi [Name], I saw you support hiring at {comp_clean} and recently applied for the {role_clean[:30]} role. "
        f"As a KSU Cybersecurity senior with CompTIA Security+ and enterprise support background, I'd value connecting! - Michael Azuka"
    )

    # 3. Comprehensive Follow-Up InMail / Email Draft
    inmail_subject = f"Application Follow-Up: {role_clean} — Michael Azuka"
    inmail_body = (
        f"Hi [Hiring Manager / Recruiter Name],\n\n"
        f"I hope your week is off to a great start. I recently submitted my application for the {role_clean} "
        f"position at {comp_clean} and wanted to personally reiterate my strong enthusiasm for your team's work.\n\n"
        f"As a Cybersecurity senior at Kennesaw State University graduating in December 2026 with the CompTIA "
        f"Security+ credential and enterprise support background at Wolters Kluwer and Castles Technology, I bring "
        f"hands-on experience in {skill_highlight}.\n\n"
        f"I would welcome the opportunity to connect briefly and share how my technical background and disciplined "
        f"work ethic can support {comp_clean}'s objectives.\n\n"
        f"Thank you for your time and leadership,\n"
        f"Michael Azuka\n"
        f"404-645-0373 | mazuka146@gmail.com | linkedin.com/in/michael-azuka"
    )

    # 4. Save to outreach_drafts.csv
    try:
        write_header = not OUTREACH_CSV.exists()
        with open(OUTREACH_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["Date", "Company", "Role", "Search URL", "Draft Note"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d"),
                comp_clean,
                role_clean,
                lead_url,
                lead_note
            ])
    except Exception:
        pass

    # 5. Save detailed dossier markdown
    DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "target"
    dossier_file = DOSSIERS_DIR / f"{slug}_radar.md"

    md_content = f"""# 👥 Warm Referral Radar: {comp_clean} — {role_clean}
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Candidate:** Michael Azuka

---

## 🔍 Instant LinkedIn Search Targets
1. **[Hiring Managers & Security Leads]({lead_url})**
2. **[KSU Alumni at {comp_clean}]({alumni_url})** *(Highest Response Rate!)*
3. **[Technical & Campus Recruiters]({recruiter_url})**

---

## 💬 Connection Notes (Under 300 Characters)

### 🎓 1. KSU Alumni Connection Note:
```text
{alumni_note}
```
*({len(alumni_note)} characters)*

### 🛡️ 2. Hiring Manager Connection Note:
```text
{lead_note}
```
*({len(lead_note)} characters)*

### 💼 3. Talent Acquisition / Recruiter Note:
```text
{recruiter_note}
```
*({len(recruiter_note)} characters)*

---

## ✉️ Direct Email / InMail Draft
**Subject:** `{inmail_subject}`

```text
{inmail_body}
```
"""
    dossier_file.write_text(md_content, encoding="utf-8")

    telegram_summary = (
        f"👥 <b>Warm Referral Radar: {comp_clean}</b>\n\n"
        f"🔗 <a href=\"{alumni_url}\">Find KSU Alumni at {comp_clean}</a>\n"
        f"🔗 <a href=\"{lead_url}\">Find Hiring Leads / Security Managers</a>\n"
        f"🔗 <a href=\"{recruiter_url}\">Find Technical Recruiters</a>\n\n"
        f"📝 <b>Draft Note (Alumni):</b>\n<code>{alumni_note}</code>\n\n"
        f"📝 <b>Draft Note (Hiring Lead):</b>\n<code>{lead_note}</code>"
    )

    return {
        "company": comp_clean,
        "role": role_clean,
        "lead_url": lead_url,
        "alumni_url": alumni_url,
        "recruiter_url": recruiter_url,
        "alumni_note": alumni_note,
        "lead_note": lead_note,
        "inmail_body": inmail_body,
        "telegram_summary": telegram_summary,
        "file_path": str(dossier_file)
    }
