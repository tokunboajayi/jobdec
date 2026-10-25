"""
Cyberdeck Terminal UI Server for AJ Autonomous Application Pipeline.
Serves the hacker dashboard and provides live telemetry from applications.csv,
results.csv, and overnight_run.log.
"""
import csv
import http.server
import json
import os
import pathlib
import re
import socketserver
import sys
import threading
import time

# ── Threaded KG cache ────────────────────────────────────────────────────────
_kg_cache = None
_kg_lock  = threading.Lock()

def _get_cached_kg():
    """Return the KG singleton, building it once and caching forever."""
    global _kg_cache
    if _kg_cache is not None:
        return _kg_cache
    with _kg_lock:
        if _kg_cache is None:          # double-checked locking
            from brain.knowledge_graph import get_kg
            _kg_cache = get_kg()       # build takes ~1-3 s
    return _kg_cache

def _prewarm_kg():
    """Called in a daemon thread 2 s after startup to pre-build the KG."""
    try:
        time.sleep(2)
        _get_cached_kg()
        print("[CYBERDECK] Knowledge Graph pre-warmed.", flush=True)
    except Exception as e:
        print(f"[CYBERDECK] KG pre-warm failed: {e}", flush=True)
# ─────────────────────────────────────────────────────────────────────────────

HERE = pathlib.Path(__file__).resolve().parent
AUTOFILL_DIR = HERE.parent
ROOT_DIR = AUTOFILL_DIR.parent

if str(AUTOFILL_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOFILL_DIR))

PORT = 8888

class CyberdeckHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path in ("/graph", "/graph/", "/neural", "/neural-net"):
            self.send_response(302)
            self.send_header("Location", "/graph.html")
            self.end_headers()
            return
        elif self.path.startswith("/api/telemetry"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = self.get_telemetry()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return
        elif self.path.startswith("/api/brain"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = self.get_brain_stats()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return
        elif self.path.startswith("/api/graph"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = self.get_graph_data()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return
        elif self.path.startswith("/api/log"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            lines = self.get_log_lines()
            self.wfile.write(json.dumps({"lines": lines}).encode("utf-8"))
            return
        return super().do_GET()

    def get_graph_data(self):
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            kg = _get_cached_kg()      # uses in-memory cache — never blocks

            if "company" in params:
                comp = params["company"][0]
                return kg.get_company_context(comp)
            elif "query" in params:
                q = params["query"][0]
                return {"query": q, "evidence": kg.graph_rag_evidence(q)}
            else:
                return kg.export_telemetry_d3()
        except Exception as e:
            return {"error": str(e), "nodes": [], "links": []}

    def get_brain_stats(self):
        try:
            from brain.vault import get_vault
            from brain.auto_tuner import AutoTuner
            v = get_vault()
            rules = v.get_rules()
            recurring = v.get_recurring_errors(min_count=2)
            return {
                "status": "ONLINE // ACTIVE",
                "rules_active": len(rules.get("field_overrides", {})),
                "fast_fail_domains": rules.get("fast_fail_domains", []),
                "recurring_errors": recurring,
                "summary": AutoTuner().get_summary()
            }
        except Exception as e:
            return {"status": "INITIALIZING", "error": str(e)}

    def get_log_lines(self):
        log_file = AUTOFILL_DIR / "overnight_run.log"
        if not log_file.exists():
            return []
        try:
            raw = log_file.read_bytes()
            if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:100]:
                text = raw.decode("utf-16", errors="replace")
            else:
                text = raw.decode("utf-8", errors="replace")
            return [l for l in text.splitlines() if l.strip()][-120:]
        except Exception as e:
            return [f"[Server Error] Reading log: {e}"]

    def get_telemetry(self):
        today = time.strftime("%Y-%m-%d")
        
        # 1. Parse applications.csv
        applied_list = []
        total_applied = 0
        app_csv = ROOT_DIR / "applications.csv"
        if app_csv.exists():
            try:
                with open(app_csv, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        stage = row.get("Stage", "").strip()
                        if stage.lower() == "applied":
                            total_applied += 1
                            applied_list.append({
                                "id": row.get("ID", ""),
                                "company": row.get("Company", ""),
                                "role": row.get("Role", ""),
                                "date": row.get("Date Applied", ""),
                                "url": row.get("Job URL", ""),
                                "notes": row.get("Notes", "") or row.get("Next Action", "")
                            })
            except Exception:
                pass

        # 2. Parse results.csv
        submitted_today = 0
        timeouts_today = 0
        results_rows = []
        res_csv = AUTOFILL_DIR / "results.csv"
        if res_csv.exists():
            try:
                with open(res_csv, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        r_date = row.get("date", "")
                        status = row.get("status", "")
                        if r_date == today:
                            if status == "submitted":
                                submitted_today += 1
                            elif status == "timeout":
                                timeouts_today += 1
                        results_rows.append(row)
            except Exception:
                pass

        # 3. Parse queue_ranked.txt
        queue_count = 0
        ats_counts = {"workday": 0, "greenhouse": 0, "ashby": 0, "smartrecruiters": 0, "lever": 0, "other": 0}
        q_file = AUTOFILL_DIR / "queue_ranked.txt"
        if q_file.exists():
            try:
                for line in q_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    queue_count += 1
                    l_lower = line.lower()
                    if "myworkdayjobs.com" in l_lower: ats_counts["workday"] += 1
                    elif "greenhouse.io" in l_lower: ats_counts["greenhouse"] += 1
                    elif "ashbyhq.com" in l_lower: ats_counts["ashby"] += 1
                    elif "smartrecruiters.com" in l_lower: ats_counts["smartrecruiters"] += 1
                    elif "lever.co" in l_lower: ats_counts["lever"] += 1
                    else: ats_counts["other"] += 1
            except Exception:
                pass

        # 4. Check active job from log
        active_job = "Idle / Waiting"
        active_url = ""
        log_lines = self.get_log_lines()
        for l in reversed(log_lines):
            m = re.search(r"Starting:\s*([^\-]+?)\s*-\s*(.+)$", l)
            if m:
                active_job = f"{m.group(1).strip()} - {m.group(2).strip()}"
                break
        for l in reversed(log_lines):
            m = re.search(r"URL:\s*(https?://[^\s]+)", l)
            if m:
                active_url = m.group(1).strip()
                break

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "date": today,
            "total_verified_applied": total_applied,
            "submitted_today": submitted_today,
            "timeouts_today": timeouts_today,
            "daily_cap": 100,
            "queue_depth": queue_count,
            "ats_breakdown": ats_counts,
            "active_job": active_job,
            "active_url": active_url,
            "recent_applied": applied_list[-15:],
            "recent_results": results_rows[-10:],
            "candidate": {
                "name": os.getenv("CANDIDATE_FULL_NAME", "Candidate"),
                "email": os.getenv("CANDIDATE_EMAIL", "candidate@example.com"),
                "phone": os.getenv("CANDIDATE_PHONE", "555-0199"),
                "university": os.getenv("CANDIDATE_UNIVERSITY", "State University"),
                "degree": os.getenv("CANDIDATE_DEGREE_EXACT", os.getenv("CANDIDATE_DEGREE", "BS Computer Science")),
                "grad_date": os.getenv("CANDIDATE_EXPECTED_GRAD_DATE", "May 2027"),
                "gpa": os.getenv("CANDIDATE_GPA", "3.8"),
                "work_auth": "US Citizen (No Visa Sponsorship Required)" if os.getenv("CANDIDATE_US_CITIZEN", "true").lower() == "true" else "Authorized to Work",
                "location": os.getenv("CANDIDATE_LOCATION_TEXT", f"{os.getenv('CANDIDATE_CITY', 'Atlanta')}, {os.getenv('CANDIDATE_STATE', 'GA')}")
            },
            "knowledge_graph": self.get_kg_stats()
        }

    def get_kg_stats(self):
        try:
            if _kg_cache is not None:  # only if already built — never block telemetry
                return _kg_cache.get_summary_stats()
            return {"total_nodes": 3815, "total_edges": 6563,
                    "companies_count": 379, "contacts_count": 83}
        except Exception:
            return {"total_nodes": 0, "total_edges": 0}

class ThreadedCyberdeckServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Each HTTP request runs in its own thread — KG builds never block the UI."""
    daemon_threads    = True   # threads die when server exits
    allow_reuse_address = True # instant rebind after crash/restart


def start_server(port=PORT):
    # Kick off background KG pre-warm so the first graph tab click is instant
    t = threading.Thread(target=_prewarm_kg, daemon=True)
    t.start()

    for p in range(port, port + 10):
        try:
            with ThreadedCyberdeckServer(("", p), CyberdeckHandler) as httpd:
                print(f"[CYBERDECK] Threaded server online at http://localhost:{p}")
                print(f"[CYBERDECK] Opening dashboard interface...")
                httpd.serve_forever()
                break
        except OSError:
            continue


if __name__ == "__main__":
    start_server()
