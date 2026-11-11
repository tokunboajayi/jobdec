"""2026-11-11: typed or spoken apply requests launched fill.py live with no confirmation, and loose matching made
"apply the cover letter fix later" an apply command. A message may only preview; the Apply now tap launches."""
import asyncio

import telegram_bot_service as TB


def test_loose_phrases_are_not_apply_commands():
    assert TB.parse_targeted_apply_intent("apply the cover letter fix later") is None
    assert TB.parse_targeted_apply_intent("target the weekend") is None
    assert TB.parse_targeted_apply_intent("/apply Visa") == "Visa"


def test_typed_apply_previews_and_never_launches(monkeypatch):
    sent = []
    monkeypatch.setattr(TB, "resolve_targeted_company_jobs",
                        lambda q, include_applied=False: [{"company": "Acme", "role": "Data Analyst Intern", "url": "https://acme.com/j/1"}])
    monkeypatch.setattr(TB.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))

    async def fake_reply(target, text, reply_markup=None):
        sent.append((text, reply_markup))
    monkeypatch.setattr(TB, "safe_reply", fake_reply)
    asyncio.run(TB.confirm_targeted_apply(object(), "Acme"))
    text, kb = sent[-1]
    assert "Apply to this job?" in text and "Acme" in text
    assert kb.inline_keyboard[0][0].callback_data == "quick_apply|Acme"


def test_targeted_launch_skips_non_internships(monkeypatch):
    monkeypatch.setattr(TB, "resolve_targeted_company_jobs",
                        lambda q, include_applied=False: [{"company": "Acme", "role": "IT Operations Specialist I", "url": "https://acme.com/j/2"}])
    res = TB.launch_mid_session_targeted_job("Acme", ensure_runner_active=False, dry_run=True)
    assert res["ok"] is False and not res["launched"]
