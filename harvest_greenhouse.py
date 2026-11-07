import urllib.request
import json
import re
import csv
from agents import smarts

BOARDS = [
    'huntress', 'tines', 'axonius', 'torq', 'tenableinc', 'nozominetworks',
    'appian', 'roblox', 'qualtrics', 'five9', 'zoominfo', 'zuora',
    'purestorage', 'backblaze', 'newrelic', 'starburst', 'betterment',
    'yugabyte', 'fastly', 'logicmonitor', 'knowbe4', 'commvault',
    'twilio', 'zscaler', 'netskope', 'tanium', 'axon', 'sonicwall',
    'dragos', 'bitgo', 'cribl', 'tailscale', 'beyondtrust', 'pingidentity',
    'chainguard', 'defenseunicorns', 'epirus', 'vannevarlabs', 'fivetran',
    'gusto', 'crowdstrike', 'cloudflare', 'cyberark', 'sailpoint',
    'qualys', 'wiz', 'arcticwolf', 'snyk', 'vanta', 'kaseya', 'jamf',
    'aviatrix', 'virtru', 'klaviyo', 'smartsheet', 'anaplan', 'mongodb',
    'databricks', 'hashicorp', 'elastic', 'confluent', 'couchbase',
    'okta', 'paloaltonetworks', 'sentinelone', 'fortinet', 'proofpoint',
    'abnormalsecurity', 'recordedfuture', 'catonetworks', 'rubrik',
    'bishopfox', 'verkada', 'samsara', 'stripe', 'pagerduty',
    'gitlab', 'canonical', 'cockroachlabs'
]

with open('applications.csv', 'r', encoding='utf-8', errors='ignore') as f:
    app_text = f.read()
    app_jids = set(re.findall(r'(?:gh_jid=|/jobs/)(\d+)', app_text))

with open('applications.csv', 'r', encoding='utf-8', errors='ignore') as f:
    app_rows = list(csv.DictReader(f))

app_urls = set()
app_company_roles = set()

for r in app_rows:
    u = r.get('Job URL', '').strip().split('?')[0].rstrip('/')
    if u:
        app_urls.add(u)
    comp = r.get('Company', '').strip().lower()
    role = r.get('Job Title', '').strip().lower()
    role_norm = re.sub(r'\[.*?\]', '', role).strip()
    if comp and role_norm:
        app_company_roles.add((comp, role_norm))

include_pattern = re.compile(
    r'\b(cyber|security|infosec|soc|iam|identity|access management|it support|desktop support|help desk|systems admin|system administrator|sysadmin|systems engineer|cloud security|network engineer|network administrator|it specialist|it technician|datacenter|data center|information security|incident response|vulnerability|threat|compliance)\b',
    re.I
)

exclude_pattern = re.compile(
    r'\b(senior|sr\b|architect|lead|director|manager|head of|vp|principal|staff|chief|cto|leader|software engineer|software developer|full stack|backend|frontend|compiler|machine learning|deep learning|data scientist|data engineer|firmware|embedded|robotics|mechanical|thermal|cabin|homologation|hydraulic|optical|hardware|sales executive|account executive|recruiter|counsel)\b',
    re.I
)

non_us_pattern = re.compile(
    r'\b(kindom|kingdom|canada|ontario|toronto|vancouver|quebec|uk|united kingdom|london|england|germany|berlin|munich|frankfurt|france|paris|ireland|dublin|netherlands|amsterdam|australia|sydney|melbourne|india|bangalore|bengaluru|hyderabad|pune|gurugram|singapore|japan|tokyo|brazil|paulo|bucharest|romania|luxembourg|saudi|riyadh|arabia|malaysia|spain|madrid|barcelona|poland|warsaw|krakow|czech|prague|israel|tel aviv|costa rica|mexico|colombia|argentina|philippines|manila|emea|apac|latam|taiwan|taipei|sweden|norway|finland|denmark|portugal|italy|switzerland)\b',
    re.I
)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

found_jobs = []

for board in BOARDS:
    api_url = f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs'
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            jobs = data.get('jobs', [])
    except Exception:
        continue

    for j in jobs:
        title = j.get('title', '').strip()
        loc = (j.get('location', {}).get('name', '') or '').strip()
        jid = str(j.get('id', '')).strip()
        url = f'https://boards.greenhouse.io/{board}/jobs/{jid}'

        if not include_pattern.search(title):
            continue
        if exclude_pattern.search(title):
            continue

        # Check location
        combined_loc = (loc + ' ' + title).lower()
        if non_us_pattern.search(combined_loc):
            continue

        # Deduplication checks
        if url in app_urls or jid in app_jids:
            continue
        
        comp_norm = board.lower()
        title_norm = re.sub(r'\[.*?\]', '', title).strip().lower()
        if (comp_norm, title_norm) in app_company_roles:
            continue

        # Check smarts backoff
        attemptable, reason = smarts.should_attempt(url, title, board)
        if not attemptable:
            continue

        loc_tag = f'[{loc}]' if loc else '[US]'
        comp_clean = board.capitalize()
        brand_map = {
            'tenableinc': 'Tenable',
            'nozominetworks': 'NozomiNetworks',
            'defenseunicorns': 'DefenseUnicorns',
            'vannevarlabs': 'VannevarLabs',
            'newrelic': 'NewRelic',
            'purestorage': 'PureStorage',
            'zoominfo': 'ZoomInfo',
            'paloaltonetworks': 'PaloAltoNetworks',
            'sentinelone': 'SentinelOne',
            'proofpoint': 'Proofpoint',
            'abnormalsecurity': 'AbnormalSecurity',
            'recordedfuture': 'RecordedFuture',
            'catonetworks': 'CatoNetworks',
            'bishopfox': 'BishopFox'
        }
        comp_display = brand_map.get(board.lower(), comp_clean)
        line = f'{comp_display} {title} {loc_tag}   {url}'
        found_jobs.append(line)

print(f'Total pristine new non-senior US jobs discovered: {len(found_jobs)}')
for j in found_jobs[:25]:
    print('  *', j)

with open('discovered_greenhouse.txt', 'w', encoding='utf-8') as out:
    for line in found_jobs:
        out.write(line + '\n')
