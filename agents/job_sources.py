"""
Job sources for the autonomous coordinator:
  1. GitHub Internship Repositories (SimplifyJobs Summer 2027, PittCSC 2026, SpeedyApply 2026).
  2. Direct ATS Board Endpoints (Greenhouse, Lever, Ashby) for 60+ tier-1 tech & enterprise companies.
Keeps FULL titles, drops closed / grad-only / non-US / stale postings, dedupes against queue.txt
and everything already applied to, and appends new roles directly into queue.txt.
"""
import html, json, pathlib, re, sys, urllib.request

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
if str(AUTOFILL) not in sys.path:
    sys.path.insert(0, str(AUTOFILL))
QUEUE = AUTOFILL / "queue.txt"

GITHUB_SOURCES = [
    ("SimplifyJobs 2027", "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"),
    ("PittCSC 2026", "https://raw.githubusercontent.com/pittcsc/Summer2026-Internships/dev/README.md"),
    ("SpeedyApply 2026", "https://raw.githubusercontent.com/SpeedyApply/2026-SWE-College-Jobs/main/README.md"),
]

DIRECT_ATS_COMPANIES = [
    # (Company Name, ATS Type, Board Slug)
    ("Figma", "greenhouse", "figma"),
    ("Stripe", "greenhouse", "stripe"),
    ("Databricks", "greenhouse", "databricks"),
    ("Scale AI", "greenhouse", "scaleai"),
    ("Ramp", "ashby", "ramp"),
    ("Palantir", "lever", "palantir"),
    ("Coinbase", "greenhouse", "coinbase"),
    ("Robinhood", "greenhouse", "robinhood"),
    ("DoorDash", "greenhouse", "doordash"),
    ("Uber", "greenhouse", "uber"),
    ("Dropbox", "greenhouse", "dropbox"),
    ("Instacart", "greenhouse", "instacart"),
    ("Snowflake", "greenhouse", "snowflake"),
    ("ServiceNow", "greenhouse", "servicenow"),
    ("Cloudflare", "greenhouse", "cloudflare"),
    ("Brex", "greenhouse", "brex"),
    ("Verkada", "greenhouse", "verkada"),
    ("Affirm", "greenhouse", "affirm"),
    ("Plaid", "greenhouse", "plaid"),
    ("Samsara", "greenhouse", "samsara"),
    ("Reddit", "greenhouse", "reddit"),
    ("Pinterest", "greenhouse", "pinterest"),
    ("Snap", "greenhouse", "snap"),
    ("Twitch", "greenhouse", "twitch"),
    ("Discord", "greenhouse", "discord"),
    ("Notion", "lever", "notion"),
    ("Retool", "greenhouse", "retool"),
    ("Weights & Biases", "greenhouse", "wandb"),
    ("Anthropic", "lever", "anthropic"),
    ("OpenAI", "greenhouse", "openai"),
    ("Perplexity", "ashby", "perplexity"),
    ("Harvey", "ashby", "harvey"),
    ("Writer", "ashby", "writer"),
    ("Sierra", "ashby", "sierra"),
    ("Duolingo", "greenhouse", "duolingo"),
    ("Lyft", "greenhouse", "lyft"),
    ("Block", "greenhouse", "block"),
    ("Box", "greenhouse", "box"),
    ("MongoDB", "greenhouse", "mongodb"),
    ("Elastic", "greenhouse", "elastic"),
    ("Datadog", "greenhouse", "datadog"),
    ("Asana", "greenhouse", "asana"),
    ("HubSpot", "greenhouse", "hubspot"),
    ("Waymo", "greenhouse", "waymo"),
    ("Cruise", "greenhouse", "cruise"),
    ("Nuro", "greenhouse", "nuro"),
    ("Aurora", "greenhouse", "aurora"),
    ("Toast", "greenhouse", "toast"),
    ("Chime", "greenhouse", "chime"),
    ("SoFi", "greenhouse", "sofi"),
    ("Glean", "ashby", "glean"),
]

NON_US = re.compile(
    r"\b(canada|uk|united kingdom|london|ontario|toronto|vancouver|bc|india|germany|france|ireland|"
    r"netherlands|poland|singapore|japan|china|australia|mexico|brazil|israel|switzerland|spain)\b",
    re.I
)

INTERN_KEYWORDS = re.compile(r"\b(intern|internship|co-op|coop|fellow|fellowship|early talent|student|university)\b", re.I)
GRAD_ONLY = re.compile(r"\b(phd|master'?s|mba|graduate student|postdoc)\b", re.I)


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("↳", "").strip()


def fetch_github_sources(max_age_days=30):
    jobs = []
    seen = set()
    for src_name, src_url in GITHUB_SOURCES:
        try:
            req = urllib.request.Request(src_url, headers={"User-Agent": "Mozilla/5.0"})
            text = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", errors="ignore")
            last_company = ""
            for row in re.findall(r"<tr>(.*?)</tr>", text, re.S):
                cols = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                if len(cols) < 5:
                    continue
                raw_company = _clean(cols[0])
                company = raw_company if raw_company else last_company
                if raw_company:
                    last_company = raw_company
                if "\U0001f512" in row or "\U0001f393" in row:  # closed or grad-only
                    continue
                role, loc = _clean(cols[1]), _clean(cols[2])
                if NON_US.search(loc) and "remote" not in loc.lower():
                    continue
                links = [h for h in re.findall(r'href="([^"]+)"', cols[3]) if "simplify.jobs" not in h]
                if not links:
                    continue
                url = links[0]
                base_u = url.split("?")[0].rstrip("/")
                if base_u in seen:
                    continue
                seen.add(base_u)
                m = re.match(r"(\d+)\s*d", _clean(cols[4]))
                age = int(m.group(1)) if m else 0
                if _clean(cols[4]).endswith("mo") or age > max_age_days:
                    continue
                jobs.append({"company": company, "role": role, "location": loc, "url": url, "age_days": age, "source": src_name})
        except Exception:
            pass
    return jobs


def fetch_direct_ats():
    jobs = []
    seen = set()
    for comp_name, ats_type, slug in DIRECT_ATS_COMPANIES:
        try:
            if ats_type == "greenhouse":
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
                req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    if not INTERN_KEYWORDS.search(title) or GRAD_ONLY.search(title):
                        continue
                    loc = j.get("location", {}).get("name", "USA")
                    if NON_US.search(loc) and "remote" not in loc.lower():
                        continue
                    u = j.get("absolute_url", "")
                    if not u or u.split("?")[0] in seen:
                        continue
                    seen.add(u.split("?")[0])
                    jobs.append({"company": comp_name, "role": title, "location": loc, "url": u, "age_days": 1, "source": "Greenhouse Direct"})

            elif ats_type == "lever":
                api_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
                req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
                for j in data:
                    title = j.get("text", "")
                    if not INTERN_KEYWORDS.search(title) or GRAD_ONLY.search(title):
                        continue
                    loc = j.get("categories", {}).get("location", "USA")
                    if NON_US.search(loc) and "remote" not in loc.lower():
                        continue
                    u = j.get("hostedUrl", "")
                    if not u or u.split("?")[0] in seen:
                        continue
                    seen.add(u.split("?")[0])
                    jobs.append({"company": comp_name, "role": title, "location": loc, "url": u, "age_days": 1, "source": "Lever Direct"})

            elif ats_type == "ashby":
                api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
                req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    if not INTERN_KEYWORDS.search(title) or GRAD_ONLY.search(title):
                        continue
                    loc = j.get("location", "USA")
                    if NON_US.search(loc) and "remote" not in loc.lower():
                        continue
                    u = j.get("jobUrl", "")
                    if not u or u.split("?")[0] in seen:
                        continue
                    seen.add(u.split("?")[0])
                    jobs.append({"company": comp_name, "role": title, "location": loc, "url": u, "age_days": 1, "source": "Ashby Direct"})
        except Exception:
            pass
    return jobs


def fetch(max_age_days=30):
    """Aggregate jobs across GitHub repositories and direct ATS board endpoints."""
    gh_jobs = fetch_github_sources(max_age_days)
    ats_jobs = fetch_direct_ats()
    combined = []
    seen = set()
    for j in ats_jobs + gh_jobs:  # prioritize direct ATS endpoints first
        base_u = j["url"].split("?")[0].rstrip("/")
        if base_u not in seen:
            seen.add(base_u)
            combined.append(j)
    return combined


def add_new(max_age_days=30, limit=1000):
    """Append new postings to queue.txt. Returns how many were added."""
    import results_engine as RE
    known = RE.already_applied_keys()
    qtext = QUEUE.read_text(encoding="utf-8") if QUEUE.exists() else ""
    for j in RE.parse_queue_file(QUEUE) if QUEUE.exists() else []:
        known.add(RE.job_key(j["company"], j["role"], j["url"]))
    new = []
    try:
        from . import smarts
    except ImportError:
        from agents import smarts
    for j in fetch(max_age_days):
        smarts.record_posted(j["url"], j["age_days"])
        k = RE.job_key(j["company"], j["role"], j["url"])
        base_u = j["url"].split("?")[0]
        if k in known or base_u in qtext:
            continue
        known.add(k)
        token = re.sub(r"[^A-Za-z0-9]", "", j["company"].title()) or "Company"
        new.append(f"{token} {j['role']} [{j['location']}; {j['age_days']}d old]   {j['url']}")
        if len(new) >= limit:
            break
    if new:
        with open(QUEUE, "a", encoding="utf-8") as f:
            f.write(f"\n# ---- added by agents/job_sources.py (multi-source, <= {max_age_days} days old)\n" + "\n".join(new) + "\n")
    return len(new)


# Alias expected by run_until_target.py coordinator
add_new_jobs_to_queue = add_new


if __name__ == "__main__":
    print("[Job Sources] Running multi-source ingestion...")
    added = add_new(max_age_days=30, limit=1000)
    print(f"[Job Sources] Successfully ingested {added} new active postings into queue.txt!")
