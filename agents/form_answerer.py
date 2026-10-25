"""
Agent 3 - Form Answerer. Answers application questions that have no rule in profile.json,
using only the verified facts. Hooked into ai_responder.generate_response / pick_best_option.

Returns:
  str  - the answer (an exact option for dropdowns)
  ""   - deliberately no answer (sensitive / not in facts / failed verification) -> the job skips or logs it
  None - agent unavailable -> caller uses its old rule-based logic
"""
import hashlib, json, re
from typing import Literal
from pydantic import BaseModel
from . import llm, context

SENSITIVE = re.compile(
    r"convict|felon|criminal|misdemeanor|arrest|terminat|discharged|dismissed|fired|clearance|non-?compete|"
    r"non-?solicit|obligation|previously applied|relative|family member|related to|drug|export|itar|debar|"
    r"exclu|conflict of interest|gender|sex\b|race|ethnic|hispanic|latino|veteran|disabilit|orientation|"
    r"pronoun|transgender|salary|compensation|pay expectation", re.I)


class FormAnswer(BaseModel):
    answer: str
    chosen_option: str
    confidence: Literal["high", "medium", "low"]
    answerable_from_facts: bool
    rationale: str


SYSTEM = f"""You fill in job application questions for the candidate below, using ONLY these facts.

{context.FACT_TEXT}

# RULES
- If the facts directly answer the question, answer it. If they don't, set answerable_from_facts=false and
  leave answer/chosen_option empty. Never guess about legal history, background, relatives, prior employment,
  clearances, demographics or pay - those must come from the facts or stay empty.
- Dropdown/radio/yes-no: chosen_option must be copied EXACTLY from the options list. Also put it in answer.
- Free text: 1-3 plain sentences in first person. Only claims and numbers that appear in the resume above.
  Use contractions. Never use: leverage, passionate, delve, synergy, spearhead.
- Short factual fields (city, school, GPA, graduation date, LinkedIn URL, phone): just the value.
- confidence=high only when the facts state it outright."""


def _key(label, options, company):
    opts = "|".join(options or [])
    return hashlib.sha1(f"{company.lower()}::{label.lower()}::{opts}".encode()).hexdigest()[:20]


def answer(label, field_type="text", options=None, company="", role=""):
    # Rule-based mode: profile.json rules + ai_responder's fact templates ARE the answerer, so hand back to them.
    if llm.engine("form_answerer") != "ai":
        return None
    options = [str(o).strip() for o in (options or []) if str(o).strip()]
    options = [o for o in options if not re.match(r"^(select|choose|please select|--)", o, re.I)]
    key = _key(label, options, company)
    hit = llm.cache_get("answers", key)
    if hit is not None:
        return hit["answer"]
    scout = {}
    if company and role:
        try:
            import results_engine as RE
            scout = next((v for k, v in (json.loads((llm.CACHE_DIR / "scout.json").read_text(encoding="utf-8")).items())
                          if k.startswith(RE.norm(company)[:6])), {}) or {}
        except Exception:
            scout = {}
    user = (f"Company: {company or 'unknown'}\nRole: {role or 'internship'}\n"
            + (f"Role summary: {scout.get('title', '')} - {', '.join(scout.get('keywords', []))}\n" if scout else "")
            + f"Field type: {field_type}\nQuestion: {label}\n"
            + (f"Options: {json.dumps(options, ensure_ascii=False)}\n" if options else ""))
    r = llm.ask("form_answerer", "writer", SYSTEM, user, FormAnswer)
    if r is None:
        return None
    out = _verify(r, label, options)
    llm.cache_put("answers", key, {"label": label, "company": company, "answer": out,
                                    "confidence": r.confidence, "rationale": r.rationale})
    return out


def _verify(r, label, options):
    if not r.answerable_from_facts or r.confidence == "low":
        return ""
    if options:
        pick = r.chosen_option or r.answer
        exact = next((o for o in options if o.strip().lower() == pick.strip().lower()), None)
        return exact or ""
    text = (r.answer or "").strip()
    if not text or context.BANNED.search(text):
        return ""
    if SENSITIVE.search(label) and r.confidence != "high":
        return ""
    if context.unsupported_numbers(text):
        return ""  # a number not in the resume = possible invention
    return text
