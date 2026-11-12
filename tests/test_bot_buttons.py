"""2026-11-11: tapping a panel button showed the command list again. Results edited the pinned panel and the 45s refresh
put the panel back; a second query.answer() raised and sent "That didn't work"; launch_runner blocked the event loop.
Every button must now give its own result, and only menus may change the panel."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import telegram_bot_service as TB

PANEL_ID = 4242


@pytest.fixture
def bot(monkeypatch):
    out = {"replies": [], "edits": [], "launch": [], "halt": 0}

    async def reply(target, text, reply_markup=None):
        out["replies"].append(text)
        m = MagicMock()
        m.edit_text = AsyncMock(side_effect=lambda t, **k: out["replies"].append(t))
        return m

    async def edit(query, text, reply_markup=None):
        out["edits"].append(text)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(TB, "safe_reply", reply)
    monkeypatch.setattr(TB, "safe_edit", edit)
    monkeypatch.setattr(TB, "launch_runner", lambda *a, **k: out["launch"].append(a) or 1)
    monkeypatch.setattr(TB, "halt_runner", lambda: out.__setitem__("halt", out["halt"] + 1) or 2)
    monkeypatch.setattr(TB.psutil, "pid_exists", lambda pid: True)
    real_metrics = TB.get_realtime_metrics  # the live runner must not decide test outcomes
    monkeypatch.setattr(TB, "get_realtime_metrics", lambda: {**real_metrics(), "is_running": False, "worker_count": 0})
    monkeypatch.setattr(TB.asyncio, "sleep", noop)
    monkeypatch.setattr(TB, "ensure_pinned_live_status", noop)
    monkeypatch.setattr(TB, "replenish_queue_action", lambda: 7)
    monkeypatch.setattr(TB, "open_or_refresh_decision_tab", noop)
    monkeypatch.setattr(TB, "reply_with_engine", lambda u, t: reply(None, "engine: " + t))
    TB.save_pinned_status_info(1, PANEL_ID)
    TB.save_settings(workers=3, delay=2.0, autopilot=True)
    return out


def tap(data, message_id=PANEL_ID):
    u = MagicMock()
    q = u.callback_query
    q.data = data
    q.from_user.id = TB.AUTHORIZED_USER_ID
    q.message.message_id = message_id
    q.message.chat_id = 1
    calls = []

    async def answer(*a, **k):  # Telegram rejects a second answer to one tap
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("Query is too old")
    q.answer = answer
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    asyncio.run(TB.handle_callback_query(u, ctx))


@pytest.mark.parametrize("data", ["btn_run", "btn_stop", "btn_recent", "btn_stats", "btn_replenish", "btn_assessments",
                                  "btn_turbo", "btn_start_deck"])
def test_action_buttons_answer_with_their_own_result(bot, data):
    tap(data)
    assert bot["replies"], f"{data} sent nothing"
    assert not bot["edits"], f"{data} rewrote the pinned panel"
    assert not any("Live Control Panel" in r for r in bot["replies"]), f"{data} answered with the panel again"


def test_menus_open_in_place_and_settings_drive_the_runner(bot):
    tap("btn_more")
    assert "More" in bot["edits"][-1]
    tap("set|workers|2")
    tap("set|delay|4.0")
    tap("set|autopilot|off")
    assert TB.load_settings() | {"desired": None} == {"workers": 2, "delay": 4.0, "autopilot": False, "desired": None}
    assert "Settings" in bot["edits"][-1]
    tap("btn_run")
    assert bot["launch"][-1][0] == 2 and bot["launch"][-1][2] == 4.0
    assert "Applying now" in bot["replies"][-1] and "Autopilot: off" in bot["replies"][-1]


def test_runner_death_is_reported_not_hidden(bot, monkeypatch):
    monkeypatch.setattr(TB.psutil, "pid_exists", lambda pid: False)
    tap("btn_run")
    assert "stopped right after starting" in bot["replies"][-1]


def test_sentences_never_start_or_stop_the_runner(bot):
    for text in ("close the tab please", "how do I end this", "what's the status of Visa?", "update my answer later"):
        u = MagicMock()
        u.effective_user.id = u.effective_chat.id = TB.AUTHORIZED_USER_ID
        u.message.text = text
        asyncio.run(TB.handle_text(u, MagicMock()))
    assert bot["halt"] == 0 and not bot["launch"]
    assert all(r.startswith("engine:") for r in bot["replies"])


def test_run_while_running_does_not_restart(bot, monkeypatch):
    real = TB.get_realtime_metrics
    monkeypatch.setattr(TB, "get_realtime_metrics", lambda: {**real(), "is_running": True})
    tap("btn_run")
    assert not bot["launch"] and "Already applying" in bot["replies"][-1]


def test_settings_reject_values_not_offered(bot):
    tap("set|delay|-1")
    tap("set|delay|nan")
    tap("set|workers|99")
    assert TB.load_settings()["delay"] == 2.0 and TB.load_settings()["workers"] == 3


def test_alert_buttons_and_pdf_download_have_handlers(bot, monkeypatch, tmp_path):
    from agents import interview_prep
    monkeypatch.setattr(interview_prep, "generate_interview_battlecard", lambda **k: {"telegram_summary": "card for " + k["company"]})
    tap("prep:Visa")
    assert bot["replies"][-1] == "card for Visa"
    pdf = tmp_path / ("x" * 120) / "Candidate_Resume.pdf"  # real tailored paths are far over Telegram's 64-byte limit
    tok = TB.pdf_token(pdf)
    assert len(f"dl_pdf:{tok}".encode()) <= 64 and TB.PDF_TOKENS[tok] == pdf
