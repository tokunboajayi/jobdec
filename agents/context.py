"""
The only facts agents may use: the master resume (resumes/resume_gen.py MASTER, identical to
Ajayi_Olatokunbo_Resume.pdf) plus the explicit answers in profile.json. Verifiers check agent
output against FACT_TEXT so nothing invented reaches an application.
"""
import ast, importlib.util, json, os, pathlib, re

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(AUTOFILL))
import candidate as C  # noqa: E402

RESUMES = C.RESUMES

# no resume_gen.py: only the candidate's own .env facts, blank where unknown (never another person's details)
DEFAULT_MASTER = {
    "name": C.fact("FULL_NAME"),
    "contact": " • ".join(x for x in (C.fact("LOCATION_TEXT"), C.fact("EMAIL"), C.fact("PHONE")) if x),
    "sections": [
        {"title": "EDUCATION", "entries": [
            {"org": C.fact("UNIVERSITY"), "loc": C.fact("CITY"), "lines": [
                f"{C.fact('DEGREE')}, {C.fact('MAJOR')}; Expected Graduation: {C.fact('EXPECTED_GRAD_DATE')}",
                f"Cumulative GPA: {C.fact('GPA')}"
            ]}
        ]},
        {"title": "TECHNICAL SKILLS", "labeled": [["Languages & Tools", C.fact("TOP_SKILLS")]]}
    ]
}


def _read_master():
    """MASTER data from resume_gen.py's source, or clean fallback if missing."""
    for candidate_path in [RESUMES / "resume_gen.py"]:
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
    for candidate_path in [RESUMES / "resume_gen.py"]:
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
    """Explicit answers the candidate set in profile.json (question pattern -> answer)."""
    try:
        rules = C.profile()["rules"]
    except Exception:
        return []
    return [(r["q"], r["a"]) for r in rules if isinstance(r.get("a"), str) and r["a"] not in ("ASK", "TODAY", "check", "uncheck")]


def facts_block():
    lines = ["# CANDIDATE RESUME (the only work history, skills and numbers you may use)", resume_text(),
             "", "# EXPLICIT ANSWERS SET BY THE CANDIDATE (question pattern -> answer)"]
    lines += [f"- /{q}/ -> {a}" for q, a in profile_answers()]
    lines += ["", "# STANDING FACTS"] + [f"- {f}" for f in C.standing_facts()]
    return "\n".join(lines)


FACT_TEXT = facts_block()
# numbers that may appear in generated text: from the resume and the candidate's answers only (not question patterns)
_NUMS = set(re.findall(r"\d[\d,.]*\+?", resume_text() + " " + " ".join(a for _, a in profile_answers())))


def unsupported_numbers(text):
    """Numbers in `text` that don't appear anywhere in the facts (a strong sign of invention)."""
    found = re.findall(r"\d[\d,.]*\+?", text or "")
    return [n for n in found if n.rstrip(".,") not in {x.rstrip(".,") for x in _NUMS} and len(n.strip(".,")) > 0
            and n.strip(".,") not in ("2027", "2028", "1", "2", "3")]


BANNED = re.compile(r"\b(leverage[sd]?|leveraging|passionate|delve|synerg\w*|spearhead\w*)\b", re.I)


def employers():
    return [e["org"] for s in MASTER["sections"] for e in s.get("entries", []) if e.get("bullets")]
