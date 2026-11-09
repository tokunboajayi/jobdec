"""
Interview Battlecard & Prep Dossier Generator.
Generates comprehensive, targeted interview dossiers for upcoming recruiter screens,
technical interviews, and team rounds. Tailors technical questions, STAR model answers,
and reverse-inquiries strictly grounded in Michael Azuka's verified background.
"""
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from . import context, jd_fetch, intelligent_tailor

INTERVIEWS_DIR = Path(__file__).resolve().parent.parent / "briefings" / "interviews"

STAR_STORIES = {
    "iam": {
        "title": "Active Directory & Identity Lifecycle Automation",
        "situation": "In my Active Directory Automation Lab, manual user onboarding and offboarding created operational delays and inconsistent permissions.",
        "task": "Automate user provisioning and deprovisioning to ensure audit-ready compliance and enforce least-privilege access.",
        "action": "Developed PowerShell scripts to parse incoming user records, provision accounts into specific Organizational Units (OUs), and automatically apply Group Policy Objects (GPOs) for role-based access control.",
        "result": "Streamlined the identity lifecycle into a repeatable, documented, and fully auditable workflow."
    },
    "soc": {
        "title": "Azure Sentinel SIEM Threat Detection & Alert Tuning",
        "situation": "In my Azure Sentinel SIEM Lab, raw alert feeds generated excessive noise, making rapid threat triage challenging.",
        "task": "Simulate real-world attacks, detect threats, and tune alert rules to minimize false positives.",
        "action": "Configured attack simulation scenarios across monitored endpoints, evaluated trigger frequencies, and tuned KQL-based alert rules mapped to MITRE ATT&CK techniques and NIST CSF standards.",
        "result": "Documented remediation playbooks and reduced alert fatigue with precise detection logic."
    },
    "support": {
        "title": "High-Volume Enterprise Technical Support & Access Restoration",
        "situation": "At Wolters Kluwer, tax professionals experienced critical software configuration faults and account lockouts during peak filing periods.",
        "task": "Quickly isolate root cause, restore system permissions, and close incidents while maintaining customer trust.",
        "action": "Diagnosed client-end CCH ProSystem fx software errors, restored database access via phone and chat, and drafted standardized troubleshooting notes.",
        "result": "Independently closed routine access tickets while collaborating smoothly on complex escalations."
    },
    "deployment": {
        "title": "High-Volume Hardware & Software Deployment",
        "situation": "At Castles Technology, client rollout deadlines required rapid hardware staging and software imaging under tight SLAs.",
        "task": "Configure, test, and deploy POS hardware and client-specific firmware across simultaneous rollouts.",
        "action": "Worked on a multi-technician deployment team shipping approximately 500 devices per week, performing hardware diagnostics, database logging, and QA validation before shipment.",
        "result": "Maintained on-time delivery cycles with zero SLA penalties and audit-ready configuration logs."
    }
}


def generate_interview_battlecard(company: str, role: str, url: str = "", jd_text: str = "") -> Dict[str, Any]:
    """
    Generates an executive-level Interview Battlecard for Michael Azuka.
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

    # Select domain-specific technical focus
    if domain == "iam":
        domain_title = "Identity & Access Management (IAM) & Directory Services"
        star_story = STAR_STORIES["iam"]
        core_questions = [
            ("Explain your experience automating user provisioning in Active Directory.",
             "Walk through my PowerShell automation lab: scripting account creation, assigning OUs, applying GPOs, and implementing immediate deprovisioning to eliminate orphaned accounts."),
            ("How do you enforce the principle of least privilege in enterprise environments?",
             "By implementing Role-Based Access Control (RBAC), auditing permissions regularly, and separating administrative accounts from standard user credentials."),
            ("What is the role of Group Policy Objects (GPOs) in identity governance?",
             "GPOs enforce consistent security baselines across domain-joined machines, such as password complexity, lockout thresholds, and software restriction policies."),
            ("How do you handle customer account access or authentication issues?",
             "Cite my Wolters Kluwer experience: verifying user identity, checking account lockouts and permissions in identity directories, and documenting root cause."),
        ]
    elif domain == "soc_analyst":
        domain_title = "Security Operations (SOC), SIEM & Incident Response"
        star_story = STAR_STORIES["soc"]
        core_questions = [
            ("How do you approach investigating a potential security incident?",
             "Follow the NIST Incident Response lifecycle: Preparation, Detection & Analysis (triage alert in Sentinel, inspect Wireshark PCAP), Containment, Eradication, and Lessons Learned."),
            ("How have you tuned alert rules in Azure Sentinel to reduce false positives?",
             "Simulated threat scenarios, observed trigger conditions, refined detection thresholds, and documented remediation logic mapped to MITRE ATT&CK."),
            ("How do you analyze packet captures in Wireshark?",
             "Filter on suspicious IP/ports (TCP/UDP), examine handshake anomalies, follow TCP streams to inspect payload headers, and flag unencrypted credentials or beaconing."),
            ("How do you evaluate phishing risks?",
             "Reference my Mastercard job simulation: inspect email headers, SPF/DKIM/DMARC records, malicious attachments, and calculate department-level exposure."),
        ]
    elif domain == "it_support":
        domain_title = "Technical Support, Systems Diagnostics & Operations"
        star_story = STAR_STORIES["support"]
        core_questions = [
            ("Tell me about a time you handled a difficult technical issue under pressure.",
             "At Wolters Kluwer, tax accounting clients faced urgent software crashes near deadlines. I isolated client-end configuration faults, verified permissions, and restored access calmly."),
            ("How do you ensure audit readiness when managing devices or tickets?",
             "At Castles Technology, I logged every device serial number, test result, and hardware repair in the tracking database before shipping ~500 devices per week."),
            ("What steps do you take when troubleshooting a network connectivity issue?",
             "Check physical connections, verify IP configuration (ipconfig/ifconfig, DHCP lease), test local gateway reachability with ping, verify DNS resolution (nslookup), and inspect proxy/firewall settings."),
            ("How do you communicate technical issues to non-technical users?",
             "Listen actively, avoid jargon, explain the root cause in terms of business impact, and walk through corrective steps with patience and clarity."),
        ]
    else:
        domain_title = "Cybersecurity Systems & Infrastructure Defense"
        star_story = STAR_STORIES["iam"]
        core_questions = [
            ("What does the CompTIA Security+ certification cover that you apply practically?",
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
        f"**Candidate:** Michael Azuka (B.S. Cybersecurity, CompTIA Security+)",
        "",
        "---",
        "",
        "## 🏢 Target Profile & Mission Alignment",
        f"- **Target Company:** {comp_clean}",
        f"- **Position:** {role_clean}",
        f"- **Core Security Focus:** {domain_title}",
        f"- **Candidate Pitch:** KSU Cybersecurity senior with enterprise technical support experience (Wolters Kluwer, Castles Tech) and hands-on lab automation (Active Directory PowerShell provisioning, Azure Sentinel SIEM tuning).",
        "",
        "---",
        "",
        "## 🌟 Primary STAR Model Story (Memorize This)",
        f"### **{star_story['title']}**",
        f"- **Situation:** {star_story['situation']}",
        f"- **Task:** {star_story['task']}",
        f"- **Action:** {star_story['action']}",
        f"- **Result:** {star_story['result']}",
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
        "- [ ] Re-read Wolters Kluwer and Active Directory automation talking points.",
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
        f"⭐ <b>Core STAR Story:</b> <i>{star_story['title']}</i>\n\n"
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

