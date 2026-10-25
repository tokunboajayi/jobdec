"""
Agent 1 - Job Scout. Reads the full job description and scores fit 0-10 against the real resume.
Results are cached per job (results_engine.score_job uses the cache automatically).
"""
from typing import List, Literal
from pydantic import BaseModel
from . import llm, jd_fetch, context, local

CATEGORIES = ("product", "ai_automation", "analyst_data", "business_systems", "consulting_strategy",
              "finance_tech", "swe", "other")


class ScoutResult(BaseModel):
    title: str
    category: Literal["product", "ai_automation", "analyst_data", "business_systems",
                      "consulting_strategy", "finance_tech", "swe", "other"]
    is_internship: bool
    term: str
    eligible: bool
    ineligible_reason: str
    location: str
    fit_score: int
    reasons: List[str]
    gaps: List[str]
    keywords: List[str]


SYSTEM = f"""You screen internship postings for one candidate and score how well each fits.

{context.FACT_TEXT}

# SCORING (fit_score is an integer 0-10)
- 9-10: role is product / AI-automation / analyst / business-systems work AND the posting's must-haves are
  clearly covered by the resume above.
- 7-8: right role family, most requirements covered, minor gaps.
- 5-6: adjacent role (consulting, finance-tech, operations) or notable gaps.
- 0-4: software-engineering-heavy (writing production code is the core job), hardware, or major gaps.
eligible=false (and fit_score 0) when the candidate cannot apply: requires a master's/PhD or graduating
before May 2028 / "new grad", full-time or experienced hire, high school program, co-op that requires leaving
school for a semester, non-US location without remote option, or a citizenship/clearance the facts rule out.
Use only facts above - never assume skills the resume doesn't show. reasons and gaps: 1-4 short items each.
keywords: up to 8 skills/terms from the posting that the resume genuinely matches (used to reorder bullets).
category is the role's main function. term: e.g. "Summer 2027", or "" if not stated."""


def scout(company, role, url, force=False):
    """Returns a dict (cached) or None if the agent isn't available / the posting can't be read."""
    import results_engine as RE
    key = RE.job_key(company, role, url)
    eng = llm.engine("job_scout")
    if not force:
        hit = llm.cache_get("scout", key)
        if hit and not (hit.get("engine") == "local" and eng == "ai"):  # AI re-scores rule-based results
            return hit
    if eng == "off":
        return None
    jd, source = jd_fetch.fetch(url)
    if not jd:
        return None
    if eng == "local":
        d = local.scout(company, role, url, jd)
        d["jd_source"] = source
        llm.cache_put("scout", key, d)
        return d
    user = f"Company: {company}\nListed title: {role}\nURL: {url}\n\n# JOB POSTING ({source})\n{jd}"
    r = llm.ask("job_scout", "fast", SYSTEM, user, ScoutResult)
    if r is None:
        return None
    d = r.model_dump()
    d["fit_score"] = max(0, min(10, int(d["fit_score"])))
    if not d["eligible"]:
        d["fit_score"] = 0
    d["jd_source"], d["engine"] = source, "ai"
    from . import smarts
    d.update(company=company, url=url, deadline=smarts.extract_deadline(jd))
    llm.cache_put("scout", key, d)
    return d


def cached(company, role, url):
    import results_engine as RE
    return llm.cache_get("scout", RE.job_key(company, role, url))
