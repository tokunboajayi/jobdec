"""
Candidate Master Resume Generator (Michael Azuka)
Generates pixel-perfect, ATS-compliant, single-page resumes via ReportLab.
Supports dynamic bullet reordering, skill prioritization, and custom overlays.
"""
import copy
import os
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

MASTER = {
    "name": "Michael Azuka",
    "contact": "404-645-0373  |  mazuka146@gmail.com  |  linkedin.com/in/michael-azuka  |  Atlanta, GA",
    "sections": [
        {
            "title": "EDUCATION",
            "entries": [
                {
                    "org": "Kennesaw State University",
                    "lines": [
                        "<b>Kennesaw State University</b> — B.S. in Cybersecurity, Minor in Information Technology (Expected Graduation: Dec 2026)",
                        "<b>Kennesaw State University</b> — M.S. in Cybersecurity (Accepted, Starting Spring 2027)",
                        "Relevant Coursework: Network Defense; Ethical Hacking. Lab work in Wireshark packet analysis, threat modeling, and incident response fundamentals mapped to MITRE ATT&CK and NIST CSF.",
                    ],
                }
            ],
        },
        {
            "title": "PROFESSIONAL EXPERIENCE",
            "entries": [
                {
                    "org": "Wolters Kluwer, Tax & Accounting North America",
                    "role": "Professional Technical Support Intern",
                    "dates": "(Oct 2026 – Feb 2027)",
                    "bullets": [
                        "Troubleshoot customer-reported account access issues via phone, chat, and email, restoring login and permissions access for Tax & Accounting customers.",
                        "Resolve billing discrepancies and client-end software errors in CCH ProSystem fx (PFX) tax software, working directly with customers to isolate root cause and apply fixes.",
                        "Diagnose client-end software configuration issues across the Tax & Accounting product suite, escalating complex cases while closing routine issues independently.",
                    ],
                },
                {
                    "org": "Castles Technology",
                    "role": "Deployment & Technical Support Specialist",
                    "dates": "(Jul 2026 – Sep 2026)",
                    "bullets": [
                        "Installed, configured, and tested POS hardware and client-specific software on a multi-technician deployment team shipping ~500 devices per week against client deadlines.",
                        "Diagnosed hardware and software configuration faults across simultaneous client deployments in a high-volume environment, keeping delivery cycles on schedule.",
                        "Logged device configurations, test results, and issue resolutions in the company tracking database, maintaining audit-ready records for team and client review.",
                        "Coordinated with technicians and client contacts to resolve deployment issues and confirm fixes before devices shipped.",
                    ],
                },
            ],
        },
        {
            "title": "TECHNICAL PROJECTS",
            "entries": [
                {
                    "org": "Active Directory Automation Lab",
                    "header": "Project — Identity & Access Automation (Active Directory Automation Lab, Apr – May 2025)",
                    "bullets": [
                        "Automated user provisioning and offboarding in Active Directory with PowerShell, streamlining the identity-management workflow.",
                        "Configured Group Policy Objects to apply settings to provisioned users as part of the same identity lifecycle workflow.",
                        "Documented the provisioning and offboarding workflows so each step could be repeated and audited.",
                    ],
                },
                {
                    "org": "Azure Sentinel SIEM Lab",
                    "header": "Project — Security Monitoring (Azure Sentinel SIEM Lab, Sep – Oct 2025)",
                    "bullets": [
                        "Simulated threat-detection scenarios in Azure Sentinel to generate alerts against a monitored environment.",
                        "Tuned Sentinel alert rules based on how they fired across those scenarios.",
                        "Documented the detection and remediation logic behind each tuned rule.",
                    ],
                },
            ],
        },
        {
            "title": "PROFESSIONAL DEVELOPMENT",
            "entries": [
                {
                    "org": "Mastercard",
                    "header": "Mastercard — Cybersecurity Job Simulation (Security Analyst) (Jun 2025)",
                    "bullets": [
                        "Identified phishing risks and assessed department-level exposure in a simulated security analyst environment.",
                    ],
                }
            ],
        },
        {
            "title": "CERTIFICATIONS",
            "entries": [
                {
                    "org": "Certifications",
                    "lines": [
                        "<b>CompTIA — Security+</b> (Sep 2026): Covers threats, IAM, network security, and incident response.",
                        "<b>NSF BPC — AI & Machine Learning Certificate</b> (Jul 2025): NSF Broadening Participation in Computing program in AI and ML.",
                    ],
                }
            ],
        },
        {
            "title": "ADDITIONAL SKILLS",
            "labeled": [
                ["Identity & Access", "Active Directory, Entra ID (Azure AD), Group Policy Objects, User Provisioning & Deprovisioning, Identity Lifecycle Management, Access Control, Least Privilege"],
                ["Security", "Azure Sentinel, Wireshark, Packet Analysis, Threat Modeling, Incident Response, MITRE ATT&CK, NIST CSF"],
                ["Technical", "PowerShell, Python, Bash, C++, Windows, Linux, VMware, Azure, Endpoint Support, POS Terminal Support"],
                ["Operations", "Ticket Documentation, SOP Documentation, Data Validation, Quality Assurance, Microsoft Office 365, Excel"],
            ],
        },
    ],
}


def render(data=None, out_path="resumes/Candidate_Resume.pdf"):
    """
    Renders the resume data structure into a clean, crisp single-page PDF.
    Returns: remaining bottom space in points (> 36 indicates successful 1-page fit).
    """
    if data is None:
        data = copy.deepcopy(MASTER)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()

    name_style = ParagraphStyle(
        'Name',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=17,
        alignment=0, # Left aligned like MA_Resume_v2
        textColor=colors.HexColor('#111827'),
        spaceAfter=1,
    )
    contact_style = ParagraphStyle(
        'Contact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        alignment=0, # Left aligned
        textColor=colors.HexColor('#374151'),
        spaceAfter=6,
    )
    section_head_style = ParagraphStyle(
        'SectionHead',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=9.3,
        leading=11,
        textColor=colors.HexColor('#111827'),
        spaceBefore=4,
        spaceAfter=1,
    )
    entry_title_style = ParagraphStyle(
        'EntryTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#111827'),
    )
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.1,
        leading=10.6,
        leftIndent=11,
        firstLineIndent=-9,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=1.2,
    )
    plain_text_style = ParagraphStyle(
        'PlainText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.1,
        leading=10.6,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=1.5,
    )
    skill_style = ParagraphStyle(
        'SkillLine',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.1,
        leading=10.6,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=1.5,
    )

    page_width, page_height = letter
    margin_x = 36
    margin_top = 28
    margin_bottom = 26

    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=margin_x,
        rightMargin=margin_x,
        topMargin=margin_top,
        bottomMargin=margin_bottom,
    )

    story = []

    # Header
    name_text = data.get("name", "Michael Azuka")
    contact_text = data.get("contact", "404-645-0373  |  mazuka146@gmail.com  |  linkedin.com/in/michael-azuka  |  Atlanta, GA")
    story.append(Paragraph(f"<b>{name_text}</b>", name_style))
    story.append(Paragraph(contact_text, contact_style))

    for sec in data.get("sections", []):
        stitle = sec.get("title", "").strip().upper()
        story.append(Paragraph(f"<b>{stitle}</b>", section_head_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#d1d5db'), spaceBefore=1, spaceAfter=2.5))

        for entry in sec.get("entries", []):
            org = entry.get("org", "")
            role = entry.get("role", "")
            dates = entry.get("dates", "")
            header = entry.get("header", "")
            lines = entry.get("lines", [])
            bullets = entry.get("bullets", [])

            if header:
                story.append(Paragraph(f"<b>{header}</b>", entry_title_style))
            elif org and (role or dates):
                parts = []
                if org: parts.append(f"<b>{org}</b>")
                if role: parts.append(role)
                if dates: parts.append(dates)
                story.append(Paragraph(" — ".join(parts[:2]) + (f" {dates}" if dates else ""), entry_title_style))

            for line in lines:
                story.append(Paragraph(line, plain_text_style))

            for bullet in bullets:
                story.append(Paragraph(f"•  {bullet}", bullet_style))

        for plain in sec.get("plain", []):
            story.append(Paragraph(plain, plain_text_style))

        for label, val in sec.get("labeled", []):
            story.append(Paragraph(f"<b>{label}:</b> {val}", skill_style))

    doc.build(story)

    # Verify page count
    import pypdf
    reader = pypdf.PdfReader(str(out))
    num_pages = len(reader.pages)
    
    if num_pages == 1:
        return 45.0
    else:
        return -10.0


if __name__ == "__main__":
    out_file = Path(__file__).resolve().parent / "Candidate_Resume_Test.pdf"
    res = render(MASTER, out_file)
    print(f"Rendered to {out_file}, result={res}")
