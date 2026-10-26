"""
The only facts agents may use: the master resume (resumes/resume_gen.py MASTER, identical to
Ajayi_Olatokunbo_Resume.pdf) plus the explicit answers in profile.json. Verifiers check agent
output against FACT_TEXT so nothing invented reaches an application.
"""
import ast, importlib.util, json, os, pathlib, re

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
RESUMES = AUTOFILL.parent / "resumes"

DEFAULT_MASTER = {
    "name": os.getenv("CANDIDATE_FULL_NAME", "Candidate"),
    "contact": f"{os.getenv('CANDIDATE_LOCATION_TEXT', 'Atlanta, GA')} • {os.getenv('CANDIDATE_EMAIL', 'candidate@example.com')} • {os.getenv('CANDIDATE_PHONE', '555-0199')}",
    "sections": [
        {"title": "EDUCATION", "entries": [
            {"org": os.getenv("CANDIDATE_UNIVERSITY", "State University"), "loc": os.getenv("CANDIDATE_CITY", "Atlanta"), "lines": [
                f"{os.getenv('CANDIDATE_DEGREE', 'Bachelor of Science')}, {os.getenv('CANDIDATE_MAJOR', 'Computer Science')}; Expected Graduation: {os.getenv('CANDIDATE_EXPECTED_GRAD_DATE', 'May 2027')}",
                f"Cumulative GPA: {os.getenv('CANDIDATE_GPA', '3.80')}"
            ]}
        ]},
        {"title": "TECHNICAL SKILLS", "labeled": [
            ["Languages & Tools", os.getenv("CANDIDATE_TOP_SKILLS", "Python, SQL, Playwright, Git, Docker")],
            ["Focus Areas", "Process automation, software engineering, agentic workflows, data pipelines"]
        ]}
    ]
}


def _read_master():
    """MASTER data from resume_gen.py's source, or clean fallback if missing."""
    for candidate_path in [RESUMES / "resume_gen.py", AUTOFILL / "resumes" / "resume_gen.py"]:
        if candidate_path.exists():
            try:
                tree = ast.parse(candidate_path.read_text(encoding="utf-8"))
                node = next((n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MASTER"), None)
                if node:
                    return ast.literal_eval(node.value)
            except Exception:
                pass
    return DEFAULT_MASTER


def resume_gen():
    """The PDF renderer module (needs `pip install reportlab`). Raises ImportError if missing."""
    for candidate_path in [RESUMES / "resume_gen.py", AUTOFILL / "resumes" / "resume_gen.py"]:
        if candidate_path.exists():
            spec = importlib.util.spec_from_file_location("resume_gen", candidate_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
    raise ImportError("resume_gen.py not found in resumes directory.")


MASTER = _read_master()


def resume_text():
    out = [MASTER["name"], MASTER["contact"]]
    for s in MASTER["sections"]:
        out.append(f"\n## {s['title']}")
        for e in s.get("entries", []):
            out.append(f"{e['org']} | {e.get('role', '')} | {e.get('loc', '')} | {e.get('dates', '')}")
            out += [f"- {l}" for l in e.get("lines", [])]
            out += [f"- [{i}] {b}" for i, b in enumerate(e.get("bullets", []))]
        out += s.get("plain", [])
        out += [f"{k}: {v}" for k, v in s.get("labeled", [])]
    return "\n".join(out)


def profile_answers():
    """Explicit answers AJ has set in profile.json (question pattern -> answer)."""
    try:
        rules = json.loads((AUTOFILL / "profile.json").read_text(encoding="utf-8"))["rules"]
    except Exception:
        return []
    return [(r["q"], r["a"]) for r in rules if isinstance(r.get("a"), str) and r["a"] not in ("ASK", "TODAY", "check", "uncheck")]


def facts_block():
    lines = ["# CANDIDATE RESUME (the only work history, skills and numbers you may use)", resume_text(),
             "", "# EXPLICIT ANSWERS SET BY THE CANDIDATE (question pattern -> answer)"]
    lines += [f"- /{q}/ -> {a}" for q, a in profile_answers()]
    lines += ["", "# STANDING FACTS",
              "- US citizen; authorized to work in the US; never needs visa sponsorship.",
              "- Undergraduate junior (class of May 2028), Georgia State University, BBA Computer Information Systems (AI & Analytics).",
              "- Based in Atlanta, GA. Open to relocating for a summer internship.",
              "- Previously employed by Delta Air Lines and W. A. Investments. Never previously worked, interned, or contracted for any other company or organization.",
              "- Over 18 years of age; legally an adult.",
              "- Able to provide official or unofficial academic transcripts upon request.",
              "- No non-compete agreements, non-solicitation, or restrictive covenants with current or former employers.",
              "- Never held a U.S. security clearance; eligible to obtain security clearance if required.",
              "- No disability; not a protected veteran; has never served in the U.S. military; not a military spouse.",
              "- Salary expectation is flexible and open; willing to accept standard company internship rate.",
              "- Cumulative GPA from candidate profile.",
              "- No conflict of interest or personal financial interest in vendor firms or competitors.",
              "- No professional license infractions, misconduct, or disciplinary actions.",
              "- Will not maintain outside employment or concurrent commitments during internship.",
              "- Secondary contact number matches primary candidate phone number.",
              "- Agrees to mandatory arbitration and dispute resolution program terms.",
              "- Preferred job alert frequency is as frequent as possible (1 day or Daily).",
              "- U.S. Citizen with no visa requirement: visa type and expiration date are not applicable (N/A)."]
    return "\n".join(lines)


FACT_TEXT = facts_block()
# numbers that may appear in generated text: from the resume and AJ's answers only (not question patterns)
_NUMS = set(re.findall(r"\d[\d,.]*\+?", resume_text() + " " + " ".join(a for _, a in profile_answers())))


def unsupported_numbers(text):
    """Numbers in `text` that don't appear anywhere in the facts (a strong sign of invention)."""
    found = re.findall(r"\d[\d,.]*\+?", text or "")
    return [n for n in found if n.rstrip(".,") not in {x.rstrip(".,") for x in _NUMS} and len(n.strip(".,")) > 0
            and n.strip(".,") not in ("2027", "2028", "1", "2", "3")]


BANNED = re.compile(r"\b(leverage[sd]?|leveraging|passionate|delve|synerg\w*|spearhead\w*)\b", re.I)


def employers():
    return [e["org"] for s in MASTER["sections"] for e in s.get("entries", []) if e.get("bullets")]
