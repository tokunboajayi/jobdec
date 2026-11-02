"""
Sync Job Deck Applications to Obsidian Job Tracker Vault
Generates structured Markdown notes with YAML frontmatter for every applied job
so that Obsidian's Dataview dashboards, Sankey charts, and Kanban boards work automatically.
"""

import os
import re
import csv
from pathlib import Path
from datetime import datetime

JOB_DECK_ROOT = Path(__file__).resolve().parent
VAULT_DIR = JOB_DECK_ROOT.parent / "Obsidian Job Tracker"
APPS_DIR = VAULT_DIR / "Applications"


def sanitize_filename(name: str) -> str:
    """Remove illegal characters for file names."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def export_applications_to_obsidian():
    """Reads applications.csv and generates/updates markdown notes in the Obsidian vault."""
    csv_path = JOB_DECK_ROOT / "applications.csv"
    if not csv_path.exists():
        csv_path = JOB_DECK_ROOT.parent / "applications.csv"
    if not csv_path.exists():
        print("[Obsidian Sync] No applications.csv found.")
        return 0

    APPS_DIR.mkdir(parents=True, exist_ok=True)

    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = list(csv.DictReader(f))

    count = 0
    for row in reader:
        company = (row.get("Company") or "Unknown").strip()
        role = (row.get("Role") or "Role").strip()
        date_applied = (row.get("Date Applied") or row.get("Date") or str(datetime.now().date())).strip()
        job_url = (row.get("Job URL") or row.get("URL") or "").strip()
        stage = (row.get("Stage") or "Applied").strip()

        # Extract location if embedded in brackets e.g. "Role [New York, NY]"
        location = "United States"
        m = re.search(r"\[(.*?)\]", role)
        if m:
            location_raw = m.group(1).split(";")[0].strip()
            if location_raw:
                location = location_raw
            clean_role = re.sub(r"\[.*?\]", "", role).strip()
        else:
            clean_role = role

        # Clean filename
        clean_company = sanitize_filename(company)
        clean_role_file = sanitize_filename(clean_role)[:50]
        safe_date = sanitize_filename(date_applied)
        filename = f"{clean_company} - {clean_role_file} - {safe_date}.md"
        filepath = APPS_DIR / filename

        # If file already exists, keep user edits / log
        if filepath.exists():
            continue

        # Tag determination
        tags = ["job-application"]
        role_lower = clean_role.lower()
        if "security" in role_lower or "cyber" in role_lower:
            tags.append("cybersecurity")
        if "iam" in role_lower or "identity" in role_lower:
            tags.append("iam")
        if "cloud" in role_lower:
            tags.append("cloud")
        if "support" in role_lower:
            tags.append("it-support")
        if "intern" in role_lower:
            tags.append("internship")

        tag_yaml = "\n".join(f"  - {t}" for t in tags)

        content = f"""---
company: "{company}"
_position: "{clean_role}"
location: "{location}"
source: "Job Deck Automation"
date_applied: {date_applied}
last_update: {date_applied}
job_url: "{job_url}"
salary_expectation: ""
notes: "Applied automatically via Job Deck"
history:
  - {stage}
tags:
{tag_yaml}
---

## Description
**Company:** {company}  
**Position:** {clean_role}  
**Location:** {location}  
**Job URL:** [View Posting]({job_url})  

### Status
- **Current Stage:** {stage}
- **Date Applied:** {date_applied}

---
## Log
- **{date_applied}** — Applied via Job Deck autonomous submission engine.
"""
        filepath.write_text(content, encoding="utf-8")
        count += 1

    print(f"[Obsidian Sync] Synced {count} new application notes to Obsidian Job Tracker.")
    return count


if __name__ == "__main__":
    export_applications_to_obsidian()

