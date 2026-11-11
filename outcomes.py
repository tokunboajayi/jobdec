"""
Measure what actually works: scan Gmail for replies to each application and report response rates
by role category and by channel (auto-applied vs manual).

    python outcomes.py                 # scan since 2026-09-01, update results.csv, write outcomes_report.md
    python outcomes.py --since 2026-10-01

Reads mail only (BODY.PEEK - nothing is marked read). Does not change applications.csv.
Classification (furthest stage wins): interview > assessment > rejection > confirmation.
"""
import argparse, collections, csv, datetime, email, email.utils, pathlib, re, sys
import results_engine as RE

HERE = pathlib.Path(__file__).resolve().parent
import candidate as CAND  # noqa: E402  # whose files these are (JOBDEC_HOME), see candidate.py
ROOT = HERE.parent
REPORT = CAND.DATA / "outcomes_report.md"

CONFIRM_SUBJ_RE = re.compile(
    r"thank(s| you)( so much)? for (applying|your application|your interest)|"
    r"application (was |has been )?received|we('ve| have) received your application|"
    r"application .*is (in|on its way)|application confirmation|your submission for|application complete",
    re.I,
)
INTERVIEW_PAT = (
    r"interview (invitation|invite|request|confirmation|reminder|schedule)|"
    r"invite[ds]? (you )?to (an? |our |your )?(phone |video |virtual |first[- ]round |technical |final )?interview|"
    r"selected (you )?for an? interview|"
    r"schedule (a|your|an) (interview|call|time|conversation|chat|phone screen)|"
    r"phone (screen|interview)|meet with (our|the) (team|hiring manager)|"
    r"availability for (a|an|your) (call|chat|interview|phone screen|conversation)|\bsuperday\b"
)
ASSESSMENT_PAT = (
    r"(invite[ds]? (you )?to|invitation to|complete (the|your|an)|take (the|your|an)|"
    r"action required.{0,40}|next step.{0,40}|reminder.{0,40})\b(online |pre-interview |coding |skills |technical )?assessment\b|"
    r"pre-interview assessment|online assessment|hirevue|codility|hackerrank|codesignal|"
    r"online test|coding challenge|pymetrics|video interview invitation"
)
KINDS = [  # (stage, rank, pattern) - rejection checked before interview/assessment so rejections mentioning them aren't misread
    ("rejection", 2, r"unfortunately|not (be )?moving forward|other candidates|no longer (being )?considered|"
                     r"position has been filled|decided to pursue|will not be proceeding|regret to inform"),
    ("assessment", 3, ASSESSMENT_PAT),
    ("interview", 4, INTERVIEW_PAT),
    ("confirmation", 1, r"thank(s| you)( so much)? for (applying|your application|your interest)|application (was |has been )?received|"
                        r"we('ve| have) received your application|application .*is (in|on its way)|application confirmation|your submission for"),
]
RANK = {k: r for k, r, _ in KINDS}
RANK["offer"] = 5

SKIP_STAGES = {
    "Found", "Scored", "Tailored", "Skipped (low fit)", "Needs decision",
    "Withdrawn", "Started (incomplete)", "Background check complete", "Submitted? (BAD DATA - verify)",
}


def classify(text, subject=""):
    if subject and CONFIRM_SUBJ_RE.search(subject) and not re.search(ASSESSMENT_PAT, subject, re.I) and not re.search(INTERVIEW_PAT, subject, re.I):
        return "confirmation"
    for kind, _, pat in KINDS:
        if re.search(pat, text, re.I):
            return kind
    return None


def _tracker_stage(st):
    st = (st or "").lower()
    if "offer" in st:
        return "offer"
    if "interview" in st:
        return "interview"
    if re.search(r"\boa\b|assessment", st):
        return "assessment"
    if "reject" in st:
        return "rejection"
    return "submitted"


def company_tokens(company):
    """'TheFederalReserveSystem' -> {'thefederalreservesystem', 'federalreserve'}; 'Arc Boat Company' -> {'arcboat', ...}"""
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+|\d+", company or "")
    words = [w.lower() for w in words if w.lower() not in ("the", "inc", "llc", "company", "corp", "group", "co", "and")]
    toks = {RE.norm(company)}
    if words:
        toks.add("".join(words))
        toks.add("".join(words[:2]))
    return {t for t in toks if len(t) >= 4}


def load_applications():
    """Every submitted application, auto (results.csv) or manual (applications.csv), labeled from the tracker."""
    apps = {}
    for r in RE.ledger_rows():
        if r["status"] == "submitted":
            k = RE.job_key(r["company"], r["role"], r["url"])
            apps[k] = {"company": r["company"], "role": r["role"], "url": r["url"], "date": r["date"],
                       "channel": "auto", "category": r["category"], "stage": "submitted", "stage_date": ""}
    p = CAND.APPLICATIONS
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                has_outcome = re.search(r"reject|interview|offer|\boa\b|assessment", r.get("Stage", ""), re.I)
                if (not r.get("Date Applied") and not has_outcome) or r.get("Stage") in SKIP_STAGES:
                    continue
                k = RE.job_key(r["Company"], r["Role"], r.get("Job URL", ""))
                stage = _tracker_stage(r.get("Stage", ""))
                m_dt = re.search(r"\d{4}-\d{2}-\d{2}", (r.get("Decision Date") or "") + " " + (r.get("Date Applied") or ""))
                app_date = m_dt.group(0) if m_dt else ""
                stage_date = app_date if stage != "submitted" else ""
                if k in apps:
                    if RANK.get(stage, 0) > RANK.get(apps[k]["stage"], 0):
                        apps[k]["stage"] = stage
                        apps[k]["stage_date"] = stage_date or apps[k]["date"]
                    continue
                cat, _ = RE.classify_role(r["Role"], r.get("Job URL", ""), r["Company"])
                # rows logged by fill.py on/after 2026-10-13 with no ledger entry were auto runs before the ledger existed
                auto = (app_date >= "2026-10-13" and "by AJ" not in r.get("Date Applied", "")
                        and (r.get("Resume Version", "").endswith(".pdf")))
                apps[k] = {"company": r["Company"], "role": r["Role"], "url": r.get("Job URL", ""),
                           "date": app_date, "channel": "auto" if auto else "manual",
                           "category": cat, "stage": stage, "stage_date": stage_date}
    return apps


def scan_gmail(apps, since):
    from gmail_auth import get_imap_client, decode_str, extract_body
    mail, err = get_imap_client()
    if not mail:
        sys.exit(f"Gmail not available: {err}")
    mail.select("INBOX", readonly=True)
    _, data = mail.uid("search", None, f"(SINCE {since.strftime('%d-%b-%Y')})")  # type: ignore
    uids = data[0].split() if data and data[0] else []
    print(f"Scanning {len(uids)} emails since {since}...")
    index = [(k, company_tokens(a["company"])) for k, a in apps.items()]
    hits = 0
    for i in range(0, len(uids), 200):
        chunk = ",".join(u.decode() for u in uids[i:i + 200])
        _, rows = mail.uid("fetch", chunk, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        for row in rows:
            if not isinstance(row, tuple):
                continue
            m = re.search(rb"UID (\d+)", row[0])
            if not m:
                continue
            uid = m.group(1).decode()
            hdr = email.message_from_bytes(row[1])
            head = f"{decode_str(hdr.get('From', ''))} {decode_str(hdr.get('Subject', ''))}"
            hn = RE.norm(head)
            matched = [k for k, toks in index if any(t in hn for t in toks)]
            if not matched:
                continue
            _, body = mail.uid("fetch", uid, "(BODY.PEEK[])")
            msg = email.message_from_bytes(body[0][1]) if body and isinstance(body[0], tuple) else hdr
            body_text = re.sub(r"<[^>]+>", " ", extract_body(msg))
            text = head + " " + body_text[:6000]
            try:
                date_val = hdr.get("Date")
                when = email.utils.parsedate_to_datetime(date_val).date().isoformat() if date_val else ""
            except Exception:
                when = ""
            kind = None
            try:  # Agent 5 reads the email; keyword rules are the fallback
                from agents import inbox_analyst
                ai = inbox_analyst.read(uid, decode_str(hdr.get("From", "")), decode_str(hdr.get("Subject", "")), body_text, when)
                if ai is not None:
                    kind = ai["kind"] if ai["is_about_application"] and ai["kind"] in RANK else None
                    if not kind:
                        continue
            except Exception:
                ai = None
            kind = kind or classify(text, decode_str(hdr.get("Subject", "")))
            if not kind:
                continue
            for k in matched:
                a = apps[k]
                if when and a["date"] and when < a["date"]:
                    continue  # email predates this application
                if RANK[kind] > RANK.get(a["stage"], 0):
                    a["stage"], a["stage_date"] = kind, when
                    hits += 1
    mail.logout()
    return hits


def report(apps):
    groups = collections.defaultdict(lambda: collections.Counter())
    for a in apps.values():
        for key in (("ALL", "all"), (a["channel"], "all"), (a["channel"], a["category"])):
            c = groups[key]
            c["applied"] += 1
            c[a["stage"]] += 1
    lines = [f"# Application outcomes - {datetime.date.today().isoformat()}", "",
             "Response = rejection, assessment or interview (a confirmation email alone doesn't count).", "",
             "| channel | category | applied | responses | assessment | interview | rejected | response rate | interview rate |",
             "|---|---|---|---|---|---|---|---|---|"]
    for (ch, cat), c in sorted(groups.items(), key=lambda x: (x[0][0] != "ALL", x[0][0], x[0][1] != "all", x[0][1])):
        resp = c["rejection"] + c["assessment"] + c["interview"] + c["offer"]
        n = c["applied"]
        lines.append(f"| {ch} | {cat} | {n} | {resp} | {c['assessment']} | {c['interview']} | {c['rejection']} | "
                     f"{resp / n:.0%} | {(c['interview'] + c['offer']) / n:.0%} |")
    lines += ["", "## Positive signals (assessment / interview)", ""]
    pos = [a for a in apps.values() if a["stage"] in ("assessment", "interview", "offer")]
    lines += [f"- {a['stage_date']} **{a['stage']}**: {a['company']} - {a['role']} ({a['channel']}, {a['category']})" for a in pos] or ["- none yet"]
    lines += ["", "Judge after 2-3 weeks: compare auto vs manual and categories. Shift the queue toward what gets interviews",
              "(edit category_weights / min_fit_score in strategy.json)."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[4:4 + 2 + len(groups)]))
    print(f"\nWrote {REPORT.name}")


def update_ledger(apps):
    def mark(rows):
        for r in rows:
            if r.get("status") != "submitted":
                r["response"], r["response_date"] = "", ""
                continue
            a = apps.get(RE.job_key(r["company"], r["role"], r["url"]))
            if a and a["stage"] != "submitted":
                r["response"], r["response_date"] = a["stage"], a["stage_date"]
            else:
                r["response"], r["response_date"] = "", ""
    RE.ledger_update(mark)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--no-gmail", action="store_true", help="report from current data only")
    a = ap.parse_args()
    apps = load_applications()
    print(f"{len(apps)} submitted applications ({sum(1 for x in apps.values() if x['channel'] == 'auto')} auto)")
    if not a.no_gmail:
        n = scan_gmail(apps, datetime.date.fromisoformat(a.since))
        print(f"{n} status updates found")
    update_ledger(apps)
    report(apps)
    try:
        from agents import smarts
        print(smarts.learner_train())
    except Exception:
        pass


if __name__ == "__main__":
    main()
