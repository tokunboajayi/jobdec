"""Fictional test candidate (no real person). Same interface as a candidate's resumes/resume_gen.py: MASTER + render()."""
from xml.sax.saxutils import escape

MASTER = {
    "name": "Jordan Sample",
    "contact": "Springfield, IL • jordan.sample@example.com • 555-010-0199",
    "sections": [
        {"title": "EDUCATION", "entries": [
            {"org": "Example State University", "loc": "Springfield, IL", "lines": [
                "B.S. in Information Security; Expected Graduation: May 2027", "Cumulative GPA: 3.50"]}]},
        {"title": "PROFESSIONAL EXPERIENCE", "entries": [
            {"org": "Northwind Health", "role": "IT Support Intern", "loc": "Springfield, IL", "dates": "Jun 2026 – Aug 2026", "bullets": [
                "Resolved account access and password reset tickets for clinic staff, documenting root cause in the ticketing system",
                "Imaged and deployed 40 laptops with Windows and endpoint protection before a site launch",
                "Wrote PowerShell scripts to automate user provisioning in Active Directory"]},
            {"org": "Contoso Retail", "role": "Help Desk Associate", "loc": "Springfield, IL", "dates": "Jan 2025 – May 2026", "bullets": [
                "Troubleshot POS hardware and network connectivity faults across 12 stores",
                "Logged incidents and escalations in the tracking database, keeping audit-ready records"]}]},
        {"title": "TECHNICAL PROJECTS", "entries": [
            {"org": "SIEM Detection Lab", "role": "Personal Project", "dates": "2026", "bullets": [
                "Tuned SIEM alert rules in Azure Sentinel and mapped detections to MITRE ATT&CK"]},
            {"org": "Active Directory Automation Lab", "role": "Personal Project", "dates": "2026", "bullets": [
                "Automated user provisioning and deprovisioning with PowerShell and Group Policy (GPO), enforcing least privilege and RBAC"]}]},
        {"title": "CERTIFICATIONS", "plain": ["CompTIA Security+ (2026)"]},
        {"title": "ADDITIONAL SKILLS", "labeled": [
            ["Identity & Access", "Active Directory, Entra ID, Azure AD, Group Policy, GPO, RBAC, least privilege"],
            ["Technical", "PowerShell, Python, Bash, Windows, Linux"],
            ["Security", "Azure Sentinel, SIEM, Wireshark, incident response"]]},
    ],
}


def render(data, out):
    """Writes `data` to the PDF `out`; returns 72.0 when it fits on one page, -1.0 when it spills."""
    import pypdf
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    st = getSampleStyleSheet()["Normal"]
    story = [Paragraph(f"<b>{escape(data['name'])}</b>", st), Paragraph(escape(data["contact"]), st)]
    for s in data["sections"]:
        story.append(Paragraph(f"<b>{escape(s['title'])}</b>", st))
        for e in s.get("entries", []):
            story.append(Paragraph(escape(" | ".join(x for x in (e.get("org"), e.get("role"), e.get("dates")) if x)), st))
            story += [Paragraph(escape(x), st) for x in e.get("lines", []) + e.get("bullets", [])]
        story += [Paragraph(escape(x), st) for x in s.get("plain", [])]
        story += [Paragraph(escape(f"{k}: {v}"), st) for k, v in s.get("labeled", [])]
    SimpleDocTemplate(str(out), pagesize=letter).build(story)
    return 72.0 if len(pypdf.PdfReader(str(out)).pages) == 1 else -1.0
