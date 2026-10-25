# Comprehensive Implementation Plan: AJ Agent Brain & High-Velocity Auto-Tuning Engine

## Executive Summary
The current application pipeline has achieved verified automated submissions across Workday, Greenhouse, and Ashby (28+ verified applications logged, 19 direct confirmation receipts in Gmail). However, application throughput is throttled by **serial latency** (60–120s per role), **repetitive error retries on common ATS obstacles**, and **lack of a centralized self-learning memory**. 

This plan designs the **AJ Agent Brain**: an autonomous, token-minimized learning system that:
1. Identifies recurring errors across all ATS portals in real time.
2. Self-heals by compiling successful resolutions into local zero-token rules.
3. Eliminates token waste and LLM latency via local fuzzy/semantic caching.
4. Accelerates pipeline velocity from ~1.5 minutes per job to under 25 seconds per job.

---

## 1. Problem Analysis & Bottleneck Decomposition

### Key Inefficiencies Identified:
1. **Repeated Obstacles**: When portal A fails on a dropdown (e.g. County selection, Month vs Number, or unexpected radio button), portal B with the exact same Workday tenant fails identically because lessons aren't shared across tasks.
2. **Slow Retry Loops**: When an obstacle is encountered, the crawler retries up to 4 times with exponential backoff (wasting 30–60s) before skipping.
3. **Zero-Token Opportunities Missed**: Simple variants of questions (e.g. *"Are you legally authorized to work in the United States?"* vs *"Do you have valid US work authorization?"*) should never hit an LLM; they must resolve in 0.5ms locally.
4. **Single-Threaded Headless Browser**: A single browser instance loads the URL, navigates login, fills 5 pages, and submits before even touching the next URL.

---

## 2. System Architecture: The AJ Agent Brain

### Core Components:

### A. The Error Vault (`error_vault.json`)
* Automatically logs every failure across all runs with a structured signature:
  * `ats_type`: `workday`, `greenhouse`, `ashby`, `lever`, etc.
  * `portal_domain`: e.g. `spgi.wd5.myworkdayjobs.com`
  * `step_index` & `page_url`: where the hang occurred
  * `field_selector` & `label_text`: exact element that failed validation
  * `failure_reason`: `stuck_step`, `unresolved_field`, `auth_lock`, `date_format_mismatch`
  * `dom_snippet`: 1KB context of the problematic input

### B. Self-Healing & Auto-Patching Compiler (`brain_agent.py`)
* Analyzes recurring failures (frequency $\ge 2$):
  * If a date field fails because the portal expects `MM/DD/YYYY` instead of month text, Brain synthesizes a portal-specific date override.
  * If a Workday tenant has a unique submit button class or an unmapped county dropdown, Brain compiles the fix directly into `brain_knowledge.json`.
  * Brain updates the live execution rules without restarting the process.

### C. Zero-Token Local Knowledge Graph & Semantic Cache
* **Local Invariants (0 Tokens)**:
  * 150+ pre-compiled regex & fuzzy patterns for candidate attributes:
    * Work authorization, sponsorship, security clearance $\rightarrow$ Instant `"Yes"` / `"No"`
    * Education, Major, Degree level, GPA $\rightarrow$ Canonical formats
    * Address, County, State code, Zip code $\rightarrow$ Standardized lookups
    * Demographics, Veteran, Disability $\rightarrow$ Pre-set standard answers
* **Cached AI Responses (`semantic_vault.json`)**:
  * For open-ended behavioral questions (*"Why do you want to work here?"*, *"Describe an automation project"*), responses are stored with semantic embedding fingerprints.
  * Similar questions reuse pre-generated high-scoring responses tailored to candidate experience (Delta Air Lines / W.A Investments) with zero LLM API calls.

### D. Fast-Path Velocity Accelerator
* **Smart Fast-Fail (5s vs 60s)**: If an ATS requires external SMS 2FA or human verification that cannot be bypassed via Gmail, immediately flag the domain in the Brain, skip in 5 seconds, and preserve pipeline momentum.
* **Pre-Flight Cookie Warming**: Reuses authenticated sessions across identical Workday tenants (`*.wd1.myworkdayjobs.com`, `*.wd5.myworkdayjobs.com`) to skip the login step entirely on subsequent jobs from that provider.

---

## 3. Technical Implementation Workstreams

### Workstream 1: Brain Knowledge Base & Error Vault
* Create `Job Applications/autofill/brain/`:
  * `vault.py`: Thread-safe persistence of failure signatures, resolution history, and domain profiles.
  * `rules.json`: Dynamic rule store that overrides default heuristics based on historical success.
* Add hook in `fill.py` and `batch_apply.py` to feed all failed fields, unhandled exceptions, and timeouts directly to `vault.record_failure(...)`.

### Workstream 2: Zero-Token Local Semantic Resolver
* Upgrade `ai_responder.py` with a 3-tier lookup pipeline:
  1. **Tier 1 (0ms, 0 tokens)**: Exact & Regex Pattern Matcher (expanded to 100% of standard screening questions).
  2. **Tier 2 (2ms, 0 tokens)**: Local Jaccard/Levenshtein Similarity Cache against previously answered questions.
  3. **Tier 3 (Fallback)**: Call Gemini with strict prompt constraints, save the result to Tier 2 cache with canonicalized tags.

### Workstream 3: Self-Learning Feedback Loop (`auto_tuner.py`)
* Periodically inspect `error_vault.json`:
  * Group errors by ATS and field type.
  * Auto-generate rules for recurring dropdown values, format mismatches, and multi-step navigations.
  * Verify rule validity before promoting to production `profile.json` or `rules.json`.

### Workstream 4: Pipeline Throughput Optimization
* Optimize navigation timeouts in `fill.py`:
  * Dynamic transition wait (detect URL or DOM mutation instantly rather than fixed `time.sleep()`).
  * Reduce inter-step polling from 1.5s to 0.4s with `page.wait_for_load_state("domcontentloaded")`.
  * Pre-filter dead or locked links using a lightweight asynchronous HTTP head request before launching full Chromium instances.

---

## 4. Verification & Success Metrics

| Metric | Current State | Target State with Agent Brain |
|---|---|---|
| **Average Time per Job** | 75 – 120 seconds | **15 – 25 seconds** |
| **LLM Token Consumption** | ~1,200 tokens / job | **< 80 tokens / job** (93% reduction) |
| **Recurring Error Repetition** | Identical errors repeated across same ATS | **Zero repetition** (auto-patched on 2nd occurrence) |
| **Daily Application Capacity** | ~25 - 40 / day | **100+ / day** (within current strategy cap) |
| **Confirmation Receipt Rate** | ~65% of attempted | **> 90% verified submission rate** |
