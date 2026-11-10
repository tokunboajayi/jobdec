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


def test_dynamic_turbo_and_hud_toggle():
    from telegram_bot_service import (
        calculate_dynamic_turbo_workers,
        get_smart_keyboard,
        ACTIVE_HUD_STATE,
    )
    # Test dynamic turbo workers calculation returns reasonable number (2 to 8) and description
    workers, desc = calculate_dynamic_turbo_workers()
    assert 2 <= workers <= 8
    assert "workers auto-tuned" in desc or "workers" in desc

    # Test HUD button toggling label based on active state
    ACTIVE_HUD_STATE["message_id"] = None
    kb_off = get_smart_keyboard()
    hud_btns_off = [btn.text for row in kb_off.inline_keyboard for btn in row if btn.callback_data == "btn_hud"]
    assert len(hud_btns_off) == 1
    assert "Live Dynamic HUD" in hud_btns_off[0]

    ACTIVE_HUD_STATE["message_id"] = 55555
    kb_on = get_smart_keyboard()
    hud_btns_on = [btn.text for row in kb_on.inline_keyboard for btn in row if btn.callback_data == "btn_hud"]
    assert len(hud_btns_on) == 1
    assert "Stop Dynamic HUD" in hud_btns_on[0]

    # Reset
    ACTIVE_HUD_STATE["message_id"] = None


def test_onboarding_wizard_steps_and_keyboard():
    from telegram_bot_service import get_onboarding_step_message, get_smart_keyboard

    # Test all 8 steps generate valid HTML messages and keyboards
    for step in range(1, 9):
        text, kb = get_onboarding_step_message(step)
        assert f"Step {step} of 8" in text
        assert kb is not None
        assert len(kb.inline_keyboard) >= 1

    # Step 1 should contain mission and guardrails
    t1, _ = get_onboarding_step_message(1)
    assert "Cybersecurity" in t1
    assert "Zero Software Engineering" in t1

    # Step 3 should contain candidate identity
    t3, _ = get_onboarding_step_message(3)
    assert "Michael Azuka" in t3
    assert "3.35" in t3
    assert "Security+" in t3

    # Step 6 should contain iMessage Pager details
    t6, _ = get_onboarding_step_message(6)
    assert "iMessage" in t6
    assert "+14046450373" in t6

    # Step 8 should have the final launch button
    t8, kb8 = get_onboarding_step_message(8)
    launch_btns = [btn for row in kb8.inline_keyboard for btn in row if btn.callback_data == "onboard:launch"]
    assert len(launch_btns) == 1
    assert "Launch" in launch_btns[0].text

    # Main dashboard smart keyboard must include [🧭 Setup Wizard]
    kb_main = get_smart_keyboard()
    setup_btns = [btn for row in kb_main.inline_keyboard for btn in row if btn.callback_data == "btn_setup_wizard"]
    assert len(setup_btns) == 1
    assert "Setup Wizard" in setup_btns[0].text


def test_decision_tab_lifecycle_and_auto_disappear():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from telegram_bot_service import (
        open_or_refresh_decision_tab,
        ACTIVE_DECISION_TAB,
        _auto_close_decision_tab_job,
    )

    async def _run():
        ACTIVE_DECISION_TAB["message_id"] = None
        ACTIVE_DECISION_TAB["chat_id"] = None

        # Mock context and bot
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value=MagicMock(message_id=77777))
        bot_mock.edit_message_text = AsyncMock()
        bot_mock.delete_message = AsyncMock(return_value=True)

        job_queue_mock = MagicMock()
        job_queue_mock.get_jobs_by_name = MagicMock(return_value=[])
        job_queue_mock.run_once = MagicMock()

        context_mock = MagicMock()
        context_mock.bot = bot_mock
        context_mock.job_queue = job_queue_mock

        # 1. Open tab
        await open_or_refresh_decision_tab(context_mock, chat_id=12345, is_scan=False)
        assert ACTIVE_DECISION_TAB["message_id"] == 77777
        assert ACTIVE_DECISION_TAB["chat_id"] == 12345
        assert bot_mock.send_message.called
        sent_args = bot_mock.send_message.call_args[1]
        assert "Active for 3 minutes" in sent_args["text"]
        assert "Autonomous Decision & Pipeline Summary" in sent_args["text"]
        assert "🔗" in sent_args["text"] or "URL" in sent_args["text"]
        assert job_queue_mock.run_once.called
        assert job_queue_mock.run_once.call_args[0][1] == 180.0  # 3 minutes

        # 2. Re-open / refresh tab while active: should edit in-place without duplicating
        await open_or_refresh_decision_tab(context_mock, chat_id=12345, is_scan=False)
        assert bot_mock.edit_message_text.called
        assert ACTIVE_DECISION_TAB["message_id"] == 77777

        # 3. Simulate auto-disappear timer expiration
        job_mock = MagicMock()
        job_mock.data = {"chat_id": 12345, "message_id": 77777}
        timer_ctx = MagicMock(bot=bot_mock, job=job_mock)
        await _auto_close_decision_tab_job(timer_ctx)
        assert bot_mock.delete_message.called
        assert ACTIVE_DECISION_TAB["message_id"] is None

    asyncio.run(_run())


def test_single_control_panel_invariant():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from telegram_bot_service import (
        ensure_pinned_live_status,
        save_pinned_status_info,
        load_pinned_status_info,
        PINNED_STATUS_FILE,
    )

    async def _run():
        test_chat = 998877
        existing_panel_id = 445566
        save_pinned_status_info(test_chat, existing_panel_id)

        bot_mock = MagicMock()
        bot_mock.edit_message_text = AsyncMock()
        bot_mock.send_message = AsyncMock(return_value=MagicMock(message_id=99999))
        bot_mock.pin_chat_message = AsyncMock()

        context_mock = MagicMock(bot=bot_mock)

        # 1. Update existing control panel: must edit in-place and NOT send new message
        res_id = await ensure_pinned_live_status(context_mock, chat_id=test_chat, force_repin=False)
        assert res_id == existing_panel_id
        assert bot_mock.edit_message_text.called
        assert not bot_mock.send_message.called  # NEVER duplicate!

        # Cleanup
        if PINNED_STATUS_FILE.exists():
            PINNED_STATUS_FILE.unlink(missing_ok=True)

    asyncio.run(_run())




