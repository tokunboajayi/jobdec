"""Fictional test candidate's generic cover letter (no real person). Same interface as resumes/cover_letter_gen.py."""
BODY = [
    "Dear Hiring Team,",
    "I'm an Information Security student at Example State University, and I'm applying for your Summer 2027 internship.",
    "At Northwind Health I resolved account access tickets and deployed laptops for a site launch, and at Contoso Retail "
    "I troubleshot POS hardware and network faults.",
    "In my lab work I automated identity and access management in Active Directory with PowerShell, applying RBAC and "
    "least privilege.",
    "I'd bring the same care to your team. Thank you for your time and consideration.",
    "Sincerely,<br/>Jordan Sample",
]


def render(body, out):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    st = getSampleStyleSheet()["Normal"]
    SimpleDocTemplate(str(out), pagesize=letter).build([Paragraph(p, st) for p in body])
    return str(out)
