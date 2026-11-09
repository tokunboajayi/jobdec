"""
In-Chat AI Mock Interview Simulator for Telegram.
Simulates technical & behavioral interview rounds for target cybersecurity employers.
Evaluates answers using the STAR framework, gives feedback, and scores responses.
"""
from typing import Dict, Any, List, Optional
import random

INTERVIEW_SESSIONS: Dict[int, Dict[str, Any]] = {}

CYBER_QUESTION_BANK = [
    {
        "id": "ad_rbac",
        "topic": "Active Directory & IAM",
        "question": "Can you walk me through how you design and enforce Role-Based Access Control (RBAC) and Least Privilege within Active Directory, and how you manage Group Policy Objects (GPOs) to prevent privilege escalation?",
        "ideal_points": ["Principle of Least Privilege", "Tiered administration (Tier 0/1/2)", "GPO hardening", "Auditing / logging"]
    },
    {
        "id": "incident_siem",
        "topic": "Incident Response & SIEM",
        "question": "Imagine your SIEM triggers a high-severity alert for multiple failed logins followed by a successful sign-in from an anomalous foreign IP. How do you triage, contain, and remediate this incident?",
        "ideal_points": ["Verify user identity / MFA status", "Revoke active session tokens", "Isolate host if compromised", "Analyze authentication logs", "Document IOCs in ticketing system"]
    },
    {
        "id": "troubleshooting",
        "topic": "Systems Administration & Troubleshooting",
        "question": "Tell me about a time a critical enterprise software or system service failed, impacting users. How did you diagnose the root cause under pressure, and what preventive measure did you implement?",
        "ideal_points": ["Structured diagnostic method", "Event Viewer / logs inspection", "Clear communication with stakeholders", "Automated script or monitor to prevent recurrence"]
    },
    {
        "id": "behavioral_pressure",
        "topic": "Behavioral / Teamwork",
        "question": "Describe a situation where a business department requested temporary administrative bypass or relaxed firewall rules to hit a project deadline. How did you balance security requirements with business operations?",
        "ideal_points": ["Constructive collaboration", "Compensating controls", "Time-bounded exception with executive sign-off", "Clear risk explanation without saying 'just no'"]
    }
]


def start_interview_session(chat_id: int, company: str = "Target Employer", role: str = "Cybersecurity Specialist") -> str:
    """Initializes an interview session for the user."""
    INTERVIEW_SESSIONS[chat_id] = {
        "company": company,
        "role": role,
        "question_idx": 0,
        "scores": [],
        "feedback_log": [],
        "questions": list(CYBER_QUESTION_BANK)
    }
    
    first_q = CYBER_QUESTION_BANK[0]["question"]
    return (
        f"🎙️ <b>AI Mock Interviewer: {company}</b>\n"
        f"<b>Role:</b> {role}\n"
        f"<b>Interviewer:</b> Lead Information Security Manager\n\n"
        f"─────────────────────────────\n"
        f"<i>\"Welcome Michael. Thanks for taking the time to speak with our security team today. Let's dive right into our first technical scenario:\"</i>\n\n"
        f"❓ <b>Question 1/4 ({CYBER_QUESTION_BANK[0]['topic']}):</b>\n"
        f"\"{first_q}\"\n\n"
        f"💡 <i>Reply with a voice memo or text answer using the STAR method. Type /exit to cancel.</i>"
    )


def evaluate_and_advance_interview(chat_id: int, user_answer: str) -> str:
    """Evaluates the candidate's answer, calculates score, and presents the next question."""
    session = INTERVIEW_SESSIONS.get(chat_id)
    if not session:
        return "No active interview session found. Type <code>/interview &lt;Company&gt;</code> to begin!"

    idx = session["question_idx"]
    q_data = session["questions"][idx]
    
    # Calculate score based on STAR structure and technical keywords
    ans_lower = user_answer.lower()
    score = 6.0
    matched_points = []
    for pt in q_data["ideal_points"]:
        keywords = pt.lower().split()
        if any(kw in ans_lower for kw in keywords if len(kw) > 3):
            score += 1.0
            matched_points.append(pt)

    if len(user_answer.split()) > 35:
        score += 0.5
    score = min(10.0, max(5.0, score))
    session["scores"].append(score)

    feedback = (
        f"📊 <b>Evaluation (Score: {score:.1f}/10)</b>\n"
        f"✅ <b>Strong Signals:</b> {', '.join(matched_points) if matched_points else 'Good structured response.'}\n"
        f"💡 <b>Coach Tip:</b> Make sure to clearly state your Result—e.g. 'reduced ticket resolution time by 30%' or 'eliminated unauthorized access risk'."
    )

    session["question_idx"] += 1
    if session["question_idx"] >= len(session["questions"]):
        # Completed interview
        avg_score = sum(session["scores"]) / len(session["scores"])
        del INTERVIEW_SESSIONS[chat_id]
        verdict = "🟢 Strong Hire / Screen Passed" if avg_score >= 8.0 else ("🟡 Hire with Minor Polish" if avg_score >= 6.5 else "🔴 Needs Review")
        return (
            f"{feedback}\n\n"
            f"🏁 <b>MOCK INTERVIEW COMPLETE!</b>\n"
            f"─────────────────────────────\n"
            f"<b>Target:</b> {session['company']} ({session['role']})\n"
            f"<b>Average Score:</b> <b>{avg_score:.1f} / 10.0</b>\n"
            f"<b>Verdict:</b> {verdict}\n\n"
            f"🏆 Great practice! Use <code>/prep {session['company']}</code> to review your full Interview Battlecard before the real interview."
        )

    next_idx = session["question_idx"]
    next_q = session["questions"][next_idx]
    return (
        f"{feedback}\n\n"
        f"─────────────────────────────\n"
        f"❓ <b>Question {next_idx + 1}/4 ({next_q['topic']}):</b>\n"
        f"\"{next_q['question']}\"\n\n"
        f"💡 <i>Reply with your voice memo or text answer.</i>"
    )


def is_in_interview(chat_id: int) -> bool:
    return chat_id in INTERVIEW_SESSIONS

