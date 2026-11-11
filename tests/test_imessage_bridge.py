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
from agents import imessage_bridge
from agents.imessage_bridge import (
    is_imessage_available,
    send_imessage,
    forward_advancement_to_imessage,
    handle_incoming_imessage_command,
    webhook_request_allowed,
)

FAKE_HANDLE = "+15550000000"  # reserved fictional number


@pytest.fixture(autouse=True)
def offline_bridge(tmp_path, monkeypatch):
    """No real handle, no real transport: every send lands in a temp outbox log."""
    monkeypatch.setattr(imessage_bridge, "IMESSAGE_ENABLED", True)
    monkeypatch.setattr(imessage_bridge, "IMESSAGE_TARGET_HANDLE", FAKE_HANDLE)
    monkeypatch.setattr(imessage_bridge, "IMESSAGE_PASSWORD", "")
    monkeypatch.setattr(imessage_bridge, "SENDBLUE_API_KEY", "")
    monkeypatch.setattr(imessage_bridge, "SENDBLUE_API_SECRET", "")
    monkeypatch.setattr(imessage_bridge.sys, "platform", "win32")
    monkeypatch.setattr(imessage_bridge, "OUTBOX_LOG_FILE", tmp_path / "outbox.jsonl")


def test_no_hardcoded_handle():
    src = Path(imessage_bridge.__file__).read_text(encoding="utf-8")
    assert '"IMESSAGE_TARGET_HANDLE", "")' in src


def test_imessage_availability(monkeypatch):
    assert is_imessage_available() is True
    monkeypatch.setattr(imessage_bridge, "IMESSAGE_TARGET_HANDLE", "")
    assert is_imessage_available() is False


def test_imessage_send_and_audit_logging():
    test_msg = "Automated Test Message"
    res = send_imessage(test_msg)
    assert res.get("success") is True
    assert res.get("target") == FAKE_HANDLE

    log = imessage_bridge.OUTBOX_LOG_FILE
    lines = log.read_text(encoding="utf-8").splitlines()
    latest = json.loads(lines[-1])
    assert latest.get("text") == test_msg
    assert latest.get("target") == FAKE_HANDLE


def test_webhook_rejects_rebinding_cross_origin_and_strangers():
    assert webhook_request_allowed("127.0.0.1:5055", "", FAKE_HANDLE)
    assert webhook_request_allowed("localhost:5055", None, FAKE_HANDLE)
    assert not webhook_request_allowed("evil.example:5055", "", FAKE_HANDLE)   # DNS rebinding
    assert not webhook_request_allowed("127.0.0.1:5055", "http://127.0.0.1:9999", FAKE_HANDLE)  # web page POST
    assert not webhook_request_allowed("127.0.0.1:5055", "", "+15551112222")  # anyone else
    assert not webhook_request_allowed("127.0.0.1:5055", "", "")


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

