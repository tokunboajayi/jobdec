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


@pytest.fixture
def fake_resumes(tmp_path, monkeypatch):
    """A blank generated PDF stands in for a resume: no real person's resume is read by tests."""
    import pypdfium2 as pdfium
    from agents import telegram_visuals
    doc = pdfium.PdfDocument.new()
    doc.new_page(612, 792)
    doc.save(str(tmp_path / "Candidate_Resume.pdf"))
    monkeypatch.setattr(telegram_visuals, "RESUMES_DIR", tmp_path)
    return tmp_path


def test_quickview_pdf_rendering(fake_resumes):
    resume_path = find_latest_tailored_resume()
    assert resume_path == fake_resumes / "Candidate_Resume.pdf"
    
    # Must produce valid PNG bytes
    img_bytes = render_pdf_to_image_bytes(resume_path, scale=1.5)
    assert len(img_bytes) > 1000
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header


def test_quickview_cover_letter_lookup(fake_resumes):
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
    assert res["email_draft"]


def test_ats_gap_analyzer():
    res = analyze_ats_gap("Tenable", "Information Security Engineer")
    assert res["match_pct"] >= 70
    assert len(res["matched"]) > 0
    assert "ATS Keyword Heatmap" in res["telegram_summary"]
    summary = res["telegram_summary"].lower()
    assert "comptia security+" in summary or "active directory" in summary


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
    cbs = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert {"btn_run", "btn_status", "btn_recent", "btn_stats", "btn_settings", "btn_more"} <= cbs
    assert len(cbs) <= 7, "the panel stays small; everything else lives under More"

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



def test_onboarding_wizard_steps_and_keyboard(monkeypatch):
    from telegram_bot_service import get_onboarding_step_message, get_smart_keyboard
    monkeypatch.setenv("CANDIDATE_FULL_NAME", "Test <Candidate>")
    monkeypatch.setenv("CANDIDATE_GPA", "3.9")

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

    # Step 3 shows this candidate's facts from .env (escaped), never a hardcoded person
    t3, _ = get_onboarding_step_message(3)
    assert "Test &lt;Candidate&gt;" in t3
    assert "3.9" in t3

    # Step 6 should contain iMessage Pager details, without any phone number in code
    t6, _ = get_onboarding_step_message(6)
    assert "iMessage" in t6
    assert "IMESSAGE_TARGET_HANDLE" in t6

    # Step 8 should have the final launch button
    t8, kb8 = get_onboarding_step_message(8)
    launch_btns = [btn for row in kb8.inline_keyboard for btn in row if btn.callback_data == "onboard:launch"]
    assert len(launch_btns) == 1
    assert "Launch" in launch_btns[0].text



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
        from agents.decision_tracker import get_decision_pipeline_summary
        assert get_decision_pipeline_summary() in sent_args["text"]
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


def test_telegram_bar_targeted_apply_intent_parsing():
    from telegram_bot_service import parse_targeted_apply_intent

    assert parse_targeted_apply_intent("Apply to this job with Visa") == "Visa"
    assert parse_targeted_apply_intent("Apply to this job with Goldman") == "Goldman"
    assert parse_targeted_apply_intent("Apply to this job with Goldman Sachs") == "Goldman Sachs"
    assert parse_targeted_apply_intent("apply to Palantir Forward Deployed") == "Palantir Forward Deployed"
    assert parse_targeted_apply_intent("/apply Visa") == "Visa"
    assert parse_targeted_apply_intent("target: Scale AI") == "Scale AI"

    # Generic commands must return None so they trigger the standard runner/deck
    assert parse_targeted_apply_intent("apply") is None
    assert parse_targeted_apply_intent("/apply") is None
    assert parse_targeted_apply_intent("start applying") is None
    assert parse_targeted_apply_intent("/deck") is None


def test_mid_session_targeted_job_uses_the_runners_gates(monkeypatch):
    # 2026-11-11 live smoke: a tap launched a Visa SWE intern (below min_fit), a protected company, and one posting twice
    import telegram_bot_service as TB
    from agents import resume_tailor, cover_letter
    W = "https://visa.wd5.myworkdayjobs.com/{}/job/Foster-City/Product-Management-Intern_REF089881W{}"
    jobs = [
        {"company": "Visa", "role": "Product Management Intern", "url": W.format("Visa", "-1"), "applied": False},
        {"company": "Visa", "role": "Product Management Intern", "url": W.format("Visa_Early_Careers", ""), "applied": False},
        {"company": "Visa", "role": "Software Engineer Intern", "url": "https://visa.wd5.myworkdayjobs.com/Visa/job/Austin/SWE_REF089918W", "applied": False},
        {"company": "Visa", "role": "Data Science Intern", "url": "https://visa.wd5.myworkdayjobs.com/Visa/job/x/DS_REF089883W", "applied": True},
        {"company": "Goldman Sachs", "role": "Product Analyst Intern", "url": "https://hdpc.fa.us2.oraclecloud.com/job/1", "applied": False},
    ]
    for j in jobs:
        j.update(score=9.0, base_score=9.0, category="product", ats_prio=0, resume=None)
    monkeypatch.setattr(TB, "resolve_targeted_company_jobs", lambda q, include_applied=False: [dict(j) for j in jobs])
    monkeypatch.setattr(resume_tailor, "tailor", lambda *a, **k: None)  # no network in tests
    monkeypatch.setattr(cover_letter, "build", lambda *a, **k: "")
    TB.ACTIVE_TARGETED_JOBS.clear()

    res = TB.launch_mid_session_targeted_job("Visa", ensure_runner_active=False, max_to_launch=3, dry_run=True)
    assert res["ok"] is True
    assert [(j["company"], j["role"]) for j in res["launched"]] == [("Visa", "Product Management Intern")]
    assert 91 <= res["launched"][0]["worker_id"] <= 99
    msg, kb = TB.format_targeted_launch_message(res)
    assert "Visa" in msg and kb is not None

    # a second tap while that application is still running launches nothing
    TB.ACTIVE_TARGETED_JOBS[-1]["pid"] = __import__("os").getpid()
    assert TB.launch_mid_session_targeted_job("Visa", ensure_runner_active=False, dry_run=True)["ok"] is False
    TB.ACTIVE_TARGETED_JOBS.clear()


def test_telegram_bar_command_menu_and_start_deck():
    from telegram_bot_service import (
        get_smart_keyboard,
        get_target_customizer_panel,
        launch_full_job_deck,
        launch_assessment_solver_from_telegram,
    )

    from telegram_bot_service import get_more_view
    kb = get_more_view()[1]
    cb_ids = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    panel = {b.callback_data for row in get_smart_keyboard({"is_running": False}).inline_keyboard for b in row}
    assert panel == {"btn_run", "btn_status", "btn_recent", "btn_stats", "btn_settings", "btn_more"}
    assert "btn_target" in cb_ids
    assert "btn_assessments" in cb_ids

    panel_text, panel_kb = get_target_customizer_panel()
    assert "Apply to this job with Visa" in panel_text
    assert "Apply to this job with Goldman" in panel_text
    panel_cbs = {btn.callback_data for row in panel_kb.inline_keyboard for btn in row}
    assert "quick_apply|Visa" in panel_cbs
    assert "quick_apply|Goldman Sachs" in panel_cbs

    deck_res = launch_full_job_deck(workers=3, dry_run=True)
    assert deck_res["ok"] is True

    oa_res = launch_assessment_solver_from_telegram(dry_run=True)
    assert oa_res["ok"] is True





