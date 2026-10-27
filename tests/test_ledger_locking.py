import csv, threading

import pytest

import fill
import results_engine as RE
from tools.file_lock import FileLock

APP_COLS = ["ID", "Company", "Role", "Stage", "Date Applied", "Job URL", "Resume Version", "Next Action", "Next Action Date"]


def _write_apps(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=APP_COLS)
        w.writeheader()
        w.writerows(rows)


def _read_apps(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_file_lock_times_out_instead_of_running_unlocked(tmp_path):
    target = tmp_path / "ledger.csv"
    with FileLock(target):
        with pytest.raises(TimeoutError):
            with FileLock(target, timeout=0.3):
                pytest.fail("second lock must not be granted while the first is held")


def test_concurrent_log_applied_keeps_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(fill, "ROOT", tmp_path)
    monkeypatch.setattr(fill, "RE", None)
    _write_apps(tmp_path / "applications.csv", [{"ID": "1", "Company": "Seed", "Role": "Seed Intern", "Stage": "Found"}])

    def apply(i):
        fill.log_applied(f"https://co{i}.com/jobs/{i}", f"Co{i}", f"Role {i}", None)

    threads = [threading.Thread(target=apply, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    rows = _read_apps(tmp_path / "applications.csv")
    assert len(rows) == 9
    assert sorted(r["Company"] for r in rows if r["Stage"] == "Applied") == sorted(f"Co{i}" for i in range(8))
    assert not (tmp_path / "applications.csv.tmp").exists()


def test_log_applied_never_wipes_a_file_it_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fill, "ROOT", tmp_path)
    monkeypatch.setattr(fill, "RE", None)
    path = tmp_path / "applications.csv"
    path.write_text("", encoding="utf-8")
    fill.log_applied("https://a.com/1", "A", "Role", None)
    assert path.read_text(encoding="utf-8") == ""


def test_ledger_update_keeps_rows_and_leaves_no_temp_file(sandbox):
    RE.ledger_add("Acme", "AI Intern", "https://acme.com/jobs/1", "submitted")
    RE.ledger_add("Beta", "PM Intern", "https://beta.com/jobs/2", "not_submitted")

    def mark(rows):
        for r in rows:
            if r["company"] == "Acme":
                r["response"] = "interview"

    RE.ledger_update(mark)
    rows = RE.ledger_rows()
    assert {r["company"]: r["response"] for r in rows} == {"Acme": "interview", "Beta": ""}
    assert not list(sandbox.glob("*.tmp"))


def test_ledger_add_during_update_is_not_lost(sandbox):
    RE.ledger_add("Acme", "AI Intern", "https://acme.com/jobs/1", "submitted")
    adders = [threading.Thread(target=RE.ledger_add, args=(f"Co{i}", "Intern", f"https://co{i}.com/j/{i}", "submitted")) for i in range(5)]
    updater = threading.Thread(target=RE.ledger_update, args=(lambda rows: [r.update(response="x") for r in rows],))
    for t in adders + [updater]:
        t.start()
    for t in adders + [updater]:
        t.join()
    assert len(RE.ledger_rows()) == 6


def test_batch_runner_skips_held_queue_lines(tmp_path):
    import batch_apply_parallel as BAP
    q = tmp_path / "q.txt"
    q.write_text("Acme Data Analyst Intern https://acme.com/jobs/123\n"
                 "Beta PM Intern (AJ OK relocation first) https://beta.com/jobs/9\n", encoding="utf-8")
    jobs = BAP.parse_queue(q)
    assert [j["company"] for j in jobs if not j["hold"]] == ["Acme"]
    assert [j["company"] for j in jobs if j["hold"]] == ["Beta"]
