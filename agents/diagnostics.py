"""
Agent Diagnostics Engine — Classifies application failures into actionable buckets.

Each failure record (records/<date>/<slug>.json + .log) is analyzed and returned
as a Diagnosis with a category and recommended action.  The supervisor uses this
to dispatch the right fix agent.

Categories:
  rule_gap    → unanswered question that can be fixed by adding a profile rule
  timeout     → job exceeded its time budget but didn't crash
  anti_bot    → WAF / CAPTCHA / bot detection blocked the page
  auth_wall   → site requires login/account the pipeline can't automate
  crash       → fill.py hit an unhandled exception (code fix candidate)
  site_dead   → DNS failure / 404 / domain unreachable
  duplicate   → already submitted (de-dup guard)
  unknown     → couldn't classify
"""
import datetime, json, pathlib, re
from typing import Any, Dict, List, Optional

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent


class Diagnosis:
    __slots__ = ("slug", "company", "role", "url", "status", "category",
                 "detail", "unanswered", "blocked", "log_tail", "retryable",
                 "suggested_action", "timestamp")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k, ""))
        self.retryable = kw.get("retryable", False)

    def to_dict(self) -> Dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}


# ---------------------------------------------------------------- classifiers
_BOT_HINTS = re.compile(
    r"captcha|cloudflare|challenge|bot.detect|access.denied|waf|"
    r"just.a.moment|verify.you.are.human|please.enable.cookies|"
    r"unusual.traffic|automated.access|rate.limit|too.many.requests",
    re.I)

_AUTH_HINTS = re.compile(
    r"sign.in|log.in|create.an?.account|sso|saml|okta|"
    r"authentication.required|session.expired|unauthorized|"
    r"please.register|account.required", re.I)

_CRASH_HINTS = re.compile(
    r"Traceback|Error:|Exception:|playwright.*error|"
    r"TimeoutError|NavigationAborted|net::ERR_", re.I)


def _read_log(log_path: pathlib.Path, tail: int = 3000) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        return text[-tail:]
    except Exception:
        return ""


def classify(rec: Dict[str, Any], log_tail: str = "") -> Diagnosis:
    """Classify a single failure record into an actionable category."""
    status = rec.get("status", "")
    url = rec.get("url", "")
    company = rec.get("company", "")
    role = rec.get("role", "")
    unanswered = rec.get("unanswered_questions", [])
    blocked = rec.get("blocked_sensitive_questions", [])
    combined = (log_tail + " " + status + " " + str(rec.get("error", ""))).lower()

    d = Diagnosis(
        slug=f"{company}_{role}".replace(" ", "_")[:60],
        company=company, role=role, url=url, status=status,
        unanswered=unanswered, blocked=blocked, log_tail=log_tail[-500:],
        timestamp=datetime.datetime.now().isoformat())

    # Already submitted → duplicate
    if status == "submitted":
        d.category = "duplicate"
        d.detail = "Already submitted successfully"
        return d

    # Site reported validation alert on required field
    m_val = re.search(r"\[Validation Alert\] Site reported: (?:Error-)?([^\n\r]+)", log_tail)
    if m_val:
        alert_text = m_val.group(1).strip()
        if not re.search(r"[a-zA-Z0-9]", alert_text):
            d.category = "stuck_page"
            d.detail = "Icon alert / unadvanceable submit button"
            d.retryable = True
            d.suggested_action = "auto_tuner_reheal"
            return d
        if re.search(r"file exceeds|upload size|file size|invalid file format", alert_text, re.I):
            d.category = "upload_error"
            d.detail = alert_text[:100]
            d.retryable = True
            d.suggested_action = "auto_tuner_upload"
            return d
        d.category = "validation_error"
        d.detail = f"Validation alert: {alert_text[:100]}"
        d.retryable = True
        d.suggested_action = "auto_heal_validation"
        return d

    # Unanswered or sensitive questions → rule gap (most common, most fixable)
    all_open = list(dict.fromkeys(unanswered + blocked))
    if not all_open:
        m_sens = re.search(r"\[Sensitive Question\] No rule for: \[(.+?)\]", log_tail)
        if m_sens:
            all_open = [m_sens.group(1).strip(" '\"")]
    if all_open or status == "skipped_sensitive":
        d.category = "rule_gap"
        d.unanswered = all_open
        d.detail = f"{len(all_open)} open question(s): {', '.join(all_open[:5])}"
        d.retryable = True
        d.suggested_action = "site_fixer_rules"
        return d

    # Bot / WAF detection
    if _BOT_HINTS.search(combined):
        d.category = "anti_bot"
        d.detail = "Bot detection or CAPTCHA challenge"
        d.suggested_action = "stealth_escalate"
        return d

    # Auth wall
    if _AUTH_HINTS.search(combined):
        d.category = "auth_wall"
        d.detail = "Login or account creation required"
        d.suggested_action = "fast_fail"
        return d

    # Timeout
    if "timeout" in combined or "exceeded" in combined:
        d.category = "timeout"
        d.detail = "Job exceeded time limit"
        d.retryable = True
        d.suggested_action = "extend_timeout"
        return d

    # Site dead
    if "getaddrinfo" in combined or "err_name" in combined or "404" in combined:
        d.category = "site_dead"
        d.detail = "Domain unreachable or page not found"
        d.suggested_action = "fast_fail"
        return d

    # Stuck page (did not advance after multiple clicks)
    if "page did not advance" in combined or "waiting for page transition" in combined:
        d.category = "stuck_page"
        d.detail = "Page did not advance after submit/next clicks"
        d.retryable = True
        d.suggested_action = "auto_tuner_reheal"
        return d

    # Crash (code bug)
    if _CRASH_HINTS.search(combined):
        d.category = "crash"
        d.detail = "Unhandled exception in fill.py"
        d.retryable = True
        d.suggested_action = "site_fixer_code"
        return d

    # Unknown
    d.category = "unknown"
    d.detail = f"Status: {status}"
    d.retryable = True
    d.suggested_action = "log_and_skip"
    return d


# ---------------------------------------------------------------- batch scan
def scan_day(day: Optional[str] = None) -> List[Diagnosis]:
    """Scan all records for a given day and return diagnoses."""
    d = AUTOFILL / "records" / (day or datetime.date.today().isoformat())
    results = []
    if not d.exists():
        return results
    for j in sorted(d.glob("*.json")):
        try:
            rec = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("status") == "submitted":
            continue
        log_tail = _read_log(j.with_suffix(".log"))
        results.append(classify(rec, log_tail))
    return results


def summary(diagnoses: List[Diagnosis]) -> Dict[str, int]:
    """Category counts for a list of diagnoses."""
    counts: Dict[str, int] = {}
    for d in diagnoses:
        counts[d.category] = counts.get(d.category, 0) + 1
    return counts
