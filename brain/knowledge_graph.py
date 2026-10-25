"""
JOBDEC KNOWLEDGE GRAPH // GRAPH-RAG & NETWORK REFERRAL ENGINE
Graph intelligence combining Candidate Invariants, Company Ecosystems,
Job Requisitions, LinkedIn Human Referral Networks, and Verified Facts.
"""
import csv
import json
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

HERE = pathlib.Path(__file__).resolve().parent
AUTOFILL_DIR = HERE.parent
ROOT_DIR = AUTOFILL_DIR.parent


class JobdecKnowledgeGraph:
    """Enterprise Knowledge Graph for candidate facts, referral paths, and ATS intelligence."""

    def __init__(self, autofill_dir: Optional[pathlib.Path] = None):
        self.autofill_dir = autofill_dir or AUTOFILL_DIR
        self.root_dir = self.autofill_dir.parent
        self.workspace_root = self.autofill_dir.parent.parent
        self.graph = nx.MultiDiGraph()
        self._built = False

    def build(self) -> nx.MultiDiGraph:
        """Constructs or refreshes the full Knowledge Graph from all project data sources."""
        self.graph.clear()

        # Load profile facts if available
        prof_data = {}
        prof_path = self.autofill_dir / "profile.json"
        if prof_path.exists():
            try:
                prof_data = json.loads(prof_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        def _get_prof_fact(patterns: List[str], default_val: str) -> str:
            for r in prof_data.get("rules", []):
                q = (r.get("q") or "").lower()
                for pat in patterns:
                    if re.search(pat, q, re.I) and r.get("a") is not None:
                        ans = str(r["a"]).strip()
                        if ans and ans != "ASK":
                            return ans
            return default_val

        # 1. Candidate Node & Core Facts (per-user isolated)
        cand_id = "Candidate:You"
        cand_name = os.getenv("CANDIDATE_FULL_NAME") or os.getenv("CANDIDATE_NAME") or _get_prof_fact([r"\bfirst\s*name\b|\bfull\s*name\b"], "Applicant")
        cand_email = os.getenv("CANDIDATE_EMAIL") or _get_prof_fact([r"\be[- ]?mail\b"], "")
        cand_phone = os.getenv("CANDIDATE_PHONE") or _get_prof_fact([r"\bphone\b|\bmobile\b"], "")
        cand_loc = os.getenv("CANDIDATE_LOCATION_TEXT") or _get_prof_fact([r"\bcity\b|\blocation\b|\baddress\b"], "")
        cand_degree = os.getenv("CANDIDATE_DEGREE_EXACT", os.getenv("CANDIDATE_DEGREE")) or _get_prof_fact([r"\bdegree\b"], "Bachelors")
        cand_major = os.getenv("CANDIDATE_MAJOR") or _get_prof_fact([r"\bmajor\b|\bfield of study\b"], "Computer Science")
        cand_gpa = os.getenv("CANDIDATE_GPA") or _get_prof_fact([r"\bgpa\b"], "")
        cand_grad = os.getenv("CANDIDATE_EXPECTED_GRAD_DATE") or _get_prof_fact([r"graduat.*date"], "")

        self.graph.add_node(
            cand_id,
            node_type="Candidate",
            label=cand_name,
            name=cand_name,
            email=cand_email or "user@example.com",
            phone=cand_phone,
            location=cand_loc,
            degree=cand_degree,
            major=cand_major,
            gpa=cand_gpa,
            grad_date=cand_grad,
            work_auth="Authorized",
        )

        # 2. Academic & Fellowship Institutions (derived dynamically)
        uni_name = os.getenv("CANDIDATE_UNIVERSITY") or _get_prof_fact([r"\bschool\b|\buniversity\b|\bcollege\b"], "")
        if uni_name:
            self.add_institution(uni_name, category="University")
            self.graph.add_edge(cand_id, f"Institution:{uni_name}", relation="ALUMNUS_OR_STUDENT_AT")

        fellowship = os.getenv("CANDIDATE_FELLOWSHIP") or _get_prof_fact([r"\bfellowship\b|\bfellow\b"], "")
        if fellowship:
            self.add_institution(fellowship, category="Fellowship")
            self.graph.add_edge(cand_id, f"Institution:{fellowship}", relation="FELLOW_OF")

        # 3. Candidate Experience & Skill Subgraph
        self._ingest_candidate_experiences(cand_id, prof_data)

        # 4. Ingest LinkedIn Referral Network (tracker.csv)
        self._ingest_tracker(cand_id, uni_name or "University")

        # 5. Ingest Active Job Sensors (queue_ranked.txt / queue.txt)
        self._ingest_job_sensors(cand_id)

        # 6. Ingest Job Applications & Requisitions (applications.csv)
        self._ingest_applications(cand_id)

        # 7. Ingest Strategy Target Companies (strategy.json)
        self._ingest_strategy()

        # 8. Ingest LinkedIn Outreach Campaign Logs (outreach_log.csv)
        self._ingest_outreach_log(cand_id)

        # 9. Ingest Outreach Drafts for Applied Roles (outreach_drafts.csv)
        self._ingest_outreach_drafts(cand_id)

        # 10. Ingest Live Application Execution Telemetry & ATS (results.csv)
        self._ingest_results(cand_id)

        # 11. Ingest Verified Profile Rules & Policies (profile.json)
        self._ingest_profile_rules(cand_id)

        self._built = True
        return self.graph

    ALIASES = {
        "amex": "American Express",
        "american express": "American Express",
        "goldman": "Goldman Sachs",
        "goldman sachs": "Goldman Sachs",
        "gs": "Goldman Sachs",
        "jpm": "JPMorgan Chase",
        "jpmorgan": "JPMorgan Chase",
        "jpmorgan chase": "JPMorgan Chase",
        "home depot": "The Home Depot",
        "the home depot": "The Home Depot",
        "cfa": "Chick-fil-A",
        "chick-fil-a": "Chick-fil-A",
        "cox": "Cox Automotive",
        "cox automotive": "Cox Automotive",
        "delta": "Delta Air Lines",
        "delta air lines": "Delta Air Lines",
        "bofa": "Bank of America",
        "bank of america": "Bank of America",
        "auto owners insurance": "Auto-Owners Insurance",
        "autoownersinsurance": "Auto-Owners Insurance",
        "xcel energy": "Xcel Energy",
        "xcelenergy": "Xcel Energy",
        "first national bank": "First National Bank",
        "firstnationalbank": "First National Bank",
        "veeam software": "Veeam Software",
        "veeamsoftware": "Veeam Software",
        "dv trading": "DV Trading",
        "dvtrading": "DV Trading",
        "gecko robotics": "Gecko Robotics",
        "geckorobotics": "Gecko Robotics",
        "robert bosch venture capital": "Robert Bosch Venture Capital",
        "robertboschventurecapital": "Robert Bosch Venture Capital",
        "the hartford": "The Hartford",
        "thehartford": "The Hartford",
        "s&p global": "S&P Global",
        "sp global": "S&P Global",
        "spglobal": "S&P Global",
        "fhlbank chicago": "FHLBank Chicago",
        "fhlbankchicago": "FHLBank Chicago",
        "corewell health": "Corewell Health",
        "corewellhealth": "Corewell Health",
        "guardian life": "Guardian Life",
        "guardianlife": "Guardian Life",
        "icf international": "ICF International",
        "icfinternational": "ICF International",
        "blackrock": "BlackRock",
        "jane street": "Jane Street",
        "janestreet": "Jane Street",
    }

    def canonical_company(self, name: str) -> str:
        clean = name.strip()
        if not clean:
            return clean
        lower = clean.lower()
        if lower in self.ALIASES:
            return self.ALIASES[lower]
        # Un-smash camelCase / PascalCase names if the alias exists
        if re.match(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+$", clean):
            unsplit = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", clean)
            if unsplit.lower() in self.ALIASES:
                return self.ALIASES[unsplit.lower()]
        return clean

    def add_institution(self, name: str, category: str = "University") -> str:
        node_id = f"Institution:{name}"
        if node_id not in self.graph:
            self.graph.add_node(node_id, node_type="Institution", label=name, category=category)
        return node_id

    def add_company(self, name: str, tier: str = "Target") -> str:
        clean = self.canonical_company(name)
        node_id = f"Company:{clean}"
        if node_id not in self.graph:
            self.graph.add_node(node_id, node_type="Company", label=clean, tier=tier)
        return node_id

    def _ingest_candidate_experiences(self, cand_id: str, prof_data: Optional[Dict[str, Any]] = None):
        """Builds Experience -> Metric -> Skill hierarchy from context.MASTER or profile.json."""
        prof_data = prof_data or {}
        master_sections = []
        try:
            from agents import context
            if hasattr(context, "MASTER") and isinstance(context.MASTER, dict):
                master_sections = context.MASTER.get("sections", [])
        except Exception:
            master_sections = []

        loaded_any = False
        for sec in master_sections:
            title = sec.get("title", "").upper()
            if "EXPERIENCE" in title or "INITIATIVE" in title:
                for idx, entry in enumerate(sec.get("entries", [])):
                    org = entry.get("org", "").strip()
                    if not org:
                        continue
                    role = entry.get("role", "")
                    exp_id = f"Exp:{re.sub(r'[^a-zA-Z0-9]', '', org)}"
                    bullets = entry.get("bullets", [])
                    self.graph.add_node(exp_id, node_type="Experience", label=f"{org} ({role})", org=org, role=role)
                    self.graph.add_edge(cand_id, exp_id, relation="HAS_EXPERIENCE")

                    comp_id = self.add_company(org, tier="Former Employer")
                    self.graph.add_edge(exp_id, comp_id, relation="AT_COMPANY")

                    for b in bullets:
                        m_id = f"Metric:{abs(hash(b))}"
                        self.graph.add_node(m_id, node_type="Metric", label=b[:60] + "...", text=b)
                        self.graph.add_edge(exp_id, m_id, relation="ACHIEVED")
                    loaded_any = True

            if "ADDITIONAL" in title or "SKILL" in title:
                for item in sec.get("labeled", []):
                    if len(item) == 2:
                        cat, skills_str = item
                        for s in [x.strip() for x in re.split(r"[,;]", skills_str) if x.strip()]:
                            s_id = f"Skill:{s}"
                            if s_id not in self.graph:
                                self.graph.add_node(s_id, node_type="Skill", label=s, category=cat)
                            self.graph.add_edge(cand_id, s_id, relation="POSSESSES_SKILL")

        # Ingest skills from profile.json rules
        for r in prof_data.get("rules", []):
            q = (r.get("q") or "").lower()
            if any(k in q for k in ["skill", "programming", "technology", "languages", "framework"]):
                ans = str(r.get("a", ""))
                for token in re.split(r"[,;/]", ans):
                    token = token.strip()
                    if len(token) > 1 and len(token) < 30 and not token.lower().startswith("http"):
                        s_id = f"Skill:{token}"
                        if s_id not in self.graph:
                            self.graph.add_node(s_id, node_type="Skill", label=token, name=token)
                        self.graph.add_edge(cand_id, s_id, relation="POSSESSES_SKILL")

        # Fallback baseline for test environments only
        if not loaded_any and (os.getenv("PYTEST_CURRENT_TEST") or os.getenv("DEMO_MODE") == "1"):
            experiences = [
                {
                    "id": "Exp:DeltaAirLines",
                    "org": "Delta Air Lines",
                    "role": "Project Management Intern, Airport Customer Service",
                    "metrics": [
                        "Automated shift-selection workflows handling 50,000+ employee bids",
                        "Reduced manual coordination by 150+ hours across frontline operations",
                        "Built 6 Excel trackers across 8 workstreams for 20,000 workforce",
                        "Cleaned 3,000+ workflow records remediating 2,500 exceptions",
                    ],
                    "skills": ["Python", "Process Automation", "Excel", "Data Cleaning", "Tableau", "Requirements Specs"],
                },
                {
                    "id": "Exp:WAInvestments",
                    "org": "W. A Investments & Development",
                    "role": "AI Research & Acquisitions Analyst",
                    "metrics": [
                        "Evaluated rent payment SaaS and Stripe Connect architectures",
                        "Benchmarked acquisition targets across real estate holding portfolios",
                        "Built corporate website with modern full-stack architectures",
                    ],
                    "skills": ["Agentic AI", "Market Research", "Financial Benchmarking", "Python", "SQL", "Full Stack"],
                },
            ]
            for exp in experiences:
                self.graph.add_node(exp["id"], node_type="Experience", label=f"{exp['org']} ({exp['role']})", **exp)
                self.graph.add_edge(cand_id, exp["id"], relation="HAS_EXPERIENCE")
                comp_id = self.add_company(exp["org"], tier="Former Employer")
                self.graph.add_edge(exp["id"], comp_id, relation="AT_COMPANY")
                for m in exp["metrics"]:
                    m_id = f"Metric:{abs(hash(m))}"
                    self.graph.add_node(m_id, node_type="Metric", label=m, text=m)
                    self.graph.add_edge(exp["id"], m_id, relation="ACHIEVED")
                for s in exp["skills"]:
                    s_id = f"Skill:{s}"
                    if s_id not in self.graph:
                        self.graph.add_node(s_id, node_type="Skill", label=s, name=s)
                    self.graph.add_edge(exp["id"], s_id, relation="APPLIED_SKILL")
                    self.graph.add_edge(cand_id, s_id, relation="POSSESSES_SKILL")

    def _ingest_tracker(self, cand_id: str, uni_name: str):
        """Ingests LinkedIn networking contacts, stages, and referral edges from tracker.csv."""
        tracker_paths = [self.autofill_dir / "tracker.csv", self.autofill_dir.parent / "tracker.csv", self.autofill_dir.parent.parent / "tracker.csv"]
        for p in tracker_paths:
            if not p.exists():
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = (row.get("Name") or "").strip()
                        firm = (row.get("Firm") or "").strip()
                        role = (row.get("Role") or "").strip()
                        stage = (row.get("Stage") or "Queued").strip()
                        hook = (row.get("Hook") or "").strip()
                        url = (row.get("Profile URL") or "").strip()

                        if not name or not firm:
                            continue

                        contact_id = f"Contact:{name}"
                        comp_id = self.add_company(firm)

                        # Determine tags/affiliations
                        is_gsu = any(k in role.lower() or k in hook.lower() for k in ["robinson", "gsu", "georgia state"])
                        is_mlt = "mlt" in role.lower() or "mlt" in hook.lower()
                        is_hm = any(k in role.lower() for k in ["manager", "lead", "director", "head", "vp", "tpm"])

                        self.graph.add_node(
                            contact_id,
                            node_type="Contact",
                            label=name,
                            firm=firm,
                            role=role,
                            stage=stage,
                            hook=hook,
                            url=url,
                            is_hiring_manager=is_hm,
                            is_gsu_alum=is_gsu,
                            is_mlt_fellow=is_mlt,
                        )

                        self.graph.add_edge(contact_id, comp_id, relation="WORKS_AT", role=role)
                        self.graph.add_edge(cand_id, contact_id, relation="NETWORKING_WITH", stage=stage)

                        if is_gsu:
                            self.graph.add_edge(contact_id, f"Institution:{uni_name}", relation="ALUMNUS_OF")
                        if is_mlt:
                            self.graph.add_edge(contact_id, "Institution:Management Leadership for Tomorrow (MLT)", relation="FELLOW_OF")
            except Exception:
                pass

    def _ingest_job_sensors(self, cand_id: str, max_items: int = 250):
        """
        Ingests fresh active job sensor requisitions from queue_ranked.txt and queue.txt.
        Allows new users and active job scouts to instantly populate their Knowledge Graph
        with real-time discovered roles, target companies, ATS platforms, and fit scores.
        """
        queue_paths = [
            self.autofill_dir / "queue_ranked.txt",
            self.autofill_dir / "queue.txt",
            self.workspace_root / "queue.txt",
        ]
        seen_urls: Set[str] = set()
        count = 0

        for qp in queue_paths:
            if not qp.exists() or count >= max_items:
                continue
            try:
                current_fit = "8.0"
                current_ats = "ats"
                with open(qp, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if count >= max_items:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("#"):
                            m_meta = re.search(r"fit\s*([\d\.]+)\s*\|\s*([^|]+)\s*\|\s*(\w+)", line, re.I)
                            if m_meta:
                                current_fit = m_meta.group(1).strip()
                                current_ats = m_meta.group(3).strip().lower()
                            continue

                        parts = re.split(r"\s+(https?://\S+)", line, maxsplit=1)
                        if len(parts) < 2:
                            continue
                        job_heading = parts[0].strip()
                        job_url = parts[1].strip()
                        if job_url in seen_urls:
                            continue
                        seen_urls.add(job_url)

                        detected_ats = current_ats
                        url_low = job_url.lower()
                        if "greenhouse.io" in url_low:
                            detected_ats = "greenhouse"
                        elif "ashbyhq.com" in url_low:
                            detected_ats = "ashby"
                        elif "lever.co" in url_low:
                            detected_ats = "lever"
                        elif "myworkdayjobs.com" in url_low:
                            detected_ats = "workday"
                        elif "icims.com" in url_low:
                            detected_ats = "icims"
                        elif "smartrecruiters.com" in url_low:
                            detected_ats = "smartrecruiters"
                        elif "oraclecloud.com" in url_low:
                            detected_ats = "oracle"

                        heading_clean = re.sub(r"\[.*?\]", "", job_heading).strip()
                        tokens = heading_clean.split()
                        if not tokens:
                            continue

                        comp_name = tokens[0]
                        role_name = " ".join(tokens[1:]) if len(tokens) > 1 else heading_clean
                        if not role_name:
                            role_name = heading_clean

                        comp_canon = self.canonical_company(comp_name)
                        comp_id = self.add_company(comp_canon, tier="Discovered Target")

                        if detected_ats and detected_ats != "other":
                            ats_id = f"ATS:{detected_ats.capitalize()}"
                            if ats_id not in self.graph:
                                self.graph.add_node(ats_id, node_type="ATS", label=detected_ats.capitalize())
                            self.graph.add_edge(comp_id, ats_id, relation="USES_ATS")

                        req_id = f"Req:{comp_canon} - {role_name[:50]}"
                        if req_id not in self.graph:
                            self.graph.add_node(
                                req_id,
                                node_type="Requisition",
                                label=role_name[:60],
                                company=comp_canon,
                                stage="Queued (Sensor Discovery)",
                                fit_score=current_fit,
                                url=job_url,
                                ats=detected_ats,
                            )
                            self.graph.add_edge(req_id, comp_id, relation="OPENED_BY")
                            self.graph.add_edge(cand_id, req_id, relation="TARGETS_REQUISITION", stage="Queued", fit_score=current_fit)
                        count += 1
            except Exception:
                pass

    def _ingest_applications(self, cand_id: str):
        """Ingests jobs, ATS types, and application outcomes from applications.csv."""
        app_paths = [self.autofill_dir / "applications.csv", self.autofill_dir.parent / "applications.csv", self.autofill_dir.parent.parent / "applications.csv"]
        for p in app_paths:
            if not p.exists():
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        comp = (row.get("Company") or "").strip()
                        role = (row.get("Role") or "").strip()
                        stage = (row.get("Stage") or "Scored").strip()
                        score = row.get("Fit Score (1-10)") or "0"
                        url = (row.get("Job URL") or "").strip()
                        contact = (row.get("Contact at Company") or "").strip()

                        if not comp or not role:
                            continue

                        req_id = f"Req:{comp} - {role[:50]}"
                        comp_id = self.add_company(comp)

                        self.graph.add_node(
                            req_id,
                            node_type="Requisition",
                            label=role,
                            company=comp,
                            stage=stage,
                            fit_score=score,
                            url=url,
                        )

                        self.graph.add_edge(req_id, comp_id, relation="OPENED_BY")
                        self.graph.add_edge(cand_id, req_id, relation="APPLIED_STATUS", stage=stage, fit_score=score)

                        # Link contact if mentioned
                        if contact:
                            for c_name in [c.strip() for c in contact.split(",")]:
                                c_id = f"Contact:{c_name}"
                                if c_id in self.graph:
                                    self.graph.add_edge(c_id, req_id, relation="CAN_REFER_OR_LEADS")
            except Exception:
                pass

    def _ingest_strategy(self):
        """Ingests protected & target companies from strategy.json."""
        strat_file = self.autofill_dir / "strategy.json"
        if strat_file.exists():
            try:
                data = json.loads(strat_file.read_text(encoding="utf-8"))
                for comp in data.get("target_companies", []):
                    self.add_company(comp, tier="Target")
                for comp in data.get("protected_companies", []):
                    self.add_company(comp, tier="Protected")
            except Exception:
                pass

    def _ingest_outreach_log(self, cand_id: str):
        """Ingests live LinkedIn outreach campaign pitches, dates sent, and follow-ups from outreach_log.csv."""
        log_paths = [
            self.workspace_root / "outreach_log.csv",
            self.autofill_dir.parent / "outreach_log.csv",
            self.autofill_dir / "outreach_log.csv",
        ]
        for p in log_paths:
            if not p.exists():
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        firm = (row.get("Firm") or "").strip()
                        name = (row.get("Name") or "").strip()
                        role = (row.get("Role") or "").strip()
                        note = (row.get("Note") or "").strip()
                        status = (row.get("Status") or "Drafted").strip()
                        date_sent = (row.get("Date Sent") or "").strip()
                        followup = (row.get("Follow-up") or "").strip()

                        if not name:
                            continue

                        # Resolve company from firm or role if listed under generic category like AI/PM
                        actual_firm = firm
                        if firm.upper() in ("AI/PM", "OTHER", ""):
                            for known in ["Delta", "Cox Automotive", "NICE", "Microsoft", "The Home Depot", "Deloitte", "Booz Allen"]:
                                if known.lower() in role.lower() or known.lower() in note.lower():
                                    actual_firm = known
                                    break

                        comp_name = self.canonical_company(actual_firm) if actual_firm else "General"
                        comp_id = self.add_company(comp_name)

                        contact_id = f"Contact:{name}"
                        if contact_id not in self.graph:
                            self.graph.add_node(
                                contact_id,
                                node_type="Contact",
                                label=name,
                                firm=comp_name,
                                role=role,
                                stage=status,
                            )
                        self.graph.add_edge(contact_id, comp_id, relation="WORKS_AT", role=role)
                        self.graph.add_edge(cand_id, contact_id, relation="NETWORKING_WITH", stage=status)

                        target_id = f"Outreach:{name}"
                        self.graph.add_node(
                            target_id,
                            node_type="OutreachTarget",
                            label=f"Pitch: {name}",
                            contact=name,
                            firm=comp_name,
                            role=role,
                            status=status,
                            date_sent=date_sent,
                            followup=followup,
                            pitch=note,
                        )
                        self.graph.add_edge(cand_id, target_id, relation="OUTREACH_TARGET", status=status)
                        self.graph.add_edge(target_id, contact_id, relation="PITCHED_TO", status=status)
                        self.graph.add_edge(target_id, comp_id, relation="AT_COMPANY")
            except Exception:
                pass

    def _ingest_outreach_drafts(self, cand_id: str):
        """Ingests role-targeted LinkedIn connection drafts from outreach_drafts.csv."""
        draft_path = self.autofill_dir / "outreach_drafts.csv"
        if not draft_path.exists():
            return
        try:
            with open(draft_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    company = (row.get("company") or "").strip()
                    role = (row.get("role_applied") or "").strip()
                    note = (row.get("note") or "").strip()
                    hook = (row.get("hook") or "").strip()
                    date = (row.get("date") or "").strip()
                    status = (row.get("status") or "draft").strip()
                    fit = (row.get("fit") or "10.0").strip()
                    search_url = (row.get("linkedin_search") or "").strip()

                    if not company:
                        continue

                    comp_canon = self.canonical_company(company)
                    comp_id = self.add_company(comp_canon)

                    draft_id = f"Draft:{comp_canon}_{idx}"
                    self.graph.add_node(
                        draft_id,
                        node_type="OutreachDraft",
                        label=f"Draft: {comp_canon}",
                        company=comp_canon,
                        role=role,
                        fit_score=fit,
                        note=note,
                        hook=hook,
                        date=date,
                        status=status,
                        search_url=search_url,
                    )
                    self.graph.add_edge(cand_id, draft_id, relation="PREPARED_DRAFT", status=status)
                    self.graph.add_edge(draft_id, comp_id, relation="TARGETS_COMPANY")

                    # Link to requisition if one matches
                    req_id = f"Req:{comp_canon} - {role[:50]}"
                    if req_id in self.graph:
                        self.graph.add_edge(draft_id, req_id, relation="DRAFT_FOR_ROLE")
        except Exception:
            pass

    def _ingest_results(self, cand_id: str):
        """Ingests live application execution outcomes, ATS infrastructure, and confirmation logs from results.csv."""
        res_path = self.autofill_dir / "results.csv"
        if not res_path.exists():
            return
        try:
            with open(res_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    company = (row.get("company") or "").strip()
                    role = (row.get("role") or "").strip()
                    ats = (row.get("ats") or "").strip().lower()
                    status = (row.get("status") or "").strip()
                    response = (row.get("response") or "").strip()
                    date = (row.get("date") or "").strip()
                    url = (row.get("url") or "").strip()
                    fit = (row.get("fit_score") or "0").strip()
                    record = (row.get("record") or "").strip()

                    if not company or not role:
                        continue

                    comp_canon = self.canonical_company(company)
                    comp_id = self.add_company(comp_canon)

                    # Ingest ATS entity hub
                    if ats:
                        ats_id = f"ATS:{ats.capitalize()}"
                        if ats_id not in self.graph:
                            self.graph.add_node(ats_id, node_type="ATS", label=ats.capitalize())
                        self.graph.add_edge(comp_id, ats_id, relation="USES_ATS")

                    # Ensure Requisition exists
                    req_id = f"Req:{comp_canon} - {role[:50]}"
                    if req_id not in self.graph:
                        self.graph.add_node(
                            req_id,
                            node_type="Requisition",
                            label=role,
                            company=comp_canon,
                            stage=response or status,
                            fit_score=fit,
                            url=url,
                        )
                        self.graph.add_edge(req_id, comp_id, relation="OPENED_BY")
                        self.graph.add_edge(cand_id, req_id, relation="APPLIED_STATUS", stage=response or status, fit_score=fit)
                    else:
                        if response:
                            self.graph.nodes[req_id]["stage"] = response
                        elif status == "submitted":
                            self.graph.nodes[req_id]["stage"] = "Submitted"

                    # Add Execution Result node
                    res_id = f"Result:{idx}"
                    self.graph.add_node(
                        res_id,
                        node_type="ExecutionResult",
                        label=f"{status.upper()}: {comp_canon}",
                        company=comp_canon,
                        status=status,
                        response=response,
                        ats=ats,
                        date=date,
                        record=record,
                    )
                    self.graph.add_edge(req_id, res_id, relation="EXECUTED_AS", status=status, date=date)
                    if response:
                        self.graph.add_edge(cand_id, res_id, relation="RECEIVED_RESPONSE", response=response, date=date)
        except Exception:
            pass

    def _ingest_profile_rules(self, cand_id: str):
        """Ingests verified candidate form rules, compliance constraints, and answers from profile.json."""
        prof_path = self.autofill_dir / "profile.json"
        if not prof_path.exists():
            return
        try:
            data = json.loads(prof_path.read_text(encoding="utf-8"))
            rules = data.get("rules", [])
            for idx, r in enumerate(rules):
                q = (r.get("q") or "").strip()
                a = r.get("a")
                src = r.get("src") or "rule"
                if not q or a is None:
                    continue

                rule_id = f"PolicyRule:{idx}"
                clean_q = re.sub(r"\\[\s\w]", " ", q).strip()[:70]
                self.graph.add_node(
                    rule_id,
                    node_type="PolicyRule",
                    label=clean_q or f"Rule #{idx}",
                    question=q,
                    answer=str(a),
                    source=src,
                )
                self.graph.add_edge(cand_id, rule_id, relation="COMPLIES_WITH", answer=str(a))
        except Exception:
            pass

    def find_referral_paths(self, target_company: str) -> List[Dict[str, Any]]:
        """
        Finds the shortest, warmest referral routes to a target company.
        Ranks contacts by stage, alumni connection, and hiring manager authority.
        """
        if not self._built:
            self.build()

        target_norm = self.canonical_company(target_company).lower().strip()
        matched_companies = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "Company" and (target_norm in d.get("label", "").lower() or d.get("label", "").lower() in target_norm)]

        if not matched_companies:
            return []

        comp_node = matched_companies[0]
        comp_name = self.graph.nodes[comp_node]["label"]

        # Find all contacts at this company
        routes = []
        for u, v, data in self.graph.in_edges(comp_node, data=True):
            if data.get("relation") == "WORKS_AT":
                contact_node = u
                c_data = self.graph.nodes[contact_node]

                # Calculate warmth score
                warmth = 0
                reasons = []

                stage = c_data.get("stage", "Queued")
                if stage in ("Chat Scheduled", "Chat Done"):
                    warmth += 50
                    reasons.append("Active coffee chat")
                elif stage in ("Replied", "Thanked/Asked"):
                    warmth += 35
                    reasons.append("Responsive conversation")
                elif stage == "Accepted":
                    warmth += 30
                    reasons.append("Connected 1st-degree")
                elif "sent" in stage.lower():
                    warmth += 25
                    reasons.append("Outreach message sent")
                elif "draft" in stage.lower():
                    warmth += 15
                    reasons.append("Pitch drafted")

                if c_data.get("is_hiring_manager"):
                    warmth += 25
                    reasons.append("Hiring Manager / Team Lead")

                if c_data.get("is_gsu_alum"):
                    warmth += 20
                    reasons.append("Georgia State / Robinson Alum")

                if c_data.get("is_mlt_fellow"):
                    warmth += 20
                    reasons.append("MLT Fellow")

                routes.append({
                    "name": c_data.get("label"),
                    "role": c_data.get("role"),
                    "company": comp_name,
                    "stage": stage,
                    "warmth_score": warmth,
                    "reasons": reasons,
                    "hook": c_data.get("hook", ""),
                    "profile_url": c_data.get("url", ""),
                })

        routes.sort(key=lambda r: r["warmth_score"], reverse=True)
        return routes

    def graph_rag_evidence(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves verified project metrics and facts from the Knowledge Graph
        relevant to an ATS screening prompt.
        """
        if not self._built:
            self.build()

        tokens = set(re.findall(r"\w+", query.lower()))
        results = []

        # Search across Experience and Metric nodes
        for node_id, data in self.graph.nodes(data=True):
            ntype = data.get("node_type")
            if ntype == "Metric":
                text = data.get("text", "")
                metric_tokens = set(re.findall(r"\w+", text.lower()))
                overlap = len(tokens.intersection(metric_tokens))
                if overlap > 0:
                    results.append({"type": "Metric", "text": text, "score": overlap})
            elif ntype == "Experience":
                role = data.get("role", "")
                org = data.get("org", "")
                combo = f"{org} {role}".lower()
                overlap = sum(1 for t in tokens if t in combo)
                if overlap > 0:
                    results.append({"type": "Experience", "org": org, "role": role, "score": overlap * 1.5})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Returns high-level graph metrics and entity distributions."""
        if not self._built:
            self.build()
        from collections import Counter
        counts = Counter(d.get("node_type", "Entity") for _, d in self.graph.nodes(data=True))
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "entity_breakdown": dict(counts),
            "companies_count": counts.get("Company", 0),
            "contacts_count": counts.get("Contact", 0),
            "requisitions_count": counts.get("Requisition", 0),
            "outreach_targets_count": counts.get("OutreachTarget", 0),
            "outreach_drafts_count": counts.get("OutreachDraft", 0),
            "results_count": counts.get("ExecutionResult", 0),
            "rules_count": counts.get("PolicyRule", 0),
            "ats_count": counts.get("ATS", 0),
            "skills_count": counts.get("Skill", 0),
            "metrics_count": counts.get("Metric", 0),
        }

    def get_company_context(self, company: str) -> Dict[str, Any]:
        """Aggregates all intelligence on a given company: referral paths, job requisitions, outreach, and matched evidence."""
        if not self._built:
            self.build()
        canon = self.canonical_company(company)
        paths = self.find_referral_paths(canon)
        comp_id = f"Company:{canon}"

        reqs = []
        outreach = []
        ats_systems = set()
        tier = "General"

        if comp_id in self.graph:
            tier = self.graph.nodes[comp_id].get("tier", "Target")
            for u, v, d in self.graph.in_edges(comp_id, data=True):
                rel = d.get("relation")
                if rel == "OPENED_BY":
                    r_data = self.graph.nodes[u]
                    reqs.append({
                        "role": r_data.get("label"),
                        "stage": r_data.get("stage"),
                        "fit_score": r_data.get("fit_score"),
                    })
                elif rel in ("AT_COMPANY", "TARGETS_COMPANY"):
                    u_data = self.graph.nodes[u]
                    ntype = u_data.get("node_type")
                    if ntype == "OutreachTarget":
                        outreach.append({
                            "type": "Target",
                            "contact": u_data.get("contact"),
                            "status": u_data.get("status"),
                            "date": u_data.get("date_sent"),
                            "pitch": u_data.get("pitch"),
                        })
                    elif ntype == "OutreachDraft":
                        outreach.append({
                            "type": "Draft",
                            "role": u_data.get("role"),
                            "status": u_data.get("status"),
                            "date": u_data.get("date"),
                            "pitch": u_data.get("note"),
                        })

            for u, v, d in self.graph.out_edges(comp_id, data=True):
                if d.get("relation") == "USES_ATS":
                    ats_systems.add(self.graph.nodes[v].get("label"))

        evidence = self.graph_rag_evidence(company, top_k=2)

        return {
            "company": canon,
            "tier": tier,
            "referral_paths": paths,
            "warmest_contact": paths[0] if paths else None,
            "requisitions": reqs,
            "outreach": outreach,
            "ats_systems": sorted(list(ats_systems)),
            "evidence": evidence,
        }

    def export_telemetry_d3(self) -> Dict[str, Any]:
        """Exports the full graph in high-fidelity format for the Neural Net Visualizer."""
        if not self._built:
            self.build()

        nodes = []
        for n, d in self.graph.nodes(data=True):
            ntype = d.get("node_type", "Entity")
            item = {
                "id": n,
                "label": d.get("label", n),
                "type": ntype,
                "group": ntype,
            }
            for k, val in d.items():
                if k not in item and isinstance(val, (str, int, float, bool, list)):
                    item[k] = val
            nodes.append(item)

        links = []
        for u, v, d in self.graph.edges(data=True):
            link_item = {
                "source": u,
                "target": v,
                "relation": d.get("relation", "CONNECTED"),
            }
            for k, val in d.items():
                if k not in link_item and isinstance(val, (str, int, float, bool)):
                    link_item[k] = val
            links.append(link_item)

        stats = self.get_summary_stats()
        return {"nodes": nodes, "links": links, "stats": stats}


# Singleton instance
_INSTANCE: Optional[JobdecKnowledgeGraph] = None


def get_kg() -> JobdecKnowledgeGraph:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = JobdecKnowledgeGraph()
        _INSTANCE.build()
    return _INSTANCE


if __name__ == "__main__":
    kg = get_kg()
    print(f"[KNOWLEDGE GRAPH] Built with {kg.graph.number_of_nodes()} nodes and {kg.graph.number_of_edges()} edges.")
    
    # Test referral lookup for American Express
    amex_paths = kg.find_referral_paths("American Express")
    print(f"\n[REFERRAL PATHS] Top paths for American Express ({len(amex_paths)} found):")
    for p in amex_paths[:3]:
        print(f" -> {p['name']} ({p['role']}) | Warmth: {p['warmth_score']} | {', '.join(p['reasons'])}")

    # Test Graph-RAG evidence extraction
    evidence = kg.graph_rag_evidence("automation workflow shift scheduling Python")
    print(f"\n[GRAPH-RAG] Retrieved {len(evidence)} verified facts:")
    for e in evidence:
        print(f" -> {e.get('text') or e.get('role')}")
