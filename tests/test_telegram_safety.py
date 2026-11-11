"""
Safety tests for the Telegram bot + Gemini assistant (REVIEW.md C-1..C-6, L-1..L-5, A-5, A-6, E-5).
Offline: urlopen / send_message are mocked, every file lives in tmp_path.
Hard rule under test: nothing a model or chat produces silently becomes a saved answer.
"""
import io
import json
import re
import urllib.error

import pytest

import candidate
import telegram_notify as TN
import telegram_query_engine as QE

CURATED = [{"q": "curated rule", "a": "curated answer"}]


@pytest.fixture
def eng(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"rules": list(CURATED)}), encoding="utf-8")
    for name, fname in [("PENDING_FILE", "pending.json"), ("QUESTION_TRACKER_FILE", "qmsgs.json"),
                        ("APPLICATION_TRACKER_FILE", "appmsgs.json"), ("HISTORY_FILE", "history.json"),
                        ("PROPOSALS_FILE", "proposals.json"), ("QUEUE_PATH", "queue.txt"),
                        ("NEEDS_YOU_PATH", "needs_you.md")]:
        monkeypatch.setattr(QE, name, tmp_path / fname)
    monkeypatch.setattr(QE, "PROFILE_PATH", profile)
    monkeypatch.setattr(TN, "ASKED_FILE", tmp_path / "asked.json")
    monkeypatch.setattr(TN, "OUTBOX_QUESTIONS", tmp_path / "unanswered.json")
    monkeypatch.setattr(TN, "OUTBOX_STATE", tmp_path / "outbox_state.json")
    monkeypatch.setattr(candidate, "APPLICATIONS", tmp_path / "applications.csv")
    monkeypatch.setattr(QE.time, "sleep", lambda s: None)
    return tmp_path


def rules():
    return json.loads(QE.PROFILE_PATH.read_text(encoding="utf-8"))["rules"]


@pytest.fixture
def sent(monkeypatch):
    """Captures Telegram sends instead of calling the API."""
    out = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def fake_send(text, reply_markup=None, parse_mode="HTML"):
        out.append({"text": text, "reply_markup": reply_markup})
        return 1000 + len(out)
    monkeypatch.setattr(TN, "send_message", fake_send)
    return out


# ---- C-3 / L-3 / E-5: answers bind to an explicit id ----

def test_unknown_id_is_rejected_and_never_falls_back_to_newest(eng):
    QE.add_pending_question("Are you willing to travel?", ["Yes", "No"])
    res = QE.resolve_pending_question("q0000000000", "Yes")
    assert res["ok"] is False
    assert rules() == CURATED
    assert len(QE.load_pending_questions()) == 1
    assert QE.resolve_pending_question("latest", "Yes")["ok"] is False


def test_button_option_index_round_trips(eng):
    item = QE.add_pending_question("Are you willing to travel?", ["Yes", "No"])
    assert QE.resolve_by_option_index(item["id"], "5")["ok"] is False
    assert QE.resolve_by_option_index(item["id"], "x")["ok"] is False
    res = QE.resolve_by_option_index(item["id"], "1")
    assert res["ok"] and res["answer"] == "No"
    assert rules()[-1]["a"] == "No"
    assert QE.load_pending_questions() == []


def test_bare_yes_or_answer_without_id_saves_nothing(eng, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    QE.add_pending_question("Are you willing to travel?", ["Yes", "No"])
    for msg in ("yes", "answer: Yes", "ans: no"):
        QE.answer_natural_language_query(msg)
    assert rules() == CURATED
    assert QE.parse_answer_command("answer: Yes") is None
    assert QE.parse_answer_command("answer qabcdef0123: Yes") == ("qabcdef0123", "Yes")


# ---- C-2 / A-5: escaped, compile-checked, appended, atomic ----

def test_saved_pattern_is_escaped_and_appended(eng):
    item = QE.add_pending_question("Salary expectations (USD", [])
    assert QE.resolve_pending_question(item["id"], "Open")["ok"]
    r = rules()
    assert r[0] == CURATED[0], "never inserted above curated rules"
    assert r[-1]["q"] == re.escape("salary expectations (usd")
    re.compile(r[-1]["q"])
    assert not list(eng.glob("*.tmp")), "atomic write leaves no temp file"


def test_short_or_bad_patterns_rejected(eng):
    assert QE.rule_pattern("ab?") is None
    assert QE.save_rule("a*", "Yes", "telegram_user")["ok"] is False
    assert QE.validate_action({"action": "update_rule", "q": "ab", "a": "x"}) is None
    assert rules() == CURATED


# ---- L-1 / C-1 / L-2 / C-5 / L-5: Gemini proposes, the user confirms ----

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def gemini_reply(text, finish="STOP"):
    return FakeResp(json.dumps({
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
    }).encode("utf-8"))


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    calls = []
    replies = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(QE.urllib.request, "urlopen", fake_urlopen)
    return calls, replies


ACTION_TEXT = ('Sure, I will save that.\n<<<ACTION\n'
               '{"action": "update_rule", "q": "Are you willing to relocate?", "a": "Yes"}\n>>>')


def test_action_is_a_proposal_not_applied_until_confirmed(eng, gemini):
    calls, replies = gemini
    replies.append(gemini_reply(ACTION_TEXT))
    answer, pid = QE.answer_natural_language_query("please set relocate to yes")
    assert pid, "an allowed action becomes a proposal"
    assert rules() == CURATED, "nothing written before the user taps Apply"
    assert "Proposed change (not applied)" in answer and "<<<" not in answer

    req = calls[0]
    assert "key=" not in req.full_url
    assert req.get_header("X-goog-api-key") == "test-key-not-real"
    body = json.loads(req.data)
    assert "<user_message>" in body["contents"][-1]["parts"][0]["text"]

    assert "Saved rule" in QE.apply_proposal(pid)
    assert rules()[-1]["q"] == re.escape("are you willing to relocate")
    assert "unknown or expired" in QE.apply_proposal(pid), "a proposal applies once"


def test_discard_and_unknown_proposals_change_nothing(eng, gemini):
    _, replies = gemini
    replies.append(gemini_reply(ACTION_TEXT))
    _, pid = QE.answer_natural_language_query("set relocate yes")
    assert "discarded" in QE.apply_proposal(pid, confirm=False)
    assert "unknown or expired" in QE.apply_proposal("deadbeef")
    assert rules() == CURATED


@pytest.mark.parametrize("action", [
    {"action": "control_runner", "command": "start"},
    {"action": "update_rule", "q": "relocate question", "a": "Yes", "option": ".*"},
    {"action": "add_queue", "url": "javascript:alert(1)"},
    {"action": "remove_queue", "keyword": "a"},
])
def test_disallowed_actions_are_never_proposed(eng, gemini, action):
    _, replies = gemini
    replies.append(gemini_reply("ok\n<<<ACTION\n" + json.dumps(action) + "\n>>>"))
    answer, pid = QE.answer_natural_language_query("do it")
    assert pid is None
    assert "not allowed" in answer
    assert rules() == CURATED


def test_retry_once_on_429_then_success(eng, gemini):
    calls, replies = gemini
    replies += [urllib.error.HTTPError("u", 429, "busy", {}, None), gemini_reply("Hello")]
    answer, _ = QE.answer_natural_language_query("hello there")
    assert "Hello" in answer and len(calls) == 2


def test_errors_and_blocked_replies_are_reported_honestly(eng, gemini):
    _, replies = gemini
    replies += [gemini_reply("partial", finish="SAFETY")]
    answer, pid = QE.answer_natural_language_query("hello there")
    assert "AI assistant error" in answer and "SAFETY" in answer and pid is None
    replies += [urllib.error.HTTPError("u", 500, "x", {}, None), urllib.error.HTTPError("u", 500, "x", {}, None)]
    answer, _ = QE.answer_natural_language_query("hello again")
    assert "AI assistant error" in answer and "Instruction noted" not in answer


def test_history_capped_and_prompt_has_no_contact_details(eng, gemini, monkeypatch):
    calls, replies = gemini
    monkeypatch.setenv("CANDIDATE_PHONE", "555-0100")
    monkeypatch.setenv("CANDIDATE_ADDRESS_LINE_1", "1 Test Street")
    monkeypatch.setenv("CANDIDATE_FIRST_NAME", "Testy")
    for i in range(6):
        replies.append(gemini_reply(f"reply {i}"))
        QE.answer_natural_language_query(f"message number {i}")
    assert len(QE.load_chat_history()) == QE.HISTORY_TURNS
    sys_text = json.loads(calls[-1].data)["systemInstruction"]["parts"][0]["text"]
    assert "Testy" in sys_text
    assert "555-0100" not in sys_text and "1 Test Street" not in sys_text


# ---- C-6: HTML escaping ----

def test_model_and_page_text_is_html_escaped(eng, sent):
    assert QE.sanitize_for_telegram('<a href="http://x">hi</a> **b**') == '&lt;a href="http://x"&gt;hi&lt;/a&gt; <b>b</b>'
    TN.notify_applied("<script>Evil</script>", "Role & <i>", 'javascript:"alert"')
    text = sent[-1]["text"]
    assert "<script>" not in text and "&lt;script&gt;" in text and "&amp;" in text
    assert "javascript" not in text, "non-http links are dropped"


# ---- A-6 / C-4 / outbox ----

def test_outbox_questions_asked_once_with_id_callbacks_and_no_auto_save(eng, sent):
    q = "What is your gender identity?"  # EEO: must be asked, never auto-saved (C-4)
    entry = {"url": "https://jobs.example.com/1", "questions": [{"label": q, "options": ["Woman", "Man", "Decline"]}]}
    TN.OUTBOX_QUESTIONS.write_text(json.dumps([entry, entry]), encoding="utf-8")
    TN.process_outbox()
    TN.process_outbox()
    assert len(sent) == 1, "same question from many workers/runs is asked once"
    qid = QE.question_id(q)
    cbs = [b["callback_data"] for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
    assert cbs == [f"ans|{qid}|0", f"ans|{qid}|1", f"ans|{qid}|2"]
    assert f"answer {qid}:" in sent[0]["text"]
    assert rules() == CURATED


def test_outbox_announces_only_new_applications(eng, sent):
    path = candidate.APPLICATIONS
    path.write_text("Company,Role,Job URL\nOldCo,Analyst,https://a\n", encoding="utf-8")
    TN.process_outbox()
    assert sent == [], "history is not replayed on first run"
    with open(path, "a", encoding="utf-8") as f:
        f.write("NewCo,Engineer,https://b\n")
    TN.process_outbox()
    assert len(sent) == 1 and "NewCo" in sent[0]["text"]
    TN.process_outbox()
    assert len(sent) == 1


def test_no_hardcoded_identity_in_telegram_code():
    import pathlib
    root = pathlib.Path(QE.__file__).parent
    for name in ("telegram_bot_service.py", "telegram_query_engine.py", "telegram_notify.py",
                 "agents/telegram_visuals.py", "agents/imessage_bridge.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "KNOWN_FACTS_MAP" not in src
        assert not re.search(r"\b(?:\d{3}-\d{3}-\d{4}|\+1\d{10}|\d{5}(?:-\d{4})?\b.*\bGA\b)", src), name
        assert "Antigravity" not in src and "conversation_memory" not in src, name
