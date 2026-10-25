"""
Agent 2 - Resume Tailor. Reorders the REAL resume for one job: bullet order inside each job,
skills-line order, and section order. It cannot add, drop or edit text - the verifier only accepts
permutations of what's in resumes/resume_gen.py MASTER, so every tailored PDF says exactly what
Ajayi_Olatokunbo_Resume.pdf says, in a different order.
"""
import copy, importlib.util, os, re
from typing import List
from pydantic import BaseModel
from . import llm, jd_fetch, context, local

OUT_DIR = context.RESUMES / "tailored"
FILENAME = os.getenv("RESUME_FILENAME", "Candidate_Resume.pdf")   # what recruiters see when they download it


class EntryOrder(BaseModel):
    org: str
    bullet_order: List[int]


class TailorPlan(BaseModel):
    entries: List[EntryOrder]
    skills_order: List[str]
    section_order: List[str]
    rationale: str


def _layout():
    m = context.MASTER
    return {
        "entries": {e["org"]: len(e.get("bullets", [])) for s in m["sections"] for e in s.get("entries", []) if e.get("bullets")},
        "skills": [k for s in m["sections"] for k, _ in s.get("labeled", [])],
        "sections": [s["title"] for s in m["sections"]],
    }


SYSTEM = f"""You reorder a resume so the most relevant real content comes first for one job posting.

{context.resume_text()}

# WHAT YOU MAY CHANGE (nothing else)
1. entries: for each job/activity below, the order of its bullets, given as the bracketed indices [0], [1], ...
   Every index must appear exactly once. Put the bullets that best match the posting first.
2. skills_order: the order of the ADDITIONAL INFORMATION labels.
3. section_order: the order of the section titles. Keep PROFESSIONAL EXPERIENCE first.
You cannot add, remove or reword anything. rationale: one sentence on what you prioritized."""


def _verify(plan):
    lay = _layout()
    bullet_order = {}
    for e in plan.entries:
        n = lay["entries"].get(e.org)
        if n is None:
            continue
        if sorted(e.bullet_order) == list(range(n)):
            bullet_order[e.org] = list(e.bullet_order)
    skills = [k for k in plan.skills_order if k in lay["skills"]]
    skills += [k for k in lay["skills"] if k not in skills]
    sections = plan.section_order if sorted(plan.section_order) == sorted(lay["sections"]) else lay["sections"]
    if sections[0] != "PROFESSIONAL EXPERIENCE":
        sections = ["PROFESSIONAL EXPERIENCE"] + [s for s in sections if s != "PROFESSIONAL EXPERIENCE"]
    return {"bullet_order": bullet_order, "labeled_order": skills, "section_order": sections}


def _render(ov, out_path):
    data = copy.deepcopy(context.MASTER)
    for s in data["sections"]:
        for e in s.get("entries", []):
            if e["org"] in ov["bullet_order"]:
                e["bullets"] = [e["bullets"][i] for i in ov["bullet_order"][e["org"]]]
        if "labeled" in s:
            d = dict(s["labeled"])
            s["labeled"] = [[k, d[k]] for k in ov["labeled_order"] if k in d]
    by_title = {s["title"]: s for s in data["sections"]}
    data["sections"] = [by_title[t] for t in ov["section_order"]]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bottom = context.resume_gen().render(data, str(out_path))
    return bottom > 36  # still fits on one page


def tailor(company, role, url, default_resume):
    """Returns the path of a tailored PDF, or default_resume if tailoring isn't possible."""
    import results_engine as RE
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "job"
    out = OUT_DIR / slug / FILENAME
    if out.exists():
        return str(out)
    eng = llm.engine("resume_tailor")
    if eng == "off":
        return default_resume
    if importlib.util.find_spec("reportlab") is None:
        print("     [Resume Tailor] reportlab not installed (pip install reportlab) - using the standard resume")
        return default_resume
    jd, _ = jd_fetch.fetch(url)
    if not jd:
        return default_resume
    if eng == "local":
        sc = llm.cache_get("scout", RE.job_key(company, role, url)) or {}
        ov = local.tailor_overlay(jd, sc.get("category", RE.score_job(company, role, url)[1]))
        try:
            if not _render(ov, out):
                out.unlink(missing_ok=True)
                return default_resume
        except Exception:
            return default_resume
        (out.parent / "plan.txt").write_text(f"rule-based: bullets ranked by overlap with the posting\n{ov}\n", encoding="utf-8")
        return str(out)
    scout = llm.cache_get("scout", RE.job_key(company, role, url)) or {}
    hint = f"\nMatched keywords from screening: {', '.join(scout.get('keywords', []))}" if scout else ""
    plan = llm.ask("resume_tailor", "writer", SYSTEM, f"Company: {company}\nRole: {role}{hint}\n\n# JOB POSTING\n{jd}", TailorPlan)
    if plan is None:
        return default_resume
    ov = _verify(plan)
    try:
        if not _render(ov, out):
            out.unlink(missing_ok=True)
            return default_resume
    except Exception:
        return default_resume
    (out.parent / "plan.txt").write_text(f"{plan.rationale}\n{ov}\n", encoding="utf-8")
    return str(out)
