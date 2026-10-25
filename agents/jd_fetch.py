"""
Fetch the full job description for a posting URL (plain HTTP, public data only).
Uses each ATS's public JSON endpoint where one exists, else the page's visible text. Cached.
"""
import hashlib, html, json, re, urllib.parse, urllib.request
from . import llm

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json,text/html"}
MAX_CHARS = 30000


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _text(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _workday(url):
    u = urllib.parse.urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if "job" not in parts:
        return None
    site = parts[0]
    tail = "/".join(parts[parts.index("job"):])
    tail = re.sub(r"/apply.*$", "", tail)
    tenant = u.netloc.split(".")[0]
    d = json.loads(_get(f"https://{u.netloc}/wday/cxs/{tenant}/{site}/{tail}"))
    info = d.get("jobPostingInfo", {})
    return f"{info.get('title', '')}\nLocation: {info.get('location', '')}\nTime type: {info.get('timeType', '')}\n\n{_text(info.get('jobDescription', ''))}"


def _greenhouse(url):
    m = re.search(r"(job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if not m:
        return None
    api = "boards-api.eu.greenhouse.io" if ".eu." in m.group(1) or m.group(1).endswith(".eu") else "boards-api.greenhouse.io"
    d = json.loads(_get(f"https://{api}/v1/boards/{m.group(2)}/jobs/{m.group(3)}"))
    return f"{d.get('title', '')}\nLocation: {(d.get('location') or {}).get('name', '')}\n\n{_text(html.unescape(d.get('content', '')))}"


def _lever(url):
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    d = json.loads(_get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}"))
    lists = "\n".join(f"{l.get('text', '')}\n{_text(l.get('content', ''))}" for l in d.get("lists", []))
    return f"{d.get('text', '')}\nLocation: {(d.get('categories') or {}).get('location', '')}\n\n{d.get('descriptionPlain', '')}\n{lists}\n{d.get('additionalPlain', '')}"


def _ashby(url):
    m = re.search(r"jobs\.ashbyhq\.com/([^/?]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    d = json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}"))
    job = next((j for j in d.get("jobs", []) if j.get("id") == m.group(2)), None)
    if not job:
        return None
    return f"{job.get('title', '')}\nLocation: {job.get('location', '')}\n\n{job.get('descriptionPlain') or _text(job.get('descriptionHtml', ''))}"


def fetch(url):
    """Returns (text, source). text is '' when nothing usable could be read."""
    key = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16]
    hit = llm.cache_get("jd", key)
    if hit is not None:
        return hit["text"], hit["source"]
    text, source = "", "none"
    for name, fn in (("workday", _workday), ("greenhouse", _greenhouse), ("lever", _lever), ("ashby", _ashby)):
        if name == "workday" and "myworkdayjobs.com" not in url:
            continue
        try:
            t = fn(url)
            if t and len(t) > 200:
                text, source = t, name
                break
        except Exception:
            continue
    if not text:
        try:
            t = _text(_get(url))
            if len(t) > 400:
                text, source = t, "page"
        except Exception:
            pass
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[...job description continues; first 30,000 characters shown]"
    llm.cache_put("jd", key, {"text": text, "source": source, "url": url})
    return text, source
