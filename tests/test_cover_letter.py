from agents import cover_letter, llm


def test_body_is_addressed_and_keeps_only_generic_facts():
    gen = cover_letter._gen()
    body = cover_letter.body_for("JohnsHopkinsAppliedPhysicsLaboratory", "AI Intern [Laurel, MD; 21d old]",
                                 "website astro tailwind cloudflare acquisitions research")
    assert "the AI Intern position at Johns Hopkins Applied Physics Laboratory" in body[1]
    assert "21d old" not in " ".join(body)
    assert body[2] == gen.BODY[3]                     # W. A paragraph matches this posting better -> first
    assert sorted(body[2:4]) == sorted(gen.BODY[2:4])  # same experience text, only reordered


def test_scraped_name_falls_back_to_generic_wording():
    gen = cover_letter._gen()
    body = cover_letter.body_for("HpIq", "Intern")
    assert "HpIq" not in " ".join(body) and body[1] == gen.BODY[1]


def test_toggle_off_returns_none(monkeypatch):
    monkeypatch.setattr(llm, "engine", lambda agent: "off")
    assert cover_letter.build("Acme", "Intern", "https://example.com") is None
