"""
Candidate Master Cover Letter Generator (Michael Azuka)
Produces standard or tailored single-page cover letters using ReportLab.
"""
import os
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

BODY = [
    "Dear Hiring Team,",
    "I am writing to express my strong enthusiasm for applying for your Summer 2027 internship. As a Cybersecurity senior at Kennesaw State University with hands-on experience in identity and access management (IAM), systems automation, and incident response, I am excited about the opportunity to contribute to your security and engineering goals.",
    "Through my academic and applied coursework, I have developed deep proficiency in security monitoring, Linux and Windows system administration, packet analysis using Wireshark, and Python automation. My work focuses on threat detection, vulnerability remediation, and strengthening infrastructure resilience.",
    "In addition to core system security, I have practical experience in identity and access management (IAM), role-based access control (RBAC), and Active Directory administration. I hold the CompTIA Security+ certification and enjoy solving real-world infrastructure challenges while maintaining rigorous security standards.",
    "I am eager to bring my problem-solving skills, proactive defense mindset, and dedication to your team. Thank you for your time and consideration.",
    "Sincerely,\nMichael Azuka"
]

def render(paragraphs, out_path):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, leading=19, textColor=colors.HexColor('#1a365d'))
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontSize=9.5, leading=14, textColor=colors.HexColor('#4a5568'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, leading=14.5, textColor=colors.HexColor('#2d3748'))
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, leading=14.5, fontName='Helvetica-Bold', textColor=colors.HexColor('#1a365d'))
    
    doc = SimpleDocTemplate(str(out), pagesize=letter, rightMargin=54, leftMargin=54, topMargin=50, bottomMargin=50)
    story = []
    
    # Header
    story.append(Paragraph('<b>Michael Azuka</b>', title_style))
    story.append(Paragraph('Atlanta, GA &bull; 404-645-0373 &bull; mazuka146@gmail.com &bull; linkedin.com/in/michael-azuka', contact_style))
    story.append(Spacer(1, 14))
    
    # Salutation
    story.append(Paragraph(f'<b>{paragraphs[0]}</b>', bold_style))
    story.append(Spacer(1, 10))
    
    # Body Paragraphs
    for p in paragraphs[1:-1]:
        story.append(Paragraph(p, body_style))
        story.append(Spacer(1, 10))
        
    # Sign-off
    sign_text = paragraphs[-1].replace('\n', '<br/>')
    story.append(Spacer(1, 5))
    story.append(Paragraph(sign_text, body_style))
    
    doc.build(story)
    return str(out)

if __name__ == "__main__":
    out_file = Path(__file__).resolve().parent / "cover_letter.pdf"
    render(BODY, out_file)
    print(f"Generated {out_file}")

