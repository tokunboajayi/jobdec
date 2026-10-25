"""
AI agents for the application pipeline. Agents decide; existing code (fill.py, batch_apply.py) acts.

  job_scout        reads the full job description, scores fit 0-10           (fast model)
  resume_tailor    reorders real resume bullets/skills for each job            (writer model)
  form_answerer    answers unknown form questions from verified facts only     (writer model)
  outreach_drafter drafts LinkedIn notes for strong applications - drafts only (writer model)
  inbox_analyst    reads replies: rejection / assessment / interview / offer   (fast model)
  site_fixer       turns failures into profile.json rules or code patches      (expert model)
  diagnostics      classifies failures into actionable buckets (rule-based, 0 tokens)
  supervisor       always-on daemon: monitors, diagnoses, dispatches fixes, retries (rule-based)
  coordinator      daily_run.py runs them all in order and writes a briefing

Settings: strategy.json -> "agents". Needs ANTHROPIC_API_KEY in ../../.env (or the environment).
Every agent degrades gracefully: with no key, no budget left, or autonomy "off", the pipeline
falls back to the rule-based logic in results_engine.py.
"""
