"""Single source of truth for "is this role something the active profile should apply to?".

Default policy (strategy.json "internships_only": true): only internship / co-op roles.
Full-time, senior, operations-specialist, recruiter etc. roles are rejected.
"""
import json
import re
from pathlib import Path

_STRATEGY = Path(__file__).resolve().parent.parent / "strategy.json"

INTERN_RE = re.compile(
    r"\b(intern|interns|internship|internships|co-?op|summer\s+(?:analyst|associate|scholar|20\d\d)|"
    r"apprentice(?:ship)?|extern(?:ship)?|fellowship)\b",
    re.I,
)
# Even if "intern" appears, these mean it is not a student role (e.g. "Intern Program Manager").
NOT_STUDENT_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead\s+recruiter|manager\s+of|director|head\s+of|"
    r"recruit(?:er|ing)\s+(?:coordinator|specialist|partner)|program\s+manager,?\s+intern)\b",
    re.I,
)


def internships_only() -> bool:
    try:
        return bool(json.loads(_STRATEGY.read_text(encoding="utf-8")).get("internships_only", True))
    except Exception:
        return True


def is_internship(role: str) -> bool:
    r = role or ""
    return bool(INTERN_RE.search(r)) and not NOT_STUDENT_RE.search(r)


def reject_reason(role: str, allow_fulltime: bool = False) -> str:
    """Empty string means OK to apply; otherwise a human-readable skip reason."""
    if allow_fulltime or not internships_only():
        return ""
    if not is_internship(role):
        return f"not an internship (internships_only=true): {role!r}"
    return ""

