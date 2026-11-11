"""
Interview Battlecard & Prep Dossier Generator.
Generates comprehensive, targeted interview dossiers for upcoming recruiter screens,
technical interviews, and team rounds. Tailors technical questions, STAR model answers,
and reverse-inquiries strictly grounded in the active candidate's master resume.
"""
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from . import context, jd_fetch, intelligent_tailor

INTERVIEWS_DIR = context.C.DATA / "briefings" / "interviews"

def star_story(analysis: Dict[str, Any]) -> Dict[str, str]:
    """STAR outline built from the candidate's best-matching resume entry; the wording stays the resume's own."""
    picks = intelligent_tailor.best_bullets(analysis, 1)
    if not picks:
        return {"title": "Your strongest project", "situation": "Pick the resume entry closest to this role.",
                "task": "", "action": "", "result": ""}
    top = picks[0]
    same = [x["bullet"] for x in intelligent_tailor.candidate_brief()["experience"] if x["org"] == top["org"] and x["bullet"] != top["bullet"]]
    return {
        "title": top["org"],
        "situation": f"{top['role']} at {top['org']}." if top["role"] else f"At {top['org']}.",
        "task": "Say what you were asked to deliver and why it mattered.",
        "action": top["bullet"],
        "result": same[0] if same else "State the outcome using only the facts on your resume.",
    }

def generate_interview_battlecard(company: str, role: str, url: str = "", jd_text: str = "") -> Dict[str, Any]:
    """
    Generates an executive-level Interview Battlecard for the active candidate.
    Saves markdown dossier to briefings/interviews/<slug>_battlecard.md.
    """
    if not jd_text and url:
        try:
            jd_text, _ = jd_fetch.fetch(url)
        except Exception:
            jd_text = ""

    analysis = intelligent_tailor.analyze_job(company, role, jd_text)
    comp_clean = analysis["company_clean"]
    role_clean = analysis["role_clean"]
    domain = analysis["domain"]
    me = intelligent_tailor.candidate_brief()
    employer = me["employers"][0] if me["employers"] else ""
    story = star_story(analysis)

    # Select domain-specific technical focus
    if domain == "iam":
        domain_title = "Identity & Access Management (IAM) & Directory Services"
        core_questions = [
            ("Explain your experience automating user provisioning in Active Directory.",
             "Walk through my PowerShell automation lab: scripting account creation, assigning OUs, applying GPOs, and implementing immediate deprovisioning to eliminate orphaned accounts."),
            ("How do you enforce the principle of least privilege in enterprise environments?",
             "By implementing Role-Based Access Control (RBAC), auditing permissions regularly, and separating administrative accounts from standard user credentials."),
            ("What is the role of Group Policy Objects (GPOs) in identity governance?",
             "GPOs enforce consistent security baselines across domain-joined machines, such as password complexity, lockout thresholds, and software restriction policies."),
            ("How do you handle customer account access or authentication issues?",
             (f"Cite my {employer} experience: " if employer else "") + "verify user identity, check account lockouts and permissions, and document root cause."),
        ]
    elif domain == "soc_analyst":
        domain_title = "Security Operations (SOC), SIEM & Incident Response"
        core_questions = [
            ("How do you approach investigating a potential security incident?",
             "Follow the NIST Incident Response lifecycle: Preparation, Detection & Analysis (triage alert in Sentinel, inspect Wireshark PCAP), Containment, Eradication, and Lessons Learned."),
            ("How have you tuned alert rules in Azure Sentinel to reduce false positives?",
             "Simulated threat scenarios, observed trigger conditions, refined detection thresholds, and documented remediation logic mapped to MITRE ATT&CK."),
            ("How do you analyze packet captures in Wireshark?",
             "Filter on suspicious IP/ports (TCP/UDP), examine handshake anomalies, follow TCP streams to inspect payload headers, and flag unencrypted credentials or beaconing."),
            ("How do you evaluate phishing risks?",
             "Inspect email headers, SPF/DKIM/DMARC records and attachments, then estimate which users were exposed."),
        ]
    elif domain == "it_support":
        domain_title = "Technical Support, Systems Diagnostics & Operations"
        core_questions = [
            ("Tell me about a time you handled a difficult technical issue under pressure.",
             f"Use the STAR story below ({story['title']}): situation, what you did, and the result, in that order."),
            ("How do you ensure audit readiness when managing devices or tickets?",
             "Log every change, test result and fix where the team can audit it, and close tickets with the root cause written down."),
            ("What steps do you take when troubleshooting a network connectivity issue?",
             "Check physical connections, verify IP configuration (ipconfig/ifconfig, DHCP lease), test local gateway reachability with ping, verify DNS resolution (nslookup), and inspect proxy/firewall settings."),
            ("How do you communicate technical issues to non-technical users?",
             "Listen actively, avoid jargon, explain the root cause in terms of business impact, and walk through corrective steps with patience and clarity."),
        ]
    else:
        domain_title = "Cybersecurity Systems & Infrastructure Defense"
        core_questions = [
            (f"What does your {me['certs'][0]} certification cover that you apply practically?" if me["certs"]
             else "Which security fundamentals do you apply most in practice?",
             "Threat landscape analysis, IAM governance, network architecture security, incident response procedures, and vulnerability mitigation."),
            ("How do you automate repetitive administrative or security tasks?",
             "Use PowerShell for Windows/Active Directory environments and Python or Bash for Linux log parsing and system health monitoring."),
            ("How do you map defense controls to industry frameworks?",
             "Map detective controls to NIST CSF (Identify, Protect, Detect, Respond, Recover) and adversary tactics to the MITRE ATT&CK matrix."),
            ("Why is documentation critical in cybersecurity engineering?",
             "Consistent SOPs ensure repeatability, streamline incident post-mortems, and satisfy compliance and audit requirements."),
        ]

    # Strategic Reverse Questions
    reverse_questions = [
        f"What are the highest priority security or infrastructure initiatives {comp_clean} is focusing on this quarter?",
        "How does the team currently balance automated alerting versus proactive threat hunting and systems tuning?",
        "What does success look like for someone in this role during their first 90 days?",
        "How does the engineering and security team collaborate during high-severity operational incidents?",
        "What opportunities are available for continuous learning and professional certification sponsorship within the department?"
    ]

    # Generate Markdown Dossier
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "target"
    out_file = INTERVIEWS_DIR / f"{slug}_battlecard.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 🎯 Interview Battlecard: {comp_clean} — {role_clean}",
        f"**Date Generated:** {now_str} | **Domain:** {domain_title}",
        f"**Candidate:** {me['name']}" + (f" ({', '.join(x for x in (me['major'], *me['certs'][:1]) if x)})" if me['major'] or me['certs'] else ""),
        "",
        "---",
        "",
        "## 🏢 Target Profile & Mission Alignment",
        f"- **Target Company:** {comp_clean}",
        f"- **Position:** {role_clean}",
        f"- **Core Security Focus:** {domain_title}",
        f"- **Candidate Pitch:** " + " ".join(x for x in (
            f"{me['major']} student at {me['school']}." if me['school'] else "",
            f"Experience at {', '.join(me['employers'])}." if me['employers'] else "",
            f"Certified: {', '.join(me['certs'])}." if me['certs'] else "") if x),
        "",
        "---",
        "",
        "## 🌟 Primary STAR Model Story (Memorize This)",
        f"### **{story['title']}**",
        f"- **Situation:** {story['situation']}",
        f"- **Task:** {story['task']}",
        f"- **Action:** {story['action']}",
        f"- **Result:** {story['result']}",
        "",
        "---",
        "",
        "## ❓ Top Predicted Technical & Behavioral Questions",
    ]

    for idx, (q, talking_point) in enumerate(core_questions, 1):
        lines.append(f"### Q{idx}: {q}")
        lines.append(f"**Key Talking Points:** {talking_point}\n")

    lines.extend([
        "---",
        "",
        "## 💡 5 Sharp Reverse-Questions to Ask the Interviewer",
    ])
    for idx, rq in enumerate(reverse_questions, 1):
        lines.append(f"{idx}. *\"{rq}\"*")

    lines.extend([
        "",
        "---",
        "**Pre-Flight Checklist:**",
        "- [ ] Test microphone, webcam, and stable internet connection 15 mins prior.",
        "- [ ] Have Candidate_Resume.pdf and project notes open on second screen.",
        f"- [ ] Re-read the {story['title']} STAR story and the talking points above.",
        "- [ ] Send thank-you note within 12 hours of completing the interview.",
    ])

    content = "\n".join(lines)
    out_file.write_text(content, encoding="utf-8")

    # Telegram summary format
    telegram_summary = (
        f"🎯 <b>Interview Battlecard Ready!</b>\n\n"
        f"🏢 <b>Company:</b> {comp_clean}\n"
        f"💼 <b>Role:</b> {role_clean}\n"
        f"🛡️ <b>Domain:</b> {domain_title}\n\n"
        f"⭐ <b>Core STAR Story:</b> <i>{story['title']}</i>\n\n"
        f"📁 <i>Full dossier saved to: <code>briefings/interviews/{out_file.name}</code></i>"
    )

    return {
        "file_path": str(out_file),
        "company": comp_clean,
        "role": role_clean,
        "domain": domain,
        "telegram_summary": telegram_summary,
        "content": content
    }

