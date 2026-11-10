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

import pytest
import setup_wizard


def test_setup_wizard_steps():
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

