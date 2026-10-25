import csv
import pathlib
import re
import urllib.request
from urllib.parse import urlparse
from collections import Counter

ROOT = pathlib.Path(r"c:\Users\RecoveryAdmin\OneDrive\Documents\LinkedIn Outreach\Job Applications")
AUTOFILL = ROOT / "autofill"
APPS_FILE = ROOT / "applications.csv"
QUEUE_FILE = AUTOFILL / "queue.txt"
PHASE2_QUEUE = AUTOFILL / "queue_phase2.txt"

# 1. Gather all existing applied and attempted URLs & companies
applied_urls = set()
applied_companies = set()

if APPS_FILE.exists():
    try:
        reader = csv.DictReader(APPS_FILE.read_text(encoding="utf-8").splitlines())
        for row in reader:
            co = row.get("Company", "").strip().lower()
            u = row.get("Job URL", "").strip().lower()
            if u: applied_urls.add(u)
            if co: applied_companies.add(co)
    except Exception as e:
        print(f"Error reading APPS_FILE: {e}")

attempted_urls = set()
attempted_companies = set()
if QUEUE_FILE.exists():
    for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        m = re.search(r'(https?://[^\s]+)', line)
        if m:
            clean_u = m.group(1).split("?utm_source=")[0].split("&utm_source=")[0].lower()
            attempted_urls.add(clean_u)
            attempted_urls.add(m.group(1).lower())
        parts = line.split()
        if parts:
            attempted_companies.add(parts[0].lower())

# 2. Fetch live SimplifyJobs Summer 2027 list
url = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as resp:
    readme_text = resp.read().decode("utf-8")

rows = re.findall(r'<tr>(.*?)</tr>', readme_text, re.DOTALL)

non_us = re.compile(r'\b(uk|london|canada|vancouver|toronto|india|germany|france|australia|coventry|berlin|poland|singapore|netherlands|ireland|dublin|japan|mexico|brazil|israel|switzerland|sweden|italy|spain)\b', re.I)
target_role = re.compile(r'product|apm|ai\b|artificial|machine learning|data|analyst|business|tech|software|engineer|developer|systems|quantitative|cloud|security|it\b|cyber|database|architect', re.I)

valid_roles = []
last_company = ""

for r in rows:
    if '<th>' in r or '🔒' in r or '🎓' in r: continue
    cols = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
    if len(cols) < 4: continue
    
    raw_comp = re.sub(r'<[^>]+>', '', cols[0]).strip()
    raw_comp = re.sub(r'^[🔥\s↳]+', '', raw_comp).strip()
    if raw_comp and raw_comp != '↳':
        last_company = raw_comp
    comp_name = last_company
    if not comp_name:
        continue
    role_title = re.sub(r'<[^>]+>', '', cols[1]).strip()
    location = re.sub(r'<[^>]+>', ' ', cols[2]).strip()
    
    if non_us.search(location): continue
    if not target_role.search(role_title): continue
    
    u_match = re.search(r'href="([^"]+)"', cols[3])
    if not u_match: continue
    app_url = u_match.group(1).strip()
    clean_u = app_url.split("?utm_source=")[0].split("&utm_source=")[0].lower()
    
    if clean_u in attempted_urls or app_url.lower() in attempted_urls or clean_u in applied_urls:
        continue
    
    comp_slug = re.sub(r'[^A-Za-z0-9]', '', comp_name).lower()
    if any(comp_slug == c.replace(" ", "").replace("-", "") for c in applied_companies):
        continue
    if any(comp_slug == c.replace(" ", "").replace("-", "") for c in attempted_companies):
        continue
        
    domain = urlparse(app_url).netloc.lower()
    if 'greenhouse' in domain: ats = 'Greenhouse'
    elif 'ashby' in domain: ats = 'Ashby'
    elif 'lever' in domain: ats = 'Lever'
    elif 'smartrecruiters' in domain: ats = 'SmartRecruiters'
    elif 'myworkdayjobs' in domain: ats = 'Workday'
    else: continue  # Focus specifically on Greenhouse, Ashby, Lever, SmartRecruiters, Workday
    
    # Priority rank: Greenhouse (10), Ashby (9), Lever (9), SmartRecruiters (8), Workday (7)
    ats_priority = {
        'Greenhouse': 10,
        'Ashby': 9,
        'Lever': 9,
        'SmartRecruiters': 8,
        'Workday': 7
    }.get(ats, 5)
    
    # Bonus for PM / AI roles
    role_bonus = 0
    if re.search(r'product|apm|ai\b|machine learning', role_title, re.I):
        role_bonus = 2
    elif re.search(r'data|analyst', role_title, re.I):
        role_bonus = 1
        
    valid_roles.append({
        "company": comp_name,
        "role": role_title,
        "location": location,
        "url": app_url,
        "ats": ats,
        "score": ats_priority + role_bonus
    })

valid_roles.sort(key=lambda x: (x["score"], x["company"]), reverse=True)

print(f"Total High-Priority ATS Roles Identified: {len(valid_roles)}")
counts = Counter(r['ats'] for r in valid_roles)
for ats, cnt in counts.most_common():
    print(f"  {ats}: {cnt}")

# Write Phase 2 Queue
lines = [
    "# ==================================================================",
    f"# PHASE 2 QUEUE: {len(valid_roles)} HIGH-PRIORITY ATS ROLES",
    "# Prioritizing Greenhouse, Ashby, Lever, SmartRecruiters, Workday",
    "# ==================================================================\n"
]

for r in valid_roles:
    co_slug = re.sub(r'[^A-Za-z0-9]', '', r['company'])
    if not co_slug: co_slug = "Company"
    role_slug = re.sub(r'[^A-Za-z0-9 ]', '', r['role'])[:28].strip()
    line = f"{co_slug} {role_slug}   {r['url']}   resumes/master_resume.pdf"
    lines.append(line)

PHASE2_QUEUE.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nSuccessfully wrote {len(valid_roles)} roles to {PHASE2_QUEUE}")
