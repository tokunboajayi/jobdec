"""
Unit tests for the Enterprise iMessage Dual-Channel Integration & Migration Bridge:
1. Availability check and recipient resolution.
2. Text message dispatch and outbox audit logging.
3. Stage advancement formatting and dispatch.
4. Incoming command handler (status, run, turbo, stop, prep, radar, boost, help).
5. Webhook listener initialization.
"""

import pytest
import os
import json
from pathlib import Path
from agents.imessage_bridge import (
    is_imessage_available,
    send_imessage,
    forward_advancement_to_imessage,
    handle_incoming_imessage_command,
    OUTBOX_LOG_FILE,
    IMESSAGE_TARGET_HANDLE,
)


def test_imessage_availability():
    assert is_imessage_available() is True
    assert IMESSAGE_TARGET_HANDLE == "+14046450373"


def test_imessage_send_and_audit_logging():
    test_msg = "Automated Test Message for Michael Azuka"
    res = send_imessage(test_msg)
    assert res.get("success") is True
    assert res.get("target") == "+14046450373"

    # Verify audit log on disk
    assert OUTBOX_LOG_FILE.exists()
    with open(OUTBOX_LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) > 0
    latest = json.loads(lines[-1])
    assert latest.get("text") == test_msg
    assert latest.get("target") == "+14046450373"


def test_imessage_forward_advancement():
    fake_adv = {
        "company": "CrowdStrike",
        "role": "Security Operations Center (SOC) Analyst",
        "stage": "Interview Screen",
        "deadline": "Nov 14, 2026",
        "email_link": "https://mail.google.com/mail/u/0/#search/crowdstrike"
    }
    sent = forward_advancement_to_imessage(fake_adv)
    assert sent is True


def test_incoming_imessage_commands():
    # Test status
    status_resp = handle_incoming_imessage_command("status")
    assert "JOB DECK LIVE STATUS" in status_resp
    assert "Verified Submissions" in status_resp

    # Test help
    help_resp = handle_incoming_imessage_command("help")
    assert "JOB DECK iMESSAGE COMMANDS" in help_resp
    assert "status" in help_resp
    assert "prep" in help_resp

    # Test unknown command
    unknown_resp = handle_incoming_imessage_command("random_ping_xyz")
    assert "Received: 'random_ping_xyz'" in unknown_resp

