"""
Per-application cover letter: the generic letter (resumes/cover_letter_gen.py) addressed to this company and role,
with the experience paragraph that best matches the posting first. Same facts as the generic letter, nothing new.

Toggle: strategy.json -> agents.autonomy.cover_letter = "auto" | "off". Off (or any failure) -> fill.py uploads the
generic Ajayi_Olatokunbo_Cover_Letter.pdf as before.
"""
import importlib.util
import re

from . import context, jd_fetch, llm
from .resume_tailor import OUT_DIR

FILENAME = "Cover_Letter.pdf"


def _gen():
    spec = importlib.util.spec_from_file_location("cover_letter_gen", context.RESUMES / "cover_letter_gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_company(company):
    """'JohnsHopkinsAppliedPhysicsLaboratory' -> 'Johns Hopkins Applied Physics Laboratory'.
    Splits only lower->Upper+lower boundaries; names still mixed-case after that ('HpIq') get the generic letter."""
    name = (company or "").strip()
    if " " not in name:
        split = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", name)
        # 'HpIq' -> 'Hp Iq' is no better: keep it unsplit so body_for() falls back to the generic wording
        name = split if all(len(w) >= 3 for w in split.split()) else name
    return name


def clean_role(role):
    """'AI Intern - Research [Laurel, MD; 21d old]' -> 'AI Intern - Research'."""
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", role or "").strip(" -")


def body_for(company, role, jd=""):
    gen = _gen()
    opening, delta, wa, close, sign = gen.BODY[1], gen.BODY[2], gen.BODY[3], gen.BODY[4], gen.BODY[5]
    company, role = clean_company(company), clean_role(role)
    if re.search(r"[a-z][A-Z]", company):  # still scraped-looking ("HpIq"): a generic letter beats a garbled name
        company = ""
    if company and role:
        opening = opening.replace("applying for your Summer 2027 internship",
                                  f"applying for the {role} position at {company}")
        close = close.replace("to your team", f"to {company}")
    words = set(re.findall(r"[a-z]+", (jd or "").lower()))
    # the paragraph sharing more words with the posting goes first; ties keep Delta first
    overlap = lambda p: len(words & set(re.findall(r"[a-z]+", p.lower())))
    exp = sorted([delta, wa], key=overlap, reverse=True) if words else [delta, wa]
    return [gen.BODY[0], opening, *exp, close, sign]


def build(company, role, url):
    """Path of this job's cover letter PDF, or None (toggle off / no reportlab / render failed)."""
    if llm.engine("cover_letter") == "off" or importlib.util.find_spec("reportlab") is None:
        return None
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "job"
    out = OUT_DIR / slug / FILENAME
    if out.exists():
        return str(out)
    try:
        jd, _ = jd_fetch.fetch(url)
    except Exception:
        jd = ""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        _gen().render(body_for(company, role, jd), out)
        return str(out)
    except Exception as e:
        print(f"     [Cover Letter] skipped, using the generic letter: {e}")
        return None
