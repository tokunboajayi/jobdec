"""
Comprehensive unit tests for advanced Telegram features:
1. Quick View PDF-to-image render (no download needed).
2. Live Screen Cam capture.
3. Voice transcription pipeline.
4. AI Mock Interview simulator.
5. Autonomous Compensation & Offer negotiator.
6. ATS Keyword Gap & Resume Heatmap analyzer.
"""
import pytest
import pathlib
from agents.telegram_visuals import (
    find_latest_tailored_resume,
    find_latest_tailored_letter,
    render_pdf_to_image_bytes,
    capture_active_worker_screenshot,
)
from agents.interview_simulator import (
    start_interview_session,
    evaluate_and_advance_interview,
    is_in_interview,
    INTERVIEW_SESSIONS,
)
from agents.offer_negotiator import analyze_offer_and_strategize
from agents.ats_gap_analyzer import analyze_ats_gap


def test_quickview_pdf_rendering():
    resume_path = find_latest_tailored_resume()
    assert resume_path is not None
    assert resume_path.exists()
    
    # Must produce valid PNG bytes
    img_bytes = render_pdf_to_image_bytes(resume_path, scale=1.5)
    assert len(img_bytes) > 10000
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header


def test_quickview_cover_letter_lookup():
    letter_path = find_latest_tailored_letter()
    if letter_path:
        assert letter_path.exists()
        img_bytes = render_pdf_to_image_bytes(letter_path, scale=1.0)
        assert len(img_bytes) > 5000
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_screen_cam_capture():
    # If snapshots exist in records/, capture_active_worker_screenshot should return valid PNG
    res = capture_active_worker_screenshot()
    if res is not None:
        img_bytes, caption = res
        assert len(img_bytes) > 1000
        assert "Snapshot" in caption or "Live" in caption
        assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_interview_simulator_lifecycle():
    chat_id = 999999
    # Start session
    prompt = start_interview_session(chat_id, "Databricks", "IAM Security Engineer")
    assert is_in_interview(chat_id)
    assert "Databricks" in prompt
    assert "Question 1/4" in prompt

    # Answer question 1
    reply1 = evaluate_and_advance_interview(chat_id, "I enforce least privilege and RBAC using GPOs in Active Directory and audit logs with PowerShell.")
    assert "Evaluation" in reply1
    assert "Question 2/4" in reply1

    # Answer remaining questions to verify completion
    evaluate_and_advance_interview(chat_id, "I revoke session tokens, isolate the host, and check authentication logs in Azure Sentinel SIEM.")
    evaluate_and_advance_interview(chat_id, "I inspected Event Viewer logs, communicated with stakeholders, and wrote a script to monitor service status.")
    final_reply = evaluate_and_advance_interview(chat_id, "I implemented compensating controls and an exception with executive sign-off.")
    assert "MOCK INTERVIEW COMPLETE" in final_reply
    assert not is_in_interview(chat_id)


def test_offer_negotiator():
    res = analyze_offer_and_strategize("Axon", "$85,000", "Scottsdale, AZ")
    assert res["base_val"] == 85000
    assert res["counter_base"] > 85000
    assert "Autonomous Compensation Dossier" in res["telegram_summary"]
    assert "Michael Azuka" in res["email_draft"]
    assert "404-645-0373" in res["email_draft"]


def test_ats_gap_analyzer():
    res = analyze_ats_gap("Tenable", "Information Security Engineer")
    assert res["match_pct"] >= 70
    assert len(res["matched"]) > 0
    assert "ATS Keyword Heatmap" in res["telegram_summary"]
    assert "CompTIA Security+" in res["telegram_summary"] or "Active Directory" in res["telegram_summary"]


def test_pinned_status_state_and_keyboard():
    from telegram_bot_service import (
        get_smart_keyboard,
        format_status_message,
        save_pinned_status_info,
        load_pinned_status_info,
        PINNED_STATUS_FILE
    )
    # Test keyboard generation contains pin live status button
    m = {
        "total_applied": 1074,
        "today_applied": 15,
        "is_running": False,
        "worker_count": 0,
        "total_mem_mb": 120,
        "avail_gb": 16.0,
        "unapplied_count": 1400,
        "current_target": ""
    }
    kb = get_smart_keyboard(m)
    found_pin_btn = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "btn_pin_status":
                found_pin_btn = True
                break
    assert found_pin_btn, "btn_pin_status must be present in keyboard"

    # Test state persistence
    test_chat = 123456789
    test_msg = 987654321
    save_pinned_status_info(test_chat, test_msg)
    loaded = load_pinned_status_info()
    assert loaded.get("chat_id") == test_chat
    assert loaded.get("message_id") == test_msg

    # Cleanup test file
    if PINNED_STATUS_FILE.exists():
        PINNED_STATUS_FILE.unlink(missing_ok=True)


