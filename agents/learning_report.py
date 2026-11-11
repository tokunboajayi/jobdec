"""Learning from failures (LEARNING_DESIGN.md loops 1 and 2): a read-only report, nothing is auto-tuned.

Loop 1 - why applications did not submit: record status and unanswered questions by ATS.
Loop 2 - what gets a reply: Beta-Binomial reply rate per category / ATS with a 90% range, internships only.
Run: python -m agents.learning_report   ->  learning_report.md
"""
import collections
import glob
import json
import re

import candidate as C
import results_engine as RE

POSITIVE = ("assessment", "interview", "offer")


def beta_range(k, n, a=1, b=1):
    """Mean and 90% range of a Beta(a+k, b+n-k) posterior, by sampling (stdlib only)."""
    import random
    rnd = random.Random(0)
    xs = sorted(rnd.betavariate(a + k, b + n - k) for _ in range(2000))
    return (a + k) / (a + b + n), xs[100], xs[1899]


def build():
    lines = ["# Learning report", ""]
    # Loop 1: process failures
    status, by_ats, questions = collections.Counter(), collections.defaultdict(collections.Counter), collections.Counter()
    by_hand = {}  # CAPTCHA-walled jobs: never solved by the pipeline, so the candidate applies to these
    for f in glob.glob(str(RE.RECORDS_DIR / "*" / "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        st = d.get("status", "?")
        status[st] += 1
        by_ats[RE.ats_of(d.get("url", ""))[0]][st] += 1
        for q in d.get("unanswered_questions") or []:
            questions[re.sub(r"\s+", " ", str(q))[:90]] += 1
        if st == "captcha":
            by_hand[d.get("url", "")] = (d.get("when", "")[:10], d.get("company", ""), d.get("role", ""))
    lines += ["## Why applications did not submit", "", "| ATS | attempts | submitted | submit rate | top failure |", "|---|---|---|---|---|"]
    for ats, c in sorted(by_ats.items(), key=lambda kv: -sum(kv[1].values()))[:12]:
        n = sum(c.values())
        fail = next((k for k, _ in c.most_common() if k != "submitted"), "-")
        lines.append(f"| {ats} | {n} | {c['submitted']} | {c['submitted'] / n:.0%} | {fail} |")
    lines += ["", "**Questions that blocked the most jobs** (answer once with a profile.json rule, or approve in Telegram):", ""]
    lines += [f"- {n}x {q}" for q, n in questions.most_common(15)] or ["- none recorded"]

    # Loop 2: reply rates, internship submissions only
    rows = [r for r in RE.ledger_rows() if r.get("status") == "submitted"
            and RE.INTERN_TITLE.search(re.sub(r"\[.*?\]", "", r.get("role", "")))]
    lines += ["", "## What gets a reply (internships only)", "",
              "Reply = any assessment/interview/offer. With this few wins, read the range, not the point estimate.", ""]
    for field in ("category", "ats"):
        lines += [f"| {field} | sent | replies | rate (90% range) |", "|---|---|---|---|"]
        groups = collections.defaultdict(list)
        for r in rows:
            groups[r.get(field) or "?"].append(r)
        for key, rs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]:
            k = sum(r.get("response") in POSITIVE for r in rs)
            m, lo, hi = beta_range(k, len(rs))
            lines.append(f"| {key} | {len(rs)} | {k} | {m:.1%} ({lo:.1%}-{hi:.1%}) |")
        lines.append("")
    applied = RE.already_applied_keys()
    todo = sorted(((w, c, r, u) for u, (w, c, r) in by_hand.items() if RE.job_key(c, r, u) not in applied), reverse=True)
    lines += ["", f"## Apply these yourself ({len(todo)} blocked by a CAPTCHA)", "",
              "The pipeline never solves CAPTCHAs. Newest first.", ""]
    lines += [f"- {w} {c} - {r[:70]}: {u}" for w, c, r, u in todo[:60]]
    out = C.DATA / "learning_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Wrote {build()}")
