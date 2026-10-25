"""
AJ AGENT BRAIN // ERROR VAULT & PERSISTENT MEMORY
Stores error signatures, tracks failure frequencies across ATS portals,
and manages self-healed resolution rules.
"""
import hashlib
import json
import os
import pathlib
import threading
import time
from typing import Any, Dict, List, Optional

HERE = pathlib.Path(__file__).resolve().parent
VAULT_FILE = HERE / "error_vault.json"
RULES_FILE = HERE / "rules.json"
DOMAIN_METRICS_FILE = HERE / "domain_metrics.json"

_LOCK = threading.Lock()


class ErrorVault:
    def __init__(self, data_dir: Optional[pathlib.Path] = None):
        self.dir = data_dir or HERE
        self.vault_file = self.dir / "error_vault.json"
        self.rules_file = self.dir / "rules.json"
        self.metrics_file = self.dir / "domain_metrics.json"
        self._ensure_files()

    def _ensure_files(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.vault_file.exists():
            self._save_json(self.vault_file, {"signatures": {}, "history": []})
        if not self.rules_file.exists():
            self._save_json(self.rules_file, {
                "field_overrides": {},
                "domain_rules": {},
                "fast_fail_domains": [],
                "custom_dropdown_maps": {}
            })
        if not self.metrics_file.exists():
            self._save_json(self.metrics_file, {"domains": {}})

    def _load_json(self, p: pathlib.Path) -> Dict[str, Any]:
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_json(self, p: pathlib.Path, data: Any):
        try:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def compute_signature(ats: str, domain: str, step: int, label: str, err_type: str) -> str:
        norm_label = (label or "").strip().lower()[:60]
        raw = f"{ats}:{domain}:{step}:{norm_label}:{err_type}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def record_error(
        self,
        ats: str,
        domain: str,
        url: str,
        step: int,
        selector: str,
        label: str,
        error_type: str,
        details: str = ""
    ) -> str:
        """Records an obstacle or failure. Returns the error signature."""
        sig = self.compute_signature(ats, domain, step, label, error_type)
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        with _LOCK:
            vault = self._load_json(self.vault_file)
            sigs = vault.setdefault("signatures", {})
            history = vault.setdefault("history", [])

            if sig not in sigs:
                sigs[sig] = {
                    "signature": sig,
                    "ats": ats,
                    "domain": domain,
                    "step": step,
                    "label": label[:100],
                    "selector": selector[:120],
                    "error_type": error_type,
                    "first_seen": now,
                    "last_seen": now,
                    "count": 1,
                    "last_details": details[:300],
                    "status": "unresolved"
                }
            else:
                sigs[sig]["count"] += 1
                sigs[sig]["last_seen"] = now
                sigs[sig]["last_details"] = details[:300]

            history.append({
                "sig": sig,
                "domain": domain,
                "step": step,
                "error_type": error_type,
                "time": now
            })
            if len(history) > 500:
                history = history[-500:]
            vault["history"] = history

            self._save_json(self.vault_file, vault)

            # Update domain failure count
            self._update_domain_metric(domain, success=False)

        return sig

    def record_success(self, domain: str, answers_count: int, duration_sec: float):
        """Records a verified successful submission for domain velocity tracking."""
        with _LOCK:
            self._update_domain_metric(domain, success=True, answers=answers_count, duration=duration_sec)

    def _update_domain_metric(self, domain: str, success: bool, answers: int = 0, duration: float = 0.0):
        metrics = self._load_json(self.metrics_file)
        doms = metrics.setdefault("domains", {})
        d = doms.setdefault(domain, {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "avg_duration": 0.0,
            "last_active": ""
        })
        d["attempts"] += 1
        d["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if success:
            d["successes"] += 1
            if duration > 0:
                old_avg = d.get("avg_duration", 0.0)
                n = d["successes"]
                d["avg_duration"] = round(((old_avg * (n - 1)) + duration) / n, 2)
        else:
            d["failures"] += 1
        self._save_json(self.metrics_file, metrics)

    def get_recurring_errors(self, min_count: int = 2) -> List[Dict[str, Any]]:
        """Returns all signatures that have repeated min_count or more times."""
        with _LOCK:
            vault = self._load_json(self.vault_file)
            sigs = vault.get("signatures", {})
            return [v for v in sigs.values() if v.get("count", 0) >= min_count and v.get("status") != "resolved"]

    def get_rules(self) -> Dict[str, Any]:
        with _LOCK:
            return self._load_json(self.rules_file)

    PROTECTED_ATS_DOMAINS = {
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
        "boards.greenhouse.io",
        "jobs.ashbyhq.com",
        "myworkdayjobs.com",
        "myworkdaysite.com",
        "icims.com",
        "workable.com",
    }

    def save_rule(self, category: str, key: str, value: Any):
        """Saves an auto-generated or self-healed rule."""
        if category == "fast_fail_domains":
            key_low = (key or "").lower()
            if key_low in self.PROTECTED_ATS_DOMAINS or any(key_low.endswith("." + d) for d in ("greenhouse.io", "ashbyhq.com", "lever.co")):
                return
        with _LOCK:
            rules = self._load_json(self.rules_file)
            cat = rules.setdefault(category, {})
            if isinstance(cat, dict):
                cat[key] = value
            elif isinstance(cat, list) and key not in cat:
                cat.append(key)
            self._save_json(self.rules_file, rules)

    def get_field_override(self, label: str) -> Optional[Any]:
        rules = self.get_rules()
        overrides = rules.get("field_overrides", {})
        norm = label.strip().lower()
        return overrides.get(norm)

    def is_fast_fail(self, domain: str) -> bool:
        dom_low = (domain or "").lower()
        if dom_low in self.PROTECTED_ATS_DOMAINS or any(dom_low.endswith("." + d) for d in ("greenhouse.io", "ashbyhq.com")):
            return False
        rules = self.get_rules()
        ff = rules.get("fast_fail_domains", [])
        return domain in ff


_GLOBAL_VAULT = None

def get_vault() -> ErrorVault:
    global _GLOBAL_VAULT
    if _GLOBAL_VAULT is None:
        _GLOBAL_VAULT = ErrorVault()
    return _GLOBAL_VAULT
