"""2026-11-10: the resume fallback submitted "Carnegie Mellon University" (first option), "Yes" to a campus referral
program and "Yes" to humanoid-robot experience. With no stated fact it must return nothing so the job is skipped."""
from agents.intelligent_resolver import synthesize_from_resume as S


def test_fallback_never_guesses_an_option():
    assert S("If you heard about us from a campus recruiting event, indicate the school", "select",
             ["Carnegie Mellon University", "MIT"]) is None
    assert S("Are you being referred to this role as part of the Campus Referral Program?", "select", ["Yes", "No"]) is None
    assert S("Do you have experience with humanoid robots?", "select", ["Yes", "No"]) is None
    assert S("Have you ever been convicted of a felony?", "select", ["Yes", "No"]) is None


def test_fallback_accepts_terms_and_leaves_file_fields_alone():
    assert S("I Accept", "checkbox", ["I Accept"])["answer"] == "I Accept"
    assert S("Resume/CV*", "text") is None


def test_company_email_labels_only_the_named_role():
    import outcomes
    apps = {k: {"role": r} for k, r in [("a", "Software Engineering Intern, Frontend [NY]"), ("b", "Applied Scientist Intern [NY]"),
                                         ("c", "Software Engineering Intern, Backend [NY]")]}
    assert outcomes.best_role_matches(list(apps), apps, "Ramp: your Applied Scientist Intern assessment") == ["b"]
    assert outcomes.best_role_matches(list(apps), apps, "Ramp: complete your CodeSignal assessment") == []
    assert outcomes.best_role_matches(["a"], apps, "anything") == ["a"]
