"""
Agent Supervisor — Always-On Self-Healing Daemon.

Continuously monitors the application pipeline, diagnoses failures in real-time,
dispatches the appropriate fix agent, verifies the fix, and retries failed jobs.

    python -m agents.supervisor              # foreground (Ctrl-C to stop)
    python -m agents.supervisor --once       # single scan, no loop
    python -m agents.supervisor --interval 30  # custom poll interval

Architecture:
    ┌─────────────┐     ┌──────────────┐     ┌────────────────┐
    │  Watcher     │────>│  Diagnostics  │────>│  Dispatch      │
    │  (poll loop) │     │  Engine       │     │  Table         │
    └─────────────┘     └──────────────┘     └───┬────────────┘
                                                  │
                        ┌─────────────────────────┼─────────────────┐
                        │              │          │          │       │
                   rule_gap      timeout     anti_bot    crash   auth_wall
                   site_fixer    extend_t    stealth    code_fix  fast_fail
                        │              │          │          │       │
                        └─────────────>┴─────────>┴──────────┘       │
                                  Retry Queue                   Skip List
                                  (max 3/job)
"""
import argparse, datetime, json, pathlib, sys, time, traceback
from typing import Any, Dict, List, Optional, Set

AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
HEAL_LOG = AUTOFILL / "brain" / "heal_log.json"
RETRY_STATE = AUTOFILL / "brain" / "retry_state.json"
MAX_RETRIES = 3
DEFAULT_INTERVAL = 45  # seconds between scans


# ---------------------------------------------------------------- heal log
def _load_json(p: pathlib.Path) -> Any:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_json(p: pathlib.Path, data: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _log_heal(action: str, target: str, result: str, detail: str = ""):
    """Append an entry to the heal audit log."""
    log = _load_json(HEAL_LOG)
    entries = log.get("entries", [])
    entries.append({
        "time": datetime.datetime.now().isoformat(),
        "action": action,
        "target": target,
        "result": result,
        "detail": detail[:300],
    })
    if len(entries) > 1000:
        entries = entries[-1000:]
    log["entries"] = entries
    log["last_scan"] = datetime.datetime.now().isoformat()
    _save_json(HEAL_LOG, log)


# ---------------------------------------------------------------- retry state
def _get_retries() -> Dict[str, int]:
    return _load_json(RETRY_STATE) or {}


def _inc_retry(key: str) -> int:
    state = _get_retries()
    state[key] = state.get(key, 0) + 1
    _save_json(RETRY_STATE, state)
    return state[key]


def _can_retry(key: str) -> bool:
    return _get_retries().get(key, 0) < MAX_RETRIES


# ---------------------------------------------------------------- pre-submit guard
def pre_submit_check(url: str, company: str, resume_path: str) -> Optional[str]:
    """Fast invariant check before spawning fill.py.  Returns None if OK, else reason to skip."""
    # 1. Resume exists
    if resume_path and not pathlib.Path(resume_path).exists():
        return f"Resume not found: {resume_path}"

    # 2. profile.json valid
    profile = AUTOFILL / "profile.json"
    if not profile.exists():
        return "profile.json missing"
    try:
        json.loads(profile.read_text(encoding="utf-8"))
    except Exception as e:
        return f"profile.json corrupt: {e}"

    # 3. Known fast-fail domain
    try:
        import urllib.parse
        sys.path.insert(0, str(AUTOFILL))
        from brain.vault import get_vault
        dom = urllib.parse.urlparse(url).netloc.lower()
        if get_vault().is_fast_fail(dom):
            return f"Domain {dom} is on fast-fail list"
    except Exception:
        pass

    return None  # all good


# ---------------------------------------------------------------- dispatch table
def _dispatch_rule_gap(diag):
    """Attempt to fix unanswered questions by running site_fixer rule generation."""
    try:
        from agents import site_fixer
        # Build a minimal failure record for site_fixer
        fake_failures = [{"unanswered_questions": diag.unanswered,
                          "blocked_sensitive_questions": diag.blocked,
                          "url": diag.url, "status": diag.status}]
        added, remaining = site_fixer.fix_rules(fake_failures)
        if added:
            _log_heal("rule_fix", diag.slug, "success",
                      f"Added {len(added)} rules: {[r['q'] for r in added]}")
            return True, f"Added {len(added)} rules"
        else:
            _log_heal("rule_fix", diag.slug, "no_fix",
                      f"Could not fix: {remaining[:5]}")
            return False, f"No rules generated for {len(remaining)} questions"
    except Exception as e:
        _log_heal("rule_fix", diag.slug, "error", str(e))
        return False, str(e)


def _dispatch_timeout(diag):
    """Extend per-site timeout in sites.json so the next attempt gets more time."""
    try:
        from agents import smarts
        sites = smarts._load(smarts.SITES)
        key = smarts._ukey(diag.url)
        site = sites.get(key, {})
        old_timeout = site.get("timeout_override", 260)
        new_timeout = min(old_timeout + 60, 600)  # cap at 10 min
        site["timeout_override"] = new_timeout
        sites[key] = site
        smarts._save(smarts.SITES, sites)
        _log_heal("extend_timeout", diag.slug, "success",
                  f"{old_timeout}s → {new_timeout}s")
        return True, f"Timeout extended to {new_timeout}s"
    except Exception as e:
        _log_heal("extend_timeout", diag.slug, "error", str(e))
        return False, str(e)


def _dispatch_stealth(diag):
    """Escalate stealth tier for bot-detected domains."""
    try:
        import urllib.parse
        from brain.vault import get_vault
        from brain.stealth_engine import get_stealth_engine
        dom = urllib.parse.urlparse(diag.url).netloc.lower()
        se = get_stealth_engine()
        new_tier = se.record_challenge(dom, "anti_bot", diag.detail)
        _log_heal("stealth_escalate", dom, "success", f"Tier → {new_tier}")
        return True, f"Stealth escalated to {new_tier}"
    except Exception as e:
        _log_heal("stealth_escalate", diag.slug, "error", str(e))
        return False, str(e)



RETRY_QUEUE = AUTOFILL / "queue_retry.txt"


def re_queue(diag):
    """Write a successfully healed job to queue_retry.txt for immediate re-application."""
    if not diag.url or not diag.company:
        return
    entry = f"{diag.company} {diag.role} {diag.url}".strip()
    existing = set()
    if RETRY_QUEUE.exists():
        existing = set(RETRY_QUEUE.read_text(encoding="utf-8").splitlines())
    if entry not in existing:
        with open(RETRY_QUEUE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        _log_heal("re_queue", diag.slug, "queued", entry)


def _dispatch_code_fix(diag):
    """Attempt a code fix via site_fixer (gated by compile check and regression replay)."""
    try:
        from agents import site_fixer
        day = datetime.date.today().isoformat()
        d_dir = AUTOFILL / "records" / day
        matches = list(d_dir.glob(f"*{diag.company}*.json")) if d_dir.exists() else []
        if not matches:
            _log_heal("code_fix_candidate", diag.slug, "no_record", "Record json not found")
            return False, "Failure record json not found"
        target_json = matches[0]
        rec = json.loads(target_json.read_text(encoding="utf-8"))
        rec["_json"] = target_json
        rec["_html"] = target_json.with_suffix(".html")
        rec["_log"] = target_json.with_suffix(".log")
        res = site_fixer.fix_code(rec)
        # Log detailed result payload for debugging
        detail = json.dumps(res, default=str)
        if res and res.get("applied"):
            _log_heal("code_patch", diag.slug, "applied", detail)
            return True, f"Code patch applied and verified by replay: {res.get('why', '')}"
        elif res:
            _log_heal("code_patch", diag.slug, "rejected", detail)
            return False, f"Code patch rejected by safety gate: {res.get('why', '')}"
        else:
            _log_heal("code_patch", diag.slug, "no_result", "site_fixer returned None or empty")
            return False, "Site fixer declined code patch (low confidence or requirements not met)"
    except Exception as e:
        _log_heal("code_fix", diag.slug, "error", str(e))
        return False, str(e)


def _dispatch_validation_error(diag):
    """Automatically resolve validation errors by looking up the field in resolver.py."""
    try:
        from brain.resolver import fast_resolve
        from brain.vault import get_vault
        import re
        field_match = re.search(r"Validation alert:\s*(?:Error-)?([^\n\r]+)", diag.detail)
        field = field_match.group(1).strip() if field_match else diag.detail
        # Strip trailing requirement text
        field_clean = re.sub(r"\s+(?:is required and must have a value|is required|must be filled).*", "", field, flags=re.I).strip()
        ans = fast_resolve(field_clean)
        if ans:
            # suggestion only: saved guesses answered a securities-order question with "Georgia" (2026-10-28)
            _log_heal("validation_override", diag.slug, "suggested", f"'{field_clean}' -> '{ans}' (not saved)")
            return False, f"Suggested '{ans}' for '{field_clean}' (not saved; add a profile.json rule if right)"
        else:
            _log_heal("validation_override", diag.slug, "unresolved", field_clean)
            return False, f"Could not resolve validation field '{field_clean}'"
    except Exception as e:
        _log_heal("validation_override", diag.slug, "error", str(e))
        return False, str(e)


def _dispatch_stuck_page(diag):
    """Escalate stuck page handling via AutoTuner and timeout extension."""
    try:
        import urllib.parse
        from brain.auto_tuner import AutoTuner
        from brain.vault import get_vault
        dom = urllib.parse.urlparse(diag.url).netloc.lower()
        AutoTuner().tune_all()
        # Extend site timeout
        _dispatch_timeout(diag)
        _log_heal("stuck_page_escalate", dom, "success", f"Tuned and extended timeout for {dom}")
        return True, f"Auto-tuned and extended timeout for {dom}"
    except Exception as e:
        _log_heal("stuck_page_escalate", diag.slug, "error", str(e))
        return False, str(e)


def _dispatch_upload_error(diag):
    """Auto-heal file upload failures via AutoTuner and fallback profile settings."""
    try:
        import urllib.parse
        from brain.vault import get_vault
        dom = urllib.parse.urlparse(diag.url).netloc.lower()
        vault = get_vault()
        vault.save_rule("domain_rules", dom, {"upload_mode": "raw_input", "retry_without_file": True})
        _log_heal("upload_heal", dom, "success", "Switched upload mode to raw_input")
        return True, f"Configured upload fallback for {dom}"
    except Exception as e:
        _log_heal("upload_heal", diag.slug, "error", str(e))
        return False, str(e)


DISPATCH = {
    "rule_gap":         _dispatch_rule_gap,
    "validation_error": _dispatch_validation_error,
    "upload_error":     _dispatch_upload_error,
    "stuck_page":       _dispatch_stuck_page,
    "timeout":          _dispatch_timeout,
    "anti_bot":         _dispatch_stealth,
    # a login wall or one closed posting is per job, not per site: fast-failing the domain blocked 191 sites (2026-10-28)
    "auth_wall":        lambda d: (_log_heal("auth_wall", d.slug, "skipped", d.detail), (False, "Per-job auth wall"))[1],
    "site_dead":        lambda d: (_log_heal("site_dead", d.slug, "skipped", d.detail), (False, "Per-job dead posting"))[1],
    "crash":            _dispatch_code_fix,
    "unknown":          lambda d: (_log_heal("unknown", d.slug, "skipped", d.detail), (False, "Unknown category"))[1],
}


# ---------------------------------------------------------------- main scan
def scan_and_heal(day: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
    """Single scan: diagnose all failures, dispatch fixes, report results."""
    from agents.diagnostics import scan_day, summary
    diagnoses = scan_day(day)
    if not diagnoses:
        if verbose:
            print(f"[Supervisor] No failures found for {day or 'today'}.")
        return {"scanned": 0, "healed": 0, "retryable": 0}

    counts = summary(diagnoses)
    healed = 0
    retryable = 0
    actions_taken = []

    if verbose:
        print(f"[Supervisor] Scanned {len(diagnoses)} failures: {counts}")

    for diag in diagnoses:
        key = f"{diag.company}:{diag.role}:{diag.url}"

        # Skip if max retries exceeded
        if not _can_retry(key):
            if verbose:
                print(f"  [X] {diag.slug}: max retries ({MAX_RETRIES}) exceeded")
            continue

        # Dispatch the fix
        handler = DISPATCH.get(diag.category)
        if handler:
            try:
                success, msg = handler(diag)
                if success:
                    healed += 1
                    _inc_retry(key)
                    re_queue(diag)
                    actions_taken.append(f"[OK] {diag.category}: {diag.slug} -> {msg}")
                else:
                    actions_taken.append(f"[X] {diag.category}: {diag.slug} -> {msg}")
            except Exception as e:
                actions_taken.append(f"[!] {diag.category}: {diag.slug} -> error: {e}")

        if diag.retryable and _can_retry(key):
            retryable += 1

    if verbose:
        for a in actions_taken:
            print(f"  {a}")
        print(f"[Supervisor] Healed: {healed}, Retryable: {retryable}")

    return {
        "scanned": len(diagnoses),
        "categories": counts,
        "healed": healed,
        "retryable": retryable,
        "actions": actions_taken,
    }


# ---------------------------------------------------------------- live callback (for batch_apply)
def on_job_complete(rec: Dict[str, Any], log_path: pathlib.Path) -> Optional[str]:
    """Called immediately after each job in batch_apply.  Returns heal action taken or None."""
    if rec.get("status") == "submitted":
        return None
    from agents.diagnostics import classify
    log_tail = ""
    if log_path and log_path.exists():
        try:
            log_tail = log_path.read_text(encoding="utf-8", errors="ignore")[-3000:]
        except Exception:
            pass
    diag = classify(rec, log_tail)
    key = f"{rec.get('company', '')}:{rec.get('role', '')}:{rec.get('url', '')}"
    if not _can_retry(key):
        return None

    handler = DISPATCH.get(diag.category)
    if handler:
        try:
            success, msg = handler(diag)
            if success:
                _inc_retry(key)
                re_queue(diag)
                return f"[Supervisor] Healed {diag.category}: {msg}"
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- daemon loop
def run_daemon(interval: int = DEFAULT_INTERVAL, once: bool = False):
    """Poll loop: scan, heal, sleep, repeat."""
    print(f"[Supervisor] Self-healing daemon started (interval={interval}s, once={once})")
    print(f"[Supervisor] Watching: {AUTOFILL / 'records'}")
    print(f"[Supervisor] Heal log: {HEAL_LOG}")

    seen: Set[str] = set()
    iteration = 0

    while True:
        iteration += 1
        try:
            day = datetime.date.today().isoformat()
            result = scan_and_heal(day, verbose=True)

            # Also run auto-tuner periodically
            if iteration % 5 == 0:
                try:
                    from brain.auto_tuner import run_auto_tuner
                    run_auto_tuner()
                except Exception as e:
                    print(f"[Supervisor] Auto-tuner error: {e}")

        except KeyboardInterrupt:
            print("\n[Supervisor] Stopped by user.")
            break
        except Exception:
            traceback.print_exc()

        if once:
            break

        time.sleep(interval)


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-Healing Agent Supervisor")
    parser.add_argument("--once", action="store_true", help="Single scan, no loop")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--day", default=None, help="Scan a specific day (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.day:
        scan_and_heal(args.day)
    else:
        run_daemon(interval=args.interval, once=args.once)
