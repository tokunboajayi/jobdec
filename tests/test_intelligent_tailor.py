"""
Unit & Integration Tests for Intelligent Resume & Cover Letter Tailor & Learning Engine.
Tests domain classification, dynamic bullet ranking, skills prioritization,
strict 1-page PDF layout constraints, zero-hallucination guarantees, and adaptive outcome learning.
"""
import copy
import os
import shutil
import tempfile
from pathlib import Path
import pytest
import pypdf

from agents import intelligent_tailor, context
from agents.tailor_learning import TailorLearningEngine, get_learning_engine
import resumes.resume_gen as resume_gen


class TestIntelligentTailor:
    def test_domain_classification(self):
        cases = [
            ("Okta", "Senior IAM Engineer", "Experience with Active Directory, Okta, SCIM, and SAML.", "iam"),
            ("CrowdStrike", "SOC Analyst - Tier 2", "Experience with SIEM, Sentinel, incident triage, and MITRE.", "soc_analyst"),
            ("Intuit", "IT Desktop Support Specialist", "Hands-on POS troubleshooting, hardware repair, and software configuration.", "it_support"),
            ("Datadog", "Cloud Infrastructure Systems Engineer", "Linux administration, VMware, Azure, PowerShell, Bash.", "cloud_sec_sysadmin"),
            ("Palo Alto", "Network Security Defense Analyst", "Firewall inspection, Wireshark packet capture, IDS/IPS.", "network_sec"),
        ]
        for comp, role, jd, expected_domain in cases:
            analysis = intelligent_tailor.analyze_job(comp, role, jd)
            assert analysis["domain"] == expected_domain, f"Failed domain classification for {comp} {role}: got {analysis['domain']}, expected {expected_domain}"
            assert analysis["company_clean"] != ""
            assert analysis["role_clean"] != ""

    def test_master_resume_render_one_page(self, tmp_path):
        out_pdf = tmp_path / "test_master_resume.pdf"
        bottom = resume_gen.render(resume_gen.MASTER, str(out_pdf))
        assert out_pdf.exists()
        assert bottom > 36.0, "Resume bottom margin must indicate single page fit"

        reader = pypdf.PdfReader(str(out_pdf))
        assert len(reader.pages) == 1, f"Expected 1 page, got {len(reader.pages)}"
        text = reader.pages[0].extract_text()
        assert "Michael Azuka" in text
        assert "Kennesaw State University" in text
        assert "CompTIA" in text
        assert "Wolters Kluwer" in text
        assert "Castles Technology" in text

    def test_tailored_resume_generation_and_page_budget(self, tmp_path):
        # Test tailoring for an IAM role
        r_iam = intelligent_tailor.tailor_resume(
            company="PingIdentity",
            role="Identity Management Engineer",
            url="https://example.com/job/123",
            default_resume=None
        )
        assert Path(r_iam).exists()
        reader = pypdf.PdfReader(r_iam)
        assert len(reader.pages) == 1, "Tailored IAM resume must fit on 1 page"

        # Verify plan was saved
        plan_file = Path(r_iam).parent / "resume_plan.txt"
        assert plan_file.exists()
        plan_content = plan_file.read_text(encoding="utf-8")
        assert "Domain: iam" in plan_content

        # Test tailoring for a SOC Analyst role
        r_soc = intelligent_tailor.tailor_resume(
            company="SentinelOne",
            role="SOC Incident Response Analyst",
            url="https://example.com/job/456",
            default_resume=None
        )
        assert Path(r_soc).exists()
        reader_soc = pypdf.PdfReader(r_soc)
        assert len(reader_soc.pages) == 1, "Tailored SOC resume must fit on 1 page"

    def test_cover_letter_generation_and_invariants(self, tmp_path):
        c_path = intelligent_tailor.create_cover_letter(
            company="AbnormalSecurity",
            role="Security Operations Analyst [Remote, USA]",
            url="https://example.com/job/789",
            jd_text="Analyze phishing alerts, investigate threat patterns using SIEM, and map to MITRE ATT&CK."
        )
        assert Path(c_path).exists()
        reader = pypdf.PdfReader(c_path)
        assert len(reader.pages) == 1, "Cover letter must fit on 1 page"

        text = reader.pages[0].extract_text()
        assert "Michael Azuka" in text
        assert "Abnormal Security" in text
        assert "Security Operations Analyst" in text
        assert "Kennesaw State University" in text
        assert "CompTIA Security+" in text

        # Check banned buzzwords
        assert not intelligent_tailor.BANNED_WORDS.search(text), "Cover letter contains banned buzzwords"

        # Check numbers are supported
        unsupported = context.unsupported_numbers(text)
        assert len(unsupported) == 0, f"Found unsupported numbers in cover letter: {unsupported}"

    def test_learning_engine_adaptation(self, tmp_path):
        test_file = tmp_path / "test_learning.json"
        engine = TailorLearningEngine(filepath=test_file)

        # Baseline weight for 'okta' in 'iam'
        w0 = engine.get_domain_weights("iam").get("okta", 2.0)

        # Record application
        engine.record_application(
            company="Okta",
            role="Identity Engineer",
            domain="iam",
            keywords=["okta", "active directory", "gpo"],
            bullet_indices={"Wolters Kluwer, Tax & Accounting North America": [0, 1, 2]},
            skill_order=["Identity & Access", "Technical", "Security", "Operations"]
        )

        w1 = engine.get_domain_weights("iam")["okta"]
        assert w1 > w0, "Weight should increase after recording application"

        # Record interview callback outcome (+4.0 reward)
        ok = engine.record_outcome("Okta", "Identity Engineer", "interview")
        assert ok is True

        w2 = engine.get_domain_weights("iam")["okta"]
        assert w2 > w1, "Weight must jump significantly on interview outcome"

        # Verify bullet boost
        boost = engine.get_bullet_boost("Wolters Kluwer, Tax & Accounting North America", 0)
        assert boost > 0.0, "Bullet performance boost should be positive following interview"

        # Verify persistent save and reload
        engine_reloaded = TailorLearningEngine(filepath=test_file)
        assert engine_reloaded.get_domain_weights("iam")["okta"] == w2
        assert engine_reloaded.state["domain_stats"]["iam"]["interviews"] == 1
