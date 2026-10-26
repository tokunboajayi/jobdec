"""
Job Validator: Fast pre-flight check to verify if a job posting is active or closed.
Prevents launching heavy headless browser sessions for expired/closed requisitions.
"""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CLOSED_PATTERNS = [
    re.compile(r"job\s+(?:is\s+)?(?:no\s+longer\s+available|closed|expired|filled)", re.I),
    re.compile(r"this\s+(?:posting|position|job)\s+has\s+been\s+(?:closed|filled|removed)", re.I),
    re.compile(r"no\s+longer\s+accepting\s+applications", re.I),
    re.compile(r"job\s+not\s+found", re.I),
    re.compile(r"requisition\s+closed", re.I),
    re.compile(r"we\s+are\s+unable\s+to\s+find\s+the\s+page", re.I),
]

_STATUS_CACHE: Dict[str, Tuple[bool, str]] = {}


def _get(url: str, timeout: int = 5) -> Tuple[int, str]:
    """Lightweight HTTP GET returning status code and response body."""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="ignore")
            return code, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def is_job_active(url: str, timeout: int = 5) -> Tuple[bool, str]:
    """
    Checks if a job posting is active.
    Returns (is_live: bool, reason: str).
    """
    clean_url = url.split("?")[0].strip()
    if clean_url in _STATUS_CACHE:
        return _STATUS_CACHE[clean_url]

    # 1. Greenhouse Embed / Jobs API
    m_gh_embed = re.search(r"boards(?:\.eu)?\.greenhouse\.io/embed/job_app\?token=(\d+)", url)
    if m_gh_embed:
        token = m_gh_embed.group(1)
        api_url = f"https://boards-api.greenhouse.io/v1/boards/embed/jobs/{token}"
        code, body = _get(api_url, timeout=timeout)
        if code in (404, 410):
            res = (False, f"Greenhouse job {token} not found (HTTP {code})")
            _STATUS_CACHE[clean_url] = res
            return res
        if code == 200 and body:
            try:
                data = json.loads(body)
                if not data.get("title"):
                    res = (False, "Greenhouse job empty title / closed")
                    _STATUS_CACHE[clean_url] = res
                    return res
            except Exception:
                pass

    m_gh = re.search(r"(job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if m_gh:
        board = m_gh.group(2)
        job_id = m_gh.group(3)
        api_domain = "boards-api.eu.greenhouse.io" if ".eu" in m_gh.group(1) else "boards-api.greenhouse.io"
        api_url = f"https://{api_domain}/v1/boards/{board}/jobs/{job_id}"
        code, body = _get(api_url, timeout=timeout)
        if code in (404, 410):
            res = (False, f"Greenhouse job {job_id} on {board} not found (HTTP {code})")
            _STATUS_CACHE[clean_url] = res
            return res
        if code == 200 and body:
            try:
                data = json.loads(body)
                if not data.get("title"):
                    res = (False, "Greenhouse job closed")
                    _STATUS_CACHE[clean_url] = res
                    return res
                res = (True, "Greenhouse API verified active")
                _STATUS_CACHE[clean_url] = res
                return res
            except Exception:
                pass

    # 2. Lever API
    m_lever = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if m_lever:
        company = m_lever.group(1)
        posting_id = m_lever.group(2)
        api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
        code, body = _get(api_url, timeout=timeout)
        if code in (404, 410):
            res = (False, f"Lever posting {posting_id} closed/not found (HTTP {code})")
            _STATUS_CACHE[clean_url] = res
            return res
        if code == 200:
            res = (True, "Lever API verified active")
            _STATUS_CACHE[clean_url] = res
            return res

    # 3. Ashby API
    m_ashby = re.search(r"jobs\.ashbyhq\.com/([^/?]+)/([0-9a-f-]{36})", url)
    if m_ashby:
        board = m_ashby.group(1)
        job_id = m_ashby.group(2)
        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        code, body = _get(api_url, timeout=timeout)
        if code == 200 and body:
            try:
                data = json.loads(body)
                jobs = data.get("jobs", [])
                match = any(j.get("id") == job_id for j in jobs)
                if not match:
                    res = (False, f"Ashby job {job_id} not found in board {board}")
                    _STATUS_CACHE[clean_url] = res
                    return res
                res = (True, "Ashby API verified active")
                _STATUS_CACHE[clean_url] = res
                return res
            except Exception:
                pass

    # 4. Workday CXS Endpoint
    if "myworkdayjobs.com" in url:
        u = urllib.parse.urlparse(url)
        parts = [p for p in u.path.split("/") if p]
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        if "job" in parts:
            site = parts[0]
            tail = "/".join(parts[parts.index("job"):])
            tail = re.sub(r"/apply.*$", "", tail)
            tenant = u.netloc.split(".")[0]
            cxs_url = f"https://{u.netloc}/wday/cxs/{tenant}/{site}/{tail}"
            code, body = _get(cxs_url, timeout=timeout)
            if code in (404, 410):
                res = (False, f"Workday posting closed/expired (HTTP {code})")
                _STATUS_CACHE[clean_url] = res
                return res
            if code == 200 and body:
                try:
                    data = json.loads(body)
                    if not data.get("jobPostingInfo"):
                        res = (False, "Workday jobPostingInfo missing/closed")
                        _STATUS_CACHE[clean_url] = res
                        return res
                    res = (True, "Workday CXS verified active")
                    _STATUS_CACHE[clean_url] = res
                    return res
                except Exception:
                    pass

    # 5. Fallback Page Text Analysis
    code, body = _get(url, timeout=timeout)
    if code in (404, 410):
        res = (False, f"Page returned HTTP {code}")
        _STATUS_CACHE[clean_url] = res
        return res

    if body:
        for pat in CLOSED_PATTERNS:
            if pat.search(body):
                res = (False, f"Page matches closed pattern: {pat.pattern}")
                _STATUS_CACHE[clean_url] = res
                return res

    # If undetermined or successfully loaded without closure patterns, assume active
    res = (True, "Live")
    _STATUS_CACHE[clean_url] = res
    return res


def filter_active_jobs(jobs: List[Dict[str, Any]], max_workers: int = 10) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """
    Scans a batch of jobs concurrently and returns (active_jobs, closed_jobs).
    """
    active = []
    closed = []

    def check(job):
        is_live, reason = is_job_active(job.get("url", ""))
        return job, is_live, reason

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(check, jobs)
        for job, is_live, reason in results:
            if is_live:
                active.append(job)
            else:
                closed.append((job, reason))

    return active, closed
