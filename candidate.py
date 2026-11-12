"""
Whose applications this run sends. Everything about a person lives in their candidate home, never in code:
  .env           CANDIDATE_* facts (name, contact, school, degree, ...) and their own tokens
  profile.json   answer rules + "standing_facts" (plain sentences agents may rely on)
  resumes/       resume_gen.py, master_resume.pdf, cover letter, transcript
  applications.csv, results.csv, queue*.txt, caches, Telegram files

JOBDEC_HOME=<folder> selects a candidate (e.g. profiles/michael). Unset, the original single-user layout is used,
so the owner's existing files keep working: .env two folders up, profile.json here, resumes/ and applications.csv
one folder up.
"""
import json
import os
import pathlib

AUTOFILL = pathlib.Path(__file__).resolve().parent
_home = os.getenv("JOBDEC_HOME", "").strip()
HOME = (AUTOFILL / _home).resolve() if _home else None


def path(name, legacy):
    """<JOBDEC_HOME>/<name> when a candidate home is set, else the original single-user location."""
    return HOME / name if HOME else legacy


_legacy_env = AUTOFILL / ".env" if (AUTOFILL / ".env").exists() else (AUTOFILL.parent / ".env" if (AUTOFILL.parent / ".env").exists() else AUTOFILL.parent.parent / ".env")
_legacy_resumes = AUTOFILL / "resumes" if (AUTOFILL / "resumes").exists() else AUTOFILL.parent / "resumes"
_legacy_applications = AUTOFILL / "applications.csv" if (AUTOFILL / "applications.csv").exists() else AUTOFILL.parent / "applications.csv"

ENV = path(".env", _legacy_env)
PROFILE = path("profile.json", AUTOFILL / "profile.json")
RESUMES = path("resumes", _legacy_resumes)
APPLICATIONS = path("applications.csv", _legacy_applications)
DATA = path("data", AUTOFILL)  # results.csv, queues, response cache, Telegram state
if HOME:
    DATA.mkdir(parents=True, exist_ok=True)

try:  # this candidate's facts win over anything already in the environment
    from dotenv import load_dotenv
    load_dotenv(ENV, override=bool(HOME))
except ImportError:
    pass


def fact(key, default=""):
    """CANDIDATE_<key> from this candidate's .env. Missing means unknown: "" (never another person's value)."""
    return os.getenv(f"CANDIDATE_{key}", default).strip()


def profile():
    try:
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {"rules": []}


def standing_facts():
    return [s for s in profile().get("standing_facts", []) if isinstance(s, str) and s.strip()]
