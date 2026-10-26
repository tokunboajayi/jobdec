# Autofill Resilience & Sensory Rules

## 1. Workday Split-Date Input Normalization
* **Invariance:** When extracting and filling composite date inputs (e.g. Workday `dateSectionMonth-input`, `dateSectionDay-input`, `dateSectionYear-input`, or elements with `aria-label` matching Month/Day/Year):
  1. The DOM scanner must append the subfield identifier (`Month`, `Day`, `Year`) to the parent label if not already present.
  2. The input value for `Month` on text/numeric inputs must always be formatted as a two-digit integer (`01` through `12`), never as an alphabetic name (e.g., `"October"`).
  3. Text inputs for `Day` must be formatted as two digits (`01` through `31`), and `Year` as four digits (e.g. `2026` or `2027`).
* **Rationale:** Workday's Voluntary Self-Identification of Disability form and graduation date widgets reject alphabetic month strings, silently discarding non-numeric characters and creating impassable `Invalid Date: /25/2026` validation errors.

---

## 2. Domain-Constrained Option Escalation (Safe Fallback)
* **Invariance:** When the autofill engine encounters a field where the target site rejects the initial answer and engages the emergency fallback option picker:
  1. Referral/source questions (`how did you hear`, `source`, `referral`) must strictly filter out options containing phone country codes (`+\d+`, `country`, `phone`, `mobile`, `device`).
  2. Fallbacks must prefer generic industry standards (`Job Board`, `Career Site`, `Indeed`, `Company Website`, `Other`) before any blind first-option selection.
* **Rationale:** Prevents accidental selection of phone codes (like `+1 United States`) into non-phone dropdowns when an option like `"LinkedIn"` is not present.

---

## 3. Dynamic Knowledge Graph Sensory Ingestion
* **Invariance:** Neural knowledge graphs and sensor analytics must initialize nodes strictly from:
  1. Active `profile.json` candidate facts.
  2. Local sensory queue files (`queue_ranked.txt`, `queue.txt`, `applications.csv`).
  3. No personal employer or school fallbacks may be hardcoded into the graph builder, ensuring clean initialization for any user.
* **Rationale:** Preserves candidate privacy and prevents ghost nodes from previous users from leaking into new user clones.
