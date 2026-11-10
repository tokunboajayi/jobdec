"""
Unit tests for Autonomous Decision & Stage Advancement Tracker.
Verifies decision classification, positive stage advancements, rank preservation,
and summary generation.
"""
import pytest
from agents.decision_tracker import (
    classify_decision_text,
    format_advancement_telegram_alert,
    get_decision_pipeline_summary,
    STAGE_RANK
)


def test_classify_technical_interview_advancement():
    subject = "Next Steps: Technical Interview for Cloud Security Engineer"
    body = "Hi Michael, We were impressed with your application and would like to invite you to a 45-minute technical screen with our Security Team."
    res = classify_decision_text(subject, body)
    
    assert res["is_advancement"] is True
    assert res["stage"] == "Interview: Technical Screen"
    assert "Schedule interview" in res["action_needed"]
    assert res["rank"] == 4


def test_classify_hiring_manager_screen():
    subject = "Axon Interview Invitation"
    body = "Hi Michael, We are moving you forward in our process. We would love to set up a hiring manager conversation with our Director of IAM."
    res = classify_decision_text(subject, body)
    
    assert res["is_advancement"] is True
    assert res["stage"] == "Interview: Hiring Manager"
    assert res["rank"] == 4


def test_classify_assessment_invitation():
    subject = "Invitation to complete online assessment"
    body = "Please complete the HireVue online assessment within 48 hours to proceed with your application."
    res = classify_decision_text(subject, body)
    
    assert res["is_advancement"] is True
    assert res["stage"] == "Assessment / OA"
    assert "assessment" in res["action_needed"].lower()
    assert res["deadline"] != ""


def test_classify_offer_extended():
    subject = "Offer of Employment - Wolters Kluwer"
    body = "Congratulations Michael! We are pleased to offer you the position of Cybersecurity Specialist. Attached is your formal offer letter."
    res = classify_decision_text(subject, body)
    
    assert res["is_advancement"] is True
    assert res["stage"] == "Offer Extended"
    assert res["rank"] == 6
    assert "Review offer" in res["action_needed"]


def test_classify_rejection_and_confirmation():
    # Rejection
    rej = classify_decision_text("Your application status", "Unfortunately, we have decided to move forward with other candidates at this time.")
    assert rej["is_advancement"] is False
    assert rej["stage"] == "Rejected"
    assert rej["rank"] == 2

    # Confirmation
    conf = classify_decision_text("Application Received", "Thank you for applying to Tenable! Your application was successfully submitted.")
    assert conf["is_advancement"] is False
    assert conf["stage"] == "Applied"
    assert conf["rank"] == 1


def test_stage_ranking_logic():
    # Verify higher stage rank cannot be superseded by lower stage rank
    assert STAGE_RANK["Offer Extended"] > STAGE_RANK["Interview: Technical Screen"]
    assert STAGE_RANK["Interview: Technical Screen"] > STAGE_RANK["Assessment / OA"]
    assert STAGE_RANK["Assessment / OA"] > STAGE_RANK["Rejected"]
    assert STAGE_RANK["Rejected"] > STAGE_RANK["Applied"]


def test_format_advancement_telegram_alert():
    adv = {
        "company": "Axon",
        "role": "Security Operations Engineer II",
        "stage": "Interview: Technical Screen",
        "action_needed": "Schedule 45-min technical interview",
        "deadline": "Friday, Nov 13",
        "decision_timestamp": "Nov 09, 2026 09:30 AM"
    }
    msg = format_advancement_telegram_alert(adv)
    assert "STAGE ADVANCEMENT DETECTED" in msg
    assert "Axon" in msg
    assert "Security Operations Engineer II" in msg
    assert "Interview: Technical Screen" in msg
    assert "Friday, Nov 13" in msg
    assert "Decision Received:" in msg
    assert "Action Deadline:" in msg


def test_get_decision_pipeline_summary():
    summary = get_decision_pipeline_summary()
    assert "Autonomous Decision & Pipeline Summary" in summary
    assert "Total Verified Applications:" in summary
    assert "Offers Extended:" in summary
    assert "Interviews & Screens:" in summary
    assert "Recent Decisions & Application URLs:" in summary
    assert "Job / Portal URL" in summary or "🔗" in summary


