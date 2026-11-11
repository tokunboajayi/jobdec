# Learning from past applications: design (2026-11-10)

## Where things stand
- About 1,450 submissions. Real outcomes: 2 automated assessments (Nissan, Carrier), plus 4 manual assessments and 1 manual interview (CLA, from a direct email). About 130–340 rejections. Everything else got no reply.
- The current learner (`agents/smarts.learner_train`) is a logistic regression that needs 5 or more interviews. It will never have enough data, and twice it trained on fake labels: email rules read "interview" and "offer" into confirmations and assessment invites. **Learning only from wins can't work at this volume.**
- What we do have plenty of is failures: 5,676 `not_submitted`, 713 timeouts, 948 incomplete records, 368 sensitive-question skips, 130 unanswered-question skips, and hundreds of rejections. Learning should start there.

## Three loops, cheapest first

### Loop 1: why didn't it submit? (process failures, daily, automatic)
Each `records/<date>/*.json` already stores the status, the unanswered questions and the blocked questions.
- Group failures by **ATS and site** and by **unanswered question text**. Rank by how many jobs each cause blocked.
- For a question you answer the same way everywhere (availability, relocation, "how did you hear"), propose a `profile.json` rule **for you to approve in Telegram**, using the Apply button that already exists. AI answers never become rules on their own.
- Stop retrying a site after N failures with the same cause. `smarts.should_attempt` and `site_failures` partly do this already. Reuse them.
- Measure it by the submit rate per attempt (about 20% today), per ATS.

### Loop 2: what gets a reply? (outcomes, weekly)
Use graded labels, not just win/lose:
`assessment/interview/offer = 1.0`, `rejection after human review (>3 days) = 0.2`, `instant rejection (<24h, ATS screen-out) = 0.0`, `no reply after 21 days = 0.05`.
Labels come **only from the tracker stage**, or from emails that match the strict patterns. Every label stores the rule version that produced it, so a bad rule can be rolled back.

The model is **Beta-Binomial counts per feature value** (category, ATS, posting age when applied, remote/onsite, company size, tailored or not, cover letter or not, auto or manual). With 8 wins this is honest: it says "Ashby 2% heard-back rate (range 0–6%)" instead of a fake-precise coefficient. Ranking adds a **Thompson-sampling** bonus, so a few low-data categories keep getting tried.
- Measure it by the reply rate of the top 50 jobs ranked each week, compared with a time-split baseline. Deploy only when it beats the current hand-set weights.

### Loop 3: why the rejections? (content, weekly report, human decides)
- For rejected jobs versus assessment jobs, compare job-description keywords with your résumé. `agents/ats_gap_analyzer.py` exists, so reuse it. The output is a report: "rejected postings asked for SQL in 70% of cases; your résumé says it twice". You change your résumé, not the bot.
- Apply speed: the share of applications sent within 48 hours of posting versus later, compared with reply rate.

## Prerequisites (do these first, all small)
1. Log each submission once: `fill.py:1903` and `batch_apply_parallel.py:607` both call `ledger_add`.
2. Mark the 246 full-time applications as `ineligible_role` so they don't count as failed internships.
3. Freeze the email rules behind tests (fake "offer" fixed 2026-11-10; fake "interview" fixed in `b544796`).
4. Never let the learner change **answers**. It may only change **which jobs are tried, and in what order**.

## The honest takeaway
More automated volume has produced 0 interviews out of about 850 automated applications. Your manual applications and warm contacts converted far better (CLA interview, BlackRock and Home Depot assessments). The highest-value "learning" is Loop 3 plus outreach. Loops 1 and 2 make the automation waste less of your time.
