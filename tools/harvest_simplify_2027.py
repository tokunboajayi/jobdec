"""
SimplifyJobs Summer 2027 Harvester.
Extracts active Summer 2027 internship roles from SimplifyJobs Summer2027-Internships,
filters for PM, AI, Data, and Tech Analyst tracks, filters for US locations,
checks for duplicates against applications.csv and queue.txt,
and populates queue.txt with verified targets using master_resume.pdf.
"""
import csv
import pathlib
import re
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent  # autofill/ (this script lives in tools/)
ROOT = HERE.parent
QUEUE_FILE = HERE / "queue.txt"
APPS_FILE = ROOT / "applications.csv"
SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"


def get_existing_tracker_companies():
    companies = set()
    urls = set()
    if APPS_FILE.exists():
        try:
            reader = csv.DictReader(APPS_FILE.read_text(encoding="utf-8").splitlines())
            for row in reader:
                co = row.get("Company", "").strip().lower()
                u = row.get("Job URL", "").strip().lower()
                if co: companies.add(co)
                if u: urls.add(u)
        except Exception:
            pass

    if QUEUE_FILE.exists():
        try:
            for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"): continue
                m = re.search(r'(https?://[^\s]+)', line)
                if m:
                    urls.add(m.group(1).lower())
                parts = line.split()
                if parts:
                    companies.add(parts[0].lower())
        except Exception:
            pass

    return companies, urls


def fetch_readme_text():
    # Check cached file first
    cached = pathlib.Path(r"C:\Users\RecoveryAdmin\.gemini\antigravity-ide\brain\b3bc6e25-ce83-42b9-b9db-bc0b39cc8510\.system_generated\steps\1502\content.md")
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    req = urllib.request.Request(SIMPLIFY_README_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def parse_roles(text):
    existing_companies, existing_urls = get_existing_tracker_companies()
    
    # Matches table rows
    rows = re.findall(r'<tr>(.*?)</tr>', text, re.DOTALL)
    print(f"Total HTML rows found: {len(rows)}")
    
    candidates = []
    
    # Non-US indicators to exclude
    non_us = re.compile(r'\b(uk|london|canada|vancouver|toronto|india|germany|france|australia|coventry|berlin|poland|singapore|netherlands|ireland|dublin|japan)\b', re.I)
    
    # Target role regex
    target_role_re = re.compile(
        r'product\s*manage|product\s*intern|product\s*analyst|ai\b|artificial\s*intelligence|'
        r'machine\s*learning|data\s*analyst|data\s*science|business\s*technology|tech\s*analyst|'
        r'business\s*analyst|technology\s*intern|software\s*engineer|systems\s*analyst|quantitative',
        re.I
    )

    for r in rows:
        # Skip headers
        if '<th>' in r: continue
        
        # Closed check
        if '🔒' in r: continue
        # Advanced degree check (Masters/PhD required)
        if '🎓' in r: continue
        
        cols = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
        if len(cols) < 4: continue
        
        comp_col, role_col, loc_col, app_col = cols[0], cols[1], cols[2], cols[3]
        
        comp_name = re.sub(r'<[^>]+>', '', comp_col).strip()
        comp_name = re.sub(r'^[🔥\s]+', '', comp_name).strip()
        
        role_title = re.sub(r'<[^>]+>', '', role_col).strip()
        location = re.sub(r'<[^>]+>', ' ', loc_col).strip()
        
        # Check non-US
        if non_us.search(location): continue
        
        # Check target role
        if not target_role_re.search(role_title): continue
        
        # Extract direct application URL
        url_match = re.search(r'href="([^"]+)"', app_col)
        if not url_match: continue
        app_url = url_match.group(1).strip()
        
        # Clean tracking params if needed, but preserve essential params
        # Avoid duplicate
        clean_url = app_url.split("?utm_source=")[0].split("&utm_source=")[0].lower()
        if clean_url in existing_urls or app_url.lower() in existing_urls:
            continue
            
        clean_comp = comp_name.lower().replace(" ", "").replace("-", "")
        if any(clean_comp == c.replace(" ", "").replace("-", "") for c in existing_companies):
            continue
            
        # Score fit (1-10)
        fit_score = 7
        if re.search(r'product|apm', role_title, re.I):
            fit_score = 9
        elif re.search(r'ai|artificial|machine learning|data analyst', role_title, re.I):
            fit_score = 9
        elif re.search(r'business.*analyst|tech.*analyst|quantitative', role_title, re.I):
            fit_score = 8
            
        candidates.append({
            "company": comp_name,
            "role": role_title,
            "location": location,
            "url": app_url,
            "fit_score": fit_score
        })
        
    # Sort by fit_score descending
    candidates.sort(key=lambda x: x["fit_score"], reverse=True)
    return candidates


def append_to_queue(roles, count=25):
    if not QUEUE_FILE.exists(): return 0
    lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    added = 0
    new_lines = [f"\n# --- Added from SimplifyJobs Summer 2027 List ({count} roles) ---"]
    for r in roles[:count]:
        co_slug = re.sub(r'[^A-Za-z0-9]', '', r['company'])
        role_slug = re.sub(r'[^A-Za-z0-9 ]', '', r['role'])[:25].strip()
        line = f"{co_slug} {role_slug}   {r['url']}   resumes/master_resume.pdf"
        new_lines.append(line)
        added += 1
    
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(new_lines) + "\n")
    print(f"\n[Simplify Harvester] Appended {added} new Summer 2027 roles to {QUEUE_FILE.name}!")
    return added


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", type=int, default=0, help="Number of top roles to append to queue.txt")
    parser.add_argument("--min-score", type=int, default=8, help="Minimum fit score (default: 8)")
    args = parser.parse_args()

    print("[Simplify Harvester] Fetching SimplifyJobs Summer 2027 list...")
    text = fetch_readme_text()
    roles = parse_roles(text)
    
    # Filter by min-score
    filtered = [r for r in roles if r["fit_score"] >= args.min_score]
    print(f"[Simplify Harvester] Found {len(filtered)} Summer 2027 roles with Fit Score >= {args.min_score}.")

    print("\nTop 15 Available Roles:")
    for i, r in enumerate(filtered[:15], 1):
        clean_comp = r['company'].encode('ascii', 'ignore').decode('ascii')
        clean_role = r['role'].encode('ascii', 'ignore').decode('ascii')
        clean_loc = r['location'].encode('ascii', 'ignore').decode('ascii').strip()
        print(f"  {i}. [{r['fit_score']}/10] {clean_comp} - {clean_role} ({clean_loc[:30]})")
        print(f"     URL: {r['url']}")

    if args.add > 0:
        append_to_queue(filtered, args.add)

    return filtered


if __name__ == "__main__":
    main()
