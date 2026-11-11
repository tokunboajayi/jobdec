"""A fictional candidate for tests (no real person's data): .env-style facts plus resumes/ in tests/fixtures/candidate."""
import pathlib
import re

import candidate
from agents import context

RESUMES = pathlib.Path(__file__).resolve().parent / "fixtures" / "candidate" / "resumes"
FACTS = {
    "FULL_NAME": "Jordan Sample", "FIRST_NAME": "Jordan", "LAST_NAME": "Sample",
    "EMAIL": "jordan.sample@example.com", "PHONE": "555-010-0199", "LOCATION_TEXT": "Springfield, IL",
    "CITY": "Springfield", "STATE": "Illinois", "ZIP_CODE": "62701",
    "UNIVERSITY": "Example State University", "DEGREE": "Bachelor of Science", "MAJOR": "Information Security",
    "EXPECTED_GRAD_DATE": "May 2027", "GPA": "3.50", "LINKEDIN_URL": "https://www.linkedin.com/in/jordan-sample-example",
}


def use(monkeypatch, tmp_path):
    """Make the fictional candidate the active one for this test (tailor learning state goes to tmp_path)."""
    from agents import tailor_learning
    monkeypatch.setattr(tailor_learning, "_ENGINE", tailor_learning.TailorLearningEngine(tmp_path / "tailor_learning.json"))
    for k, v in FACTS.items():
        monkeypatch.setenv(f"CANDIDATE_{k}", v)
    monkeypatch.setattr(candidate, "RESUMES", RESUMES)
    monkeypatch.setattr(context, "RESUMES", RESUMES)
    monkeypatch.setattr(context, "MASTER", context._read_master())
    monkeypatch.setattr(context, "FACT_TEXT", context.facts_block())
    nums = context.resume_text() + " " + " ".join(a for _, a in context.profile_answers())
    monkeypatch.setattr(context, "_NUMS", set(re.findall(r"\d[\d,.]*\+?", nums)))
    return FACTS
