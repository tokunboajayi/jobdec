"""
Self-Learning Engine for Resume & Cover Letter Tailoring.
Tracks job applications, learns keyword/bullet performance across domains (IAM, SOC Analyst, IT Support, Cloud/SysAdmin),
and dynamically updates weighting based on real application outcomes (interviews, assessments, submissions).
"""
import copy
import json
import os
import re
from pathlib import Path
from datetime import datetime

LEARNING_FILE = Path(__file__).resolve().parent / "tailor_learning.json"

DEFAULT_DOMAIN_WEIGHTS = {
    "iam": {
        "active directory": 3.0,
        "entra id": 3.0,
        "azure ad": 3.0,
        "gpo": 2.5,
        "group policy": 2.5,
        "powershell": 2.8,
        "identity": 2.5,
        "access management": 2.5,
        "provisioning": 2.5,
        "deprovisioning": 2.5,
        "lifecycle": 2.2,
        "least privilege": 2.2,
        "rbac": 2.2,
        "sso": 2.0,
        "pam": 2.0,
        "okta": 2.0,
        "security+": 2.0,
    },
    "soc_analyst": {
        "sentinel": 3.0,
        "azure sentinel": 3.0,
        "siem": 3.0,
        "incident response": 2.8,
        "threat detection": 2.8,
        "wireshark": 2.8,
        "packet analysis": 2.8,
        "alert tuning": 2.5,
        "mitre att&ck": 2.5,
        "nist csf": 2.5,
        "phishing": 2.2,
        "threat modeling": 2.2,
        "security+": 2.5,
        "soc": 2.5,
        "investigation": 2.0,
        "triage": 2.0,
    },
    "it_support": {
        "technical support": 3.0,
        "troubleshooting": 3.0,
        "hardware": 2.5,
        "pos": 2.5,
        "software configuration": 2.5,
        "client support": 2.5,
        "active directory": 2.5,
        "account access": 2.5,
        "ticketing": 2.2,
        "sop": 2.0,
        "endpoint": 2.2,
        "windows": 2.2,
        "linux": 2.0,
        "diagnostic": 2.2,
        "documentation": 2.0,
    },
    "cloud_sec_sysadmin": {
        "linux": 2.8,
        "windows server": 2.5,
        "azure": 2.8,
        "vmware": 2.5,
        "powershell": 2.5,
        "bash": 2.5,
        "python": 2.5,
        "infrastructure": 2.2,
        "automation": 2.5,
        "endpoint": 2.0,
        "cloud security": 2.5,
        "systems administration": 2.5,
    },
    "network_sec": {
        "network defense": 3.0,
        "wireshark": 3.0,
        "packet analysis": 3.0,
        "firewall": 2.5,
        "tcp/ip": 2.5,
        "dns": 2.0,
        "vpn": 2.2,
        "ethical hacking": 2.5,
        "security+": 2.5,
    },
    "general_cyber": {
        "cybersecurity": 2.5,
        "security+": 2.5,
        "risk": 2.2,
        "compliance": 2.2,
        "nist": 2.5,
        "mitre": 2.5,
        "vulnerability": 2.5,
        "access control": 2.2,
        "remediation": 2.2,
    }
}

DEFAULT_SKILL_ORDERS = {
    "iam": ["Identity & Access", "Technical", "Security", "Operations"],
    "soc_analyst": ["Security", "Identity & Access", "Technical", "Operations"],
    "it_support": ["Technical", "Operations", "Identity & Access", "Security"],
    "cloud_sec_sysadmin": ["Technical", "Identity & Access", "Security", "Operations"],
    "network_sec": ["Security", "Technical", "Identity & Access", "Operations"],
    "general_cyber": ["Security", "Identity & Access", "Technical", "Operations"]
}


class TailorLearningEngine:
    def __init__(self, filepath=LEARNING_FILE):
        self.filepath = Path(filepath)
        self.state = self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Default fresh state
        return {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "learned_keyword_weights": copy.deepcopy(DEFAULT_DOMAIN_WEIGHTS),
            "preferred_skill_orders": copy.deepcopy(DEFAULT_SKILL_ORDERS),
            "bullet_performance": {}, # key: f"{org}_{bullet_idx}" -> {"score": float, "samples": int}
            "applications": {},        # key: job_slug -> {company, role, domain, keywords, bullets, skills, outcome, ts}
            "domain_stats": {k: {"applied": 0, "interviews": 0, "assessments": 0, "confirmations": 0} for k in DEFAULT_DOMAIN_WEIGHTS}
        }

    def save(self):
        self.state["last_updated"] = datetime.now().isoformat()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def get_domain_weights(self, domain):
        return self.state.get("learned_keyword_weights", {}).get(domain, DEFAULT_DOMAIN_WEIGHTS.get(domain, {}))

    def get_preferred_skill_order(self, domain):
        return self.state.get("preferred_skill_orders", {}).get(domain, DEFAULT_SKILL_ORDERS.get(domain, DEFAULT_SKILL_ORDERS["general_cyber"]))

    def get_bullet_boost(self, org, bullet_idx):
        key = f"{org}_{bullet_idx}"
        b_data = self.state.get("bullet_performance", {}).get(key)
        if b_data and b_data.get("samples", 0) > 0:
            return b_data.get("score", 0.0) / b_data["samples"]
        return 0.0

    def record_application(self, company, role, domain, keywords, bullet_indices, skill_order):
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70] or "job"
        
        # Track application count
        if domain in self.state["domain_stats"]:
            self.state["domain_stats"][domain]["applied"] = self.state["domain_stats"][domain].get("applied", 0) + 1

        self.state["applications"][slug] = {
            "company": company,
            "role": role,
            "domain": domain,
            "keywords": keywords,
            "bullet_indices": bullet_indices,
            "skill_order": skill_order,
            "outcome": "applied",
            "timestamp": datetime.now().isoformat()
        }

        # Reinforce keywords slightly on active application
        weights = self.state["learned_keyword_weights"].setdefault(domain, {})
        for kw in keywords:
            kw_low = kw.lower()
            weights[kw_low] = round(weights.get(kw_low, 1.5) + 0.05, 3)

        self.save()

    def record_outcome(self, company, role, outcome_kind):
        """
        Outcome rewards:
        - interview: +4.0 to keywords, +2.5 to bullets used
        - assessment: +2.5 to keywords, +1.5 to bullets used
        - confirmation: +0.4 to keywords, +0.2 to bullets used
        - rejection: -0.1 (mild damping to avoid negative drift)
        """
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")[:70]
        app = self.state["applications"].get(slug)
        if not app:
            # Try partial matching on company/role
            for k, v in self.state["applications"].items():
                if company.lower() in v.get("company", "").lower() and (role.lower() in v.get("role", "").lower() or not role):
                    app = v
                    slug = k
                    break

        if not app:
            return False

        app["outcome"] = outcome_kind
        domain = app.get("domain", "general_cyber")
        stats = self.state["domain_stats"].setdefault(domain, {"applied": 0, "interviews": 0, "assessments": 0, "confirmations": 0})

        reward = 0.0
        if outcome_kind == "interview":
            reward = 4.0
            stats["interviews"] = stats.get("interviews", 0) + 1
        elif outcome_kind == "assessment":
            reward = 2.5
            stats["assessments"] = stats.get("assessments", 0) + 1
        elif outcome_kind == "confirmation":
            reward = 0.4
            stats["confirmations"] = stats.get("confirmations", 0) + 1
        elif outcome_kind == "rejection":
            reward = -0.1

        # Update keyword weights for domain
        weights = self.state["learned_keyword_weights"].setdefault(domain, {})
        for kw in app.get("keywords", []):
            kw_low = kw.lower()
            current = weights.get(kw_low, 1.5)
            weights[kw_low] = max(0.5, round(current + (reward * 0.2), 3))

        # Update bullet performance
        bullet_indices = app.get("bullet_indices", {})
        for org, indices in bullet_indices.items():
            if indices:
                top_bullet_idx = indices[0]
                b_key = f"{org}_{top_bullet_idx}"
                b_perf = self.state["bullet_performance"].setdefault(b_key, {"score": 0.0, "samples": 0})
                b_perf["score"] = round(b_perf["score"] + reward, 2)
                b_perf["samples"] += 1

        self.save()
        return True

    def sync_from_sources(self, applications_csv_path="applications.csv", reset=False):
        """Scans applications.csv to ensure all applied jobs and their tracker outcomes are registered."""
        csv_file = Path(applications_csv_path)
        if not csv_file.exists():
            return 0
        import csv
        if reset:
            self.state = {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "learned_keyword_weights": copy.deepcopy(DEFAULT_DOMAIN_WEIGHTS),
                "preferred_skill_orders": copy.deepcopy(DEFAULT_SKILL_ORDERS),
                "bullet_performance": {},
                "applications": {},
                "domain_stats": {k: {"applied": 0, "interviews": 0, "assessments": 0, "confirmations": 0} for k in DEFAULT_DOMAIN_WEIGHTS},
            }
        synced = 0
        skip_stages = {"Found", "Scored", "Tailored", "Skipped (low fit)", "Needs decision",
                       "Withdrawn", "Started (incomplete)", "Background check complete", "Submitted? (BAD DATA - verify)"}
        try:
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    comp = row.get("Company", "").strip()
                    role = row.get("Role", "").strip()
                    stage_raw = (row.get("Stage") or "").strip()
                    if not comp or not role or stage_raw in skip_stages:
                        continue
                    st = stage_raw.lower()
                    has_outcome = bool(re.search(r"reject|interview|offer|\boa\b|assessment", st))
                    if not row.get("Date Applied") and not has_outcome:
                        continue
                    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{comp}_{role}").strip("_")[:70]
                    if slug not in self.state["applications"]:
                        self.state["applications"][slug] = {
                            "company": comp,
                            "role": role,
                            "domain": "general_cyber",
                            "keywords": [],
                            "bullet_indices": {},
                            "skill_order": DEFAULT_SKILL_ORDERS["general_cyber"],
                            "outcome": "applied",
                            "timestamp": row.get("Date Applied", datetime.now().isoformat())
                        }
                        self.state["domain_stats"]["general_cyber"]["applied"] = self.state["domain_stats"]["general_cyber"].get("applied", 0) + 1
                        synced += 1
                    outcome = ("interview" if ("interview" in st or "offer" in st) else
                               "assessment" if re.search(r"\boa\b|assessment", st) else
                               "rejection" if "reject" in st else "applied")
                    if outcome != "applied" and self.state["applications"][slug].get("outcome") != outcome:
                        self.record_outcome(comp, role, outcome)
                        synced += 1
            if synced > 0 or reset:
                self.save()
        except Exception:
            pass
        return synced


# Global instance
_ENGINE = None

def get_learning_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = TailorLearningEngine()
    return _ENGINE

