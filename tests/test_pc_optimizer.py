import pytest
import os
import psutil
from unittest.mock import patch, MagicMock
import agents.pc_optimizer as pco
from agents.decision_tracker import format_advancement_telegram_alert


def test_pc_optimizer_priority_setting():
    # Test setting priority on current process
    updated = pco.set_process_priority(os.getpid(), priority="below_normal", recursive=False)
    assert updated >= 1
    p = psutil.Process()
    # On Windows, BELOW_NORMAL_PRIORITY_CLASS is 16384
    if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
        assert p.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS


def test_pc_optimizer_trim_memory():
    # Trim current process memory
    reclaimed, count = pco.trim_process_memory(os.getpid(), recursive=False)
    assert count >= 1
    assert reclaimed >= 0.0


def test_pc_optimizer_governor_backoff():
    gov = pco.AdaptiveCPUGovernor()
    # memory is faked too: should_scale_down() reads RAM, and real usage made this flaky
    with patch("psutil.cpu_percent", return_value=30.0), patch("psutil.virtual_memory") as low_mem:
        low_mem.return_value.percent = 50.0
        assert gov.get_throttle_delay() == 0.0
        assert not gov.should_scale_down()

    with patch("psutil.cpu_percent", return_value=78.0):
        assert gov.get_throttle_delay() == 0.10

    with patch("psutil.cpu_percent", return_value=88.0):
        assert gov.get_throttle_delay() == 0.35

    with patch("psutil.cpu_percent", return_value=95.0), \
         patch("psutil.virtual_memory") as mock_mem:
        mock_mem.return_value.percent = 70.0
        assert gov.should_scale_down()


def test_full_system_optimization_executes():
    res = pco.run_full_system_optimization()
    assert res["status"] == "success"
    assert "reclaimed_mb" in res
    assert "zombies_killed" in res
    assert "procs_optimized" in res


def test_advancement_email_link_formatting():
    mock_adv = {
        "company": "CrowdStrike",
        "role": "Cloud Security Specialist",
        "stage": "Interview Screen",
        "action_needed": "Confirm available interview slots",
        "deadline": "Nov 12, 2026",
        "decision_timestamp": "Nov 09, 2026 04:30 PM",
        "email_link": "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Atest12345"
    }
    alert = format_advancement_telegram_alert(mock_adv)
    assert "CrowdStrike" in alert
    assert "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Atest12345" in alert
    assert "Open Message in Gmail" in alert

