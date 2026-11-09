"""
Job Deck Executive Web Command Center.
Lightweight, zero-dependency, dark-mode real-time dashboard powered by Python's ThreadingHTTPServer.
Provides real-time pipeline monitoring, runner controls, interview battlecards,
and referral radar directly from any desktop or mobile browser.
"""
import csv
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, date
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent

# Re-use metrics & actions from telegram_bot_service / telegram_query_engine
try:
    import telegram_bot_service as tbs
    import telegram_query_engine as tqe
    from agents import interview_prep, referral_radar
except Exception:
    tbs = None
    tqe = None

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Deck — Executive Operations Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #090d16;
            --bg-card: rgba(18, 24, 38, 0.75);
            --bg-card-border: rgba(255, 255, 255, 0.08);
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent-cyan: #38bdf8;
            --accent-green: #34d399;
            --accent-purple: #a855f7;
            --accent-amber: #fbbf24;
            --accent-rose: #f43f5e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg-base);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', sans-serif;
            min-height: 100vh;
            padding: 24px;
            background-image: radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.08) 0%, transparent 40%),
                              radial-gradient(circle at 85% 85%, rgba(168, 85, 247, 0.08) 0%, transparent 40%);
        }
        .container { max-width: 1300px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--bg-card-border);
        }
        .brand { display: flex; align-items: center; gap: 12px; }
        .logo-badge {
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            color: #090d16;
            font-weight: 800;
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 15px;
            letter-spacing: 0.5px;
        }
        h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
        .live-tag {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--accent-green);
            background: rgba(52, 211, 153, 0.1);
            padding: 4px 10px;
            border-radius: 20px;
            border: 1px solid rgba(52, 211, 153, 0.25);
            font-family: 'JetBrains Mono', monospace;
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.3); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
        }
        .grid-kpis {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .card {
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--bg-card-border);
            border-radius: 12px;
            padding: 18px;
            transition: transform 0.2s, border-color 0.2s;
        }
        .card:hover { border-color: rgba(56, 189, 248, 0.3); }
        .kpi-title { font-size: 13px; color: var(--text-muted); font-weight: 500; margin-bottom: 6px; }
        .kpi-value { font-size: 28px; font-weight: 800; font-family: 'JetBrains Mono', monospace; }
        .kpi-sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
        
        .progress-bar-bg {
            background: rgba(255, 255, 255, 0.08);
            height: 6px;
            border-radius: 4px;
            margin-top: 10px;
            overflow: hidden;
        }
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #34d399);
            width: 35.4%;
            border-radius: 4px;
        }
        .section-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
        
        /* Action buttons panel */
        .actions-panel {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 24px;
        }
        .btn {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--bg-card-border);
            color: var(--text-main);
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s ease;
        }
        .btn:hover { background: rgba(255, 255, 255, 0.12); transform: translateY(-1px); }
        .btn-primary { background: linear-gradient(135deg, #0284c7, #2563eb); border: none; }
        .btn-primary:hover { background: linear-gradient(135deg, #0369a1, #1d4ed8); }
        .btn-danger { background: rgba(244, 63, 94, 0.15); color: #fda4af; border-color: rgba(244, 63, 94, 0.3); }
        .btn-danger:hover { background: rgba(244, 63, 94, 0.25); }

        /* Tables */
        .table-wrap { overflow-x: auto; margin-top: 10px; }
        table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
        th { text-align: left; padding: 12px 14px; color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--bg-card-border); }
        td { padding: 12px 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11.5px;
            font-weight: 600;
            background: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            font-family: 'JetBrains Mono', monospace;
        }
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #1e293b;
            color: #fff;
            padding: 12px 20px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            display: none;
            z-index: 1000;
            font-size: 13.5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="logo-badge">JOB DECK</div>
                <h1>Executive Operations Center</h1>
            </div>
            <div class="live-tag">
                <div class="pulse-dot"></div>
                <span id="liveStatusText">RUNNER IDLE</span>
            </div>
        </header>

        <div class="grid-kpis">
            <div class="card">
                <div class="kpi-title">TOTAL SUBMISSIONS</div>
                <div class="kpi-value" style="color: var(--accent-cyan);" id="kpiTotal">1,063</div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="kpiProgress"></div>
                </div>
                <div class="kpi-sub" id="kpiTargetSub">Goal: 3,000 Verified Submissions</div>
            </div>
            <div class="card">
                <div class="kpi-title">TODAY'S APPLICATIONS</div>
                <div class="kpi-value" style="color: var(--accent-green);" id="kpiToday">--</div>
                <div class="kpi-sub" id="kpiActiveWorkers">Active Workers: 0</div>
            </div>
            <div class="card">
                <div class="kpi-title">UNAPPLIED QUEUE</div>
                <div class="kpi-value" style="color: var(--accent-amber);" id="kpiQueue">--</div>
                <div class="kpi-sub" id="kpiQueueSub">US Cyber, IAM & Support</div>
            </div>
            <div class="card">
                <div class="kpi-title">SYSTEM MEMORY / WORKERS</div>
                <div class="kpi-value" style="color: var(--accent-purple);" id="kpiMem">-- MB</div>
                <div class="kpi-sub" id="kpiOptimalWorkers">Optimal Workers: 3</div>
            </div>
        </div>

        <div class="section-title">⚡ Autonomous Operations Controls</div>
        <div class="actions-panel">
            <button class="btn btn-primary" onclick="triggerAction('start')">▶ Run 3 Headless Workers</button>
            <button class="btn" onclick="triggerAction('turbo')">⚡ Turbo (4 Workers)</button>
            <button class="btn btn-danger" onclick="triggerAction('stop')">🛑 Pause Runner</button>
            <button class="btn" onclick="triggerAction('clean')">🧹 Clean Telegram Chat</button>
            <button class="btn" onclick="promptPrep()">🎯 Generate Interview Battlecard</button>
            <button class="btn" onclick="promptRadar()">👥 Warm Referral Radar</button>
        </div>

        <div class="card" style="margin-bottom: 24px;">
            <div class="section-title">📋 Recent Live Submissions</div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Company</th>
                            <th>Role Title</th>
                            <th>Date Applied</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="recentTableBody">
                        <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Loading recent submissions...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="toast" class="toast"></div>

    <script>
        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3500);
        }

        async function fetchMetrics() {
            try {
                const res = await fetch('/api/metrics');
                const data = await res.json();
                
                document.getElementById('kpiTotal').innerText = Number(data.total_applied).toLocaleString();
                document.getElementById('kpiToday').innerText = data.today_applied;
                document.getElementById('kpiQueue').innerText = data.unapplied_count;
                document.getElementById('kpiMem').innerText = data.total_mem_mb + ' MB';
                document.getElementById('kpiActiveWorkers').innerText = 'Active Workers: ' + data.worker_count;
                document.getElementById('kpiOptimalWorkers').innerText = 'Optimal Capacity: ' + data.optimal_workers + ' Workers';

                const pct = Math.min(100, ((data.total_applied / 3000) * 100)).toFixed(1);
                document.getElementById('kpiProgress').style.width = pct + '%';
                document.getElementById('kpiTargetSub').innerText = 'Goal: 3,000 (' + pct + '% Complete)';

                if (data.is_running) {
                    document.getElementById('liveStatusText').innerText = 'RUNNING (' + data.worker_count + ' WORKERS)';
                    document.getElementById('liveStatusText').style.color = 'var(--accent-green)';
                } else {
                    document.getElementById('liveStatusText').innerText = 'RUNNER IDLE';
                    document.getElementById('liveStatusText').style.color = 'var(--text-muted)';
                }

                // Table
                if (data.recent && data.recent.length > 0) {
                    const tbody = document.getElementById('recentTableBody');
                    tbody.innerHTML = '';
                    data.recent.slice().reverse().forEach(r => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><b>${r.Company || 'Unknown'}</b></td>
                            <td>${r.Role || 'Role'}</td>
                            <td>${r['Date Applied'] || 'Recent'}</td>
                            <td><span class="badge">SUBMITTED</span></td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            } catch(e) {
                console.error("Metric fetch failed", e);
            }
        }

        async function triggerAction(action) {
            try {
                const res = await fetch('/api/action/' + action, { method: 'POST' });
                const d = await res.json();
                showToast(d.message || 'Action executed!');
                fetchMetrics();
            } catch(e) {
                showToast('Error executing action: ' + e);
            }
        }

        function promptPrep() {
            const comp = prompt("Enter Target Company Name for Interview Battlecard (e.g. CrowdStrike, Okta, Intuit):");
            if (!comp) return;
            const role = prompt("Enter Target Role (optional, e.g. SOC Analyst, IAM Engineer):", "Cybersecurity Specialist");
            fetch('/api/action/prep', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ company: comp, role: role || '' })
            }).then(r => r.json()).then(d => {
                showToast(d.message || "Battlecard generated!");
            });
        }

        function promptRadar() {
            const comp = prompt("Enter Target Company Name for Warm Referral Radar (e.g. Tenable, Stripe, Axon):");
            if (!comp) return;
            fetch('/api/action/radar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ company: comp, role: "Cybersecurity" })
            }).then(r => r.json()).then(d => {
                showToast(d.message || "Referral radar generated!");
            });
        }

        fetchMetrics();
        setInterval(fetchMetrics, 4000);
    </script>
</body>
</html>
"""


_METRICS_CACHE = {}
_LAST_METRICS_TIME = 0.0

def get_cached_metrics(ttl=2.5):
    global _METRICS_CACHE, _LAST_METRICS_TIME
    now = time.time()
    if not _METRICS_CACHE or (now - _LAST_METRICS_TIME) > ttl:
        if tbs:
            _METRICS_CACHE = tbs.get_realtime_metrics()
        else:
            _METRICS_CACHE = {}
        _LAST_METRICS_TIME = now
    return _METRICS_CACHE


class DashboardRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        # Quiet logger to avoid polluting terminal
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ["/", "/index.html"]:
            payload = HTML_DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            return

        elif path == "/api/metrics":
            metrics = get_cached_metrics()
            payload = json.dumps(metrics).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        data = json.loads(body) if body and body.startswith("{") else {}

        resp = {"ok": True, "message": "Action completed"}

        if path == "/api/action/start":
            if tbs: tbs.launch_runner(workers=3)
            resp["message"] = "🚀 Launched 3 headless workers!"

        elif path == "/api/action/turbo":
            if tbs: tbs.launch_runner(workers=4)
            resp["message"] = "⚡ Launched Turbo 4 headless workers!"

        elif path == "/api/action/stop":
            stopped = tbs.halt_runner() if tbs else 0
            resp["message"] = f"🛑 Runner paused ({stopped} stopped)."

        elif path == "/api/action/clean":
            if tqe:
                q_ids = tqe.clear_all_pending_questions()
                app_ids = tqe.clear_all_application_messages()
                resp["message"] = f"🧹 Cleaned {len(app_ids)} application updates and {len(q_ids)} questions!"
            else:
                resp["message"] = "Cleanup executed."

        elif path == "/api/action/prep":
            comp = data.get("company", "Target Company")
            role = data.get("role", "Cybersecurity Specialist")
            card = interview_prep.generate_interview_battlecard(comp, role)
            resp["message"] = f"🎯 Battlecard generated for {comp}! Saved to {Path(card['file_path']).name}"

        elif path == "/api/action/radar":
            comp = data.get("company", "Target Company")
            role = data.get("role", "Cybersecurity Specialist")
            dossier = referral_radar.build_referral_dossier(comp, role)
            resp["message"] = f"👥 Referral Radar generated for {comp}! Saved to {Path(dossier['file_path']).name}"

        payload = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


def run_dashboard(host="127.0.0.1", port=8501):
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    print(f"[Web Command Center] Active and live on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8501
    run_dashboard(port=port)
