"""
Visual tools for Telegram:
1. Quick View PDF-to-Image renderer (allows mobile users to inspect resumes without downloading).
2. Live Headless Screen Cam (captures screenshots of active Playwright worker pages).
"""
import io
import os
import pathlib
import re
from typing import Optional, Tuple
from PIL import Image
import pypdfium2 as pdfium

HERE = pathlib.Path(__file__).resolve().parent.parent
RESUMES_DIR = HERE / "resumes"


def render_pdf_to_image_bytes(pdf_path: pathlib.Path, scale: float = 2.0) -> bytes:
    """Renders the first page of a PDF into PNG image bytes for instant Telegram photo viewing."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    doc = pdfium.PdfDocument(str(pdf_path))
    if len(doc) == 0:
        raise ValueError("PDF document is empty")
    
    page = doc[0]
    pil_img = page.render(scale=scale).to_pil()
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def find_latest_tailored_resume(company_query: Optional[str] = None) -> Optional[pathlib.Path]:
    """Finds the tailored PDF for a company, or falls back to latest or master."""
    tailored_dir = RESUMES_DIR / "tailored"
    if company_query and tailored_dir.exists():
        clean_q = re.sub(r"[^a-zA-Z0-9]", "", company_query.lower())
        for folder in tailored_dir.iterdir():
            if folder.is_dir() and clean_q in re.sub(r"[^a-zA-Z0-9]", "", folder.name.lower()):
                candidate_pdf = folder / "Candidate_Resume.pdf"
                if candidate_pdf.exists():
                    return candidate_pdf
                for pdf in folder.glob("*.pdf"):
                    if "letter" not in pdf.name.lower():
                        return pdf

    # Search for any recent tailored PDF (excluding cover letters)
    if tailored_dir.exists():
        all_pdfs = sorted(tailored_dir.glob("*/*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        for pdf in all_pdfs:
            if "letter" not in pdf.name.lower():
                return pdf

    # Default master candidate resume
    master = RESUMES_DIR / "Candidate_Resume.pdf"
    if master.exists():
        return master
    return None


def find_latest_tailored_letter(company_query: Optional[str] = None) -> Optional[pathlib.Path]:
    """Finds the tailored cover letter PDF for a company, or falls back to latest or master."""
    tailored_dir = RESUMES_DIR / "tailored"
    if company_query and tailored_dir.exists():
        clean_q = re.sub(r"[^a-zA-Z0-9]", "", company_query.lower())
        for folder in tailored_dir.iterdir():
            if folder.is_dir() and clean_q in re.sub(r"[^a-zA-Z0-9]", "", folder.name.lower()):
                candidate_pdf = folder / "Cover_Letter.pdf"
                if candidate_pdf.exists():
                    return candidate_pdf
    
    # Check general cover letter
    cl = RESUMES_DIR / "Cover_Letter.pdf"
    if cl.exists():
        return cl
    return None


def capture_active_worker_screenshot(worker_id: int = 1) -> Optional[Tuple[bytes, str]]:
    """
    Attempts to capture an instant screenshot from an active worker or latest page snapshot.
    Returns (image_bytes, caption) or None.
    """
    records_dir = HERE / "records"
    if not records_dir.exists():
        return None

    # Search for the most recently modified failure or snapshot HTML file
    recent_htmls = sorted(records_dir.glob("*/*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not recent_htmls:
        return None

    target_html = recent_htmls[0]
    caption = f"📸 Snapshot: {target_html.stem.replace('_', ' ')}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(target_html.as_uri(), timeout=10000, wait_until="domcontentloaded")
            screenshot_bytes = page.screenshot(type="png", full_page=False)
            browser.close()
            return screenshot_bytes, caption
    except Exception:
        return None
