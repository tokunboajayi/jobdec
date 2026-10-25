"""
AJ AGENT BRAIN // AUTO-TUNER & SELF-HEALING ENGINE
Continuously monitors recurring failure patterns across all ATS portals,
compiles dynamic rules into brain memory, and optimizes crawler velocity.
"""
import re
from typing import Any, Dict, List
from .vault import get_vault
from .stealth_engine import get_stealth_engine, TIER_HARDENED, TIER_MANUAL


class AutoTuner:
    """Analyzes error vault signatures and generates dynamic rules."""

    def __init__(self):
        self.vault = get_vault()

    def tune_all(self) -> Dict[str, Any]:
        """Runs pattern detection and applies self-healing patches."""
        recurring = self.vault.get_recurring_errors(min_count=2)
        patches_applied = []

        for err in recurring:
            sig = err["signature"]
            err_type = err.get("error_type", "")
            domain = err.get("domain", "")
            label = err.get("label", "")
            details = err.get("last_details", "")

            # Rule 1: Auto Fast-Fail for Unbypassable Auth / Manual Interventions & Anti-Bot Escalation
            if "manual intervention" in details.lower() or "auth screen requires" in details.lower() or "blocked" in err_type.lower() or "waf" in details.lower() or "bot" in details.lower():
                stealth = get_stealth_engine()
                new_tier = stealth.record_challenge(domain, err_type, details)
                patches_applied.append(f"[Anti-Bot] Escalated {domain} stealth tier to '{new_tier}'")
                if domain and new_tier == TIER_MANUAL and not self.vault.is_fast_fail(domain):
                    self.vault.save_rule("fast_fail_domains", domain, True)
                    patches_applied.append(f"[Fast-Fail] Added {domain} to fast-fail list (unbypassable bot defense)")
                    err["status"] = "resolved_fast_fail"

            # Rule 2: Date Format Mismatch Auto-Heal
            if "date" in label.lower() and ("format" in details.lower() or "invalid" in details.lower()):
                # Determine expected format
                if "mm/dd/yyyy" in details.lower() or "format: mm/dd/yyyy" in details.lower():
                    self.vault.save_rule("field_overrides", label.strip().lower(), "06/01/2027")
                    patches_applied.append(f"[Date Override] Mapped {label} -> '06/01/2027'")
                    err["status"] = "resolved_override"

            # Rule 3: Missing Required Custom Questions
            if "required and must have a value" in details.lower():
                m = re.search(r"The field\s+(.+?)\s+is required", details)
                if m:
                    missing_field = m.group(1).strip()
                    # If it's an AI screening question
                    if "artificial intelligence" in missing_field.lower():
                        self.vault.save_rule("field_overrides", missing_field.lower(), "Yes")
                        patches_applied.append(f"[Field Override] Auto-mapped AI screening field to 'Yes'")
                        err["status"] = "resolved_override"

            # Rule 4: Dropdown Mismatch - option text doesn't match expected value
            if "dropdown" in err_type.lower() or "select" in err_type.lower() or "option not found" in details.lower():
                m = re.search(r"expected\s+['\"](.+?)['\"]\s+but\s+found\s+['\"](.+?)['\"]", details)
                if m:
                    expected, found = m.group(1).strip(), m.group(2).strip()
                    self.vault.save_rule("custom_dropdown_maps", expected.lower(), found)
                    patches_applied.append(f"[Dropdown Map] '{expected}' → '{found}'")
                    err["status"] = "resolved_dropdown"

            # Rule 5: Repeated Timeout on Same Domain → add to slow sites list
            if err.get("count", 0) >= 3 and "timeout" in err_type.lower():
                if domain:
                    self.vault.save_rule("domain_rules", domain, {"timeout_override": 480})
                    patches_applied.append(f"[Timeout] {domain} marked as slow site (480s timeout)")
                    err["status"] = "resolved_timeout"

            # Rule 6: File Upload Failures → mark domain for retry with alternative method
            if "upload" in err_type.lower() or "file input" in details.lower():
                if domain:
                    self.vault.save_rule("domain_rules", domain, {"upload_method": "set_input_files"})
                    patches_applied.append(f"[Upload Fix] {domain} switched to set_input_files method")
                    err["status"] = "resolved_upload"

        return {
            "recurring_count": len(recurring),
            "patches_applied": patches_applied
        }

    def get_summary(self) -> str:
        rules = self.vault.get_rules()
        ff = rules.get("fast_fail_domains", [])
        overrides = rules.get("field_overrides", {})
        metrics = self.vault._load_json(self.vault.metrics_file)
        doms = metrics.get("domains", {})
        elevated = sum(1 for d in doms.values() if d.get("stealth_tier") in (TIER_HARDENED, "elevated"))
        return f"Brain Rules Active: {len(overrides)} field overrides, {len(ff)} fast-fail domains, {elevated} active stealth-tuned domains."


def run_auto_tuner():
    tuner = AutoTuner()
    res = tuner.tune_all()
    print(f"[Agent Brain] Tuning completed: {len(res['patches_applied'])} patches applied.")
    for p in res["patches_applied"]:
        print(f"  + {p}")
    return res


if __name__ == "__main__":
    run_auto_tuner()
