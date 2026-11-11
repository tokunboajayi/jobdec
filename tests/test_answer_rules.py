"""Wrong answers that were submitted on 2026-10-28 (Paylocity forms): each label must never get them again."""
import pytest

import ai_responder
import candidate
import fill


def test_address_line_2_never_repeats_street():
    # the street address comes from profile.json, never typed here: this repo is public
    street = fill.rule_for("Address Line 1")["a"]
    assert street and (fill.rule_for("Address Line 2(optional)") or {}).get("a") != street


@pytest.mark.parametrize("label, bad", [
    ("Company Phone Number (required)", "Delta Air Lines"),
    ("Certifications & Awards Earned", "check"),
    ("Have you applied for a job with us before? (required)", "Yes"),
    ("Have you worked with us before? (required)", "Yes"),
    ("Did you Graduate?", "12/10/2027"),
    ("Graduation Year", "2026"),
])
def test_rule_never_gives_the_submitted_wrong_answer(label, bad):
    assert (fill.rule_for(label) or {}).get("a") != bad


def own_school():
    """From the candidate's .env, else their profile's plain 'School' answer - never a name typed here."""
    return candidate.fact("UNIVERSITY") or (fill.rule_for("School") or {}).get("a")


def test_school_type_is_not_the_school_name():
    assert own_school() and (fill.rule_for("School Type") or {}).get("a") != own_school()


def test_real_fields_still_answered():
    assert own_school() and fill.rule_for("School Name (required)")["a"] == own_school()
    assert fill.rule_for("I certify that the information is true")["a"] == "check"
    assert fill.rule_for("Have you worked with us before? (required)")["a"] == "No"


@pytest.mark.parametrize("label", ["Reason for Leaving (required)", "May We Contact for Reference?",
                                   "Are you a current or former member of the military?"])
def test_fallback_does_not_guess(label, monkeypatch):
    monkeypatch.setattr(ai_responder, "save_cache", lambda c: None)
    monkeypatch.setattr(ai_responder, "load_cache", lambda: {})
    monkeypatch.setattr(ai_responder, "call_local_llm", lambda *a, **k: "")
    monkeypatch.setattr(ai_responder, "_FA", None, raising=False)
    assert ai_responder.generate_response(label, company="Acme") in ("", "N/A")
