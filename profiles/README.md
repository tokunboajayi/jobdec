# Candidate homes

Each folder here is one person's private data. Everything in `profiles/` except this README is
git-ignored, so nothing personal is ever committed. Without `JOBDEC_HOME` the owner's original
layout is used (see `candidate.py`).

## Add a candidate

1. Create the folder layout:

   ```
   profiles/<name>/
     .env           copy of ../../.env.example, filled with this person's CANDIDATE_* facts and tokens
     profile.json   answer rules + "standing_facts" (copy the owner's structure, use only this person's facts)
     resumes/       resume_gen.py (MASTER data), master_resume.pdf, cover_letter_gen.py, transcript
   ```

   ```
   mkdir -p profiles/<name>/resumes
   cp .env.example profiles/<name>/.env
   ```

2. Run any command with the home selected (path is relative to the `autofill` folder):

   ```
   # bash
   JOBDEC_HOME=profiles/<name> python daily_run.py --dry-run
   # PowerShell
   $env:JOBDEC_HOME = "profiles/<name>"; python daily_run.py --dry-run
   ```

   Ledgers, queues, caches and Telegram state for that person are written to `profiles/<name>/`
   (`applications.csv` and `data/`), never to the shared folder.

3. Before committing anything, check nothing personal is staged:

   ```
   git status --short profiles/
   git ls-files -ci --exclude-standard   # must print nothing
   ```

Never put one person's facts in code, prompts or another person's home.
