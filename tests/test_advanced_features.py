"""
Unit & Integration Tests for Advanced Job Deck Features:
1. Pre-Flight ATS Score Simulator & Keyword Optimizer
2. Interview Battlecard & Prep Dossier Generator
3. Warm Referral Radar & Recruiter Outreach
4. Vision-Assisted Self-Healing Page Solver
5. Real-Time Dark-Mode Web Command Center
"""
import json
import os
import re
import urllib.request
import threading
import time
from pathlib import Path
import pytest

from agents import ats_optimizer, interview_prep, referral_radar, vision_solver, context
import web_dashboard


class TestAdvancedFeatures:
    def test_ats_score_optimizer(self):
        jd_iam = (
            "We are seeking an Identity and Access Management Engineer with experience in "
            "Active Directory, Entra ID, Azure AD, Group Policy (GPO), PowerShell scripting, and RBAC."
        )
        res_text = context.resume_text()
        ats_results = ats_optimizer.calculate_ats_match_score(res_text, jd_iam)
        
        assert ats_results["score"] >= 80.0, f"Expected ATS score >= 80%, got {ats_results['score']}"
        assert ats_results["match_tier"] in ("STRONG", "OPTIMAL")
        assert len(ats_results["matched_keywords"]) > 0
        assert "active directory" in ats_results["matched_keywords"]
        assert "powershell" in ats_results["matched_keywords"]

    def test_interview_battlecard_generator(self, tmp_path):
        dossier = interview_prep.generate_interview_battlecard(
            company="Okta",
            role="Identity Management Operations Engineer",
            jd_text="Requires Active Directory administration, user provisioning workflows, and PowerShell."
        )
        assert dossier["company"] == "Okta"
        assert dossier["domain"] == "iam"
        assert Path(dossier["file_path"]).exists()

        content = dossier["content"]
        assert "Michael Azuka" in content
        assert "CompTIA Security+" in content
        assert "Active Directory & Identity Lifecycle Automation" in content
        assert "Situation:" in content
        assert "Action:" in content
        assert "Result:" in content
        assert "5 Sharp Reverse-Questions" in content

        # Check zero-hallucination numbers in candidate's STAR story
        star_section = content.split("## 🌟 Primary STAR Model Story")[1].split("## ❓ Top Predicted")[0]
        unsupported = context.unsupported_numbers(star_section)
        assert len(unsupported) == 0, f"Found unsupported numbers in battlecard STAR story: {unsupported}"

    def test_referral_radar_and_character_budget(self, tmp_path):
        dossier = referral_radar.build_referral_dossier(
            company="CrowdStrike",
            role="Security Operations Incident Response Analyst"
        )
        assert dossier["company"] == "CrowdStrike"
        assert "linkedin.com/search/results/people" in dossier["lead_url"]
        assert "linkedin.com/search/results/people" in dossier["alumni_url"]
        
        # Verify strict LinkedIn 300 character limit on all connection notes
        assert len(dossier["alumni_note"]) <= 300, f"Alumni note exceeds 300 chars: {len(dossier['alumni_note'])}"
        assert len(dossier["lead_note"]) <= 300, f"Lead note exceeds 300 chars: {len(dossier['lead_note'])}"
        assert Path(dossier["file_path"]).exists()

    def test_vision_solver_regex_matching(self):
        valid_buttons = [
            "Submit Application",
            "Submit",
            "Review and Submit",
            "Save and Continue",
            "Next Step",
            "Continue",
            "Apply Now",
            "I Accept",
        ]
        invalid_buttons = [
            "Cancel",
            "Go Back",
            "Delete Account",
            "Terms of Service Link",
            "Read More"
        ]
        for btn in valid_buttons:
            assert vision_solver.VISUAL_BUTTON_TARGETS.search(btn) is not None, f"Failed to match valid action button: {btn}"
        for btn in invalid_buttons:
            assert vision_solver.VISUAL_BUTTON_TARGETS.search(btn) is None, f"Incorrectly matched invalid action button: {btn}"

    def test_web_dashboard_server(self):
        # Start server on ephemeral port for integration testing
        test_port = 8599
        server = web_dashboard.ThreadingHTTPServer(("127.0.0.1", test_port), web_dashboard.DashboardRequestHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.5)

        try:
            # 1. Test GET / (HTML Dashboard)
            req = urllib.request.Request(f"http://127.0.0.1:{test_port}/")
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
                assert "Executive Operations Center" in body
                assert "TOTAL SUBMISSIONS" in body

            # 2. Test GET /api/metrics
            req_m = urllib.request.Request(f"http://127.0.0.1:{test_port}/api/metrics")
            with urllib.request.urlopen(req_m, timeout=10) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert "total_applied" in data
                assert "worker_count" in data

            # 3. Test POST /api/action/clean
            req_c = urllib.request.Request(
                f"http://127.0.0.1:{test_port}/api/action/clean",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req_c, timeout=10) as resp:
                assert resp.status == 200
                res = json.loads(resp.read().decode("utf-8"))
                assert res.get("ok") is True
        finally:
            server.shutdown()
            server.server_close()
