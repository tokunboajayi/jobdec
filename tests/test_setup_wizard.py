"""
Unit tests for the Job Deck Comprehensive Setup Wizard (setup_wizard.py):
1. Environment and dependencies verification.
2. Candidate profile and strict cybersecurity guardrails.
3. Master resume and tailoring engine verification.
4. Dual-channel notifications check (Telegram + iMessage).
5. Recruiter radar and Gmail credentials check.
6. Zero-lag PC optimizer pre-flight check.
7. Supervisor watchdog launch verification.
"""

import candidate
import fake_candidate
import setup_wizard


def test_setup_wizard_steps(monkeypatch, tmp_path):
    fake_candidate.use(monkeypatch, tmp_path)
    profile_before = candidate.PROFILE.read_bytes() if candidate.PROFILE.exists() else None

    # 1. Python & Dependencies Check
    assert setup_wizard.check_python_and_deps() is True

    # 2. Candidate Profile & Guardrails Verification
    assert setup_wizard.check_or_setup_profile() is True

    # 3. Master Resume Check
    assert setup_wizard.check_resume() is True

    # 4. Dual Channel Notifications
    assert setup_wizard.check_dual_channel_notifications() is True

    # 5. Recruiter Radar & Gmail
    assert setup_wizard.check_recruiter_radar_and_gmail() is True

    # 6. PC Optimizer Check
    assert setup_wizard.check_pc_optimizer() is True

    # 7. Preflight & Finish
    setup_wizard.run_preflight_and_finish()

    # the wizard only reads: it must never rewrite the candidate's profile
    assert (candidate.PROFILE.read_bytes() if candidate.PROFILE.exists() else None) == profile_before


def test_unattended_wizard_never_writes_someone_elses_facts(monkeypatch, tmp_path, capsys):
    for k in ("FULL_NAME", "EMAIL", "PHONE", "UNIVERSITY", "DEGREE", "MAJOR", "GPA"):
        monkeypatch.delenv(f"CANDIDATE_{k}", raising=False)
    monkeypatch.setattr(candidate, "ENV", tmp_path / ".env")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert setup_wizard.check_or_setup_profile() is True
    assert "Candidate facts missing" in capsys.readouterr().out
    assert not (tmp_path / ".env").exists()
