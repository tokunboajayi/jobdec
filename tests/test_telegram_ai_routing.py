"""2026-11-11: the owner's Telegram messages never reached OpenRouter. Keyword shortcuts ran first ("reply", "email",
"next", "today", a company name), AI failures fell back silently, and a Telegram reply to a question was ignored."""
import asyncio
from unittest.mock import MagicMock

import telegram_bot_service as TB
import telegram_query_engine as TQ


def test_messages_with_shortcut_words_reach_the_ai(monkeypatch):
    seen = []
    monkeypatch.setattr(TQ, "ask_ai", lambda t: seen.append(t) or ("answer", None))
    for text in ("draft a reply to the Visa recruiter", "what should I do next today?", "any email from Ramp?"):
        out, _ = TQ.answer_natural_language_query(text)
        assert "Job Deck AI" in out
    assert len(seen) == 3


def test_ai_failure_is_reported_not_hidden(monkeypatch):
    def boom(t):
        raise TQ.AIError("HTTP 401 invalid key")
    monkeypatch.setattr(TQ, "ask_ai", boom)
    monkeypatch.setenv("OPENROUTER_API_KEY", "real-looking-key")
    out, _ = TQ.answer_natural_language_query("did we apply to Visa?")
    assert "AI unavailable" in out and "401" in out


def test_telegram_reply_to_a_question_answers_that_question(monkeypatch):
    saved, sent = [], []
    monkeypatch.setattr(TQ, "load_pending_questions", lambda: [{"id": "q1", "question": "What is your Sex?", "message_id": 383}])
    monkeypatch.setattr(TQ, "resolve_pending_question",
                        lambda qid, a: saved.append((qid, a)) or {"ok": True, "answer": a, "question": "What is your Sex?"})

    async def reply(target, text, reply_markup=None):
        sent.append(text)

    async def noop(*a, **k):
        return True
    monkeypatch.setattr(TB, "safe_reply", reply)
    monkeypatch.setattr(TB, "safe_delete_message", noop)
    u = MagicMock()
    u.effective_user.id = u.effective_chat.id = TB.AUTHORIZED_USER_ID
    u.message.text = "Male"
    u.message.reply_to_message.message_id = 383
    asyncio.run(TB.handle_text(u, MagicMock()))
    assert saved == [("q1", "Male")] and "Saved" in sent[-1]
