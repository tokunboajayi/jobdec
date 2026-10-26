import pytest
from agents import job_validator

def test_closed_job_detection_greenhouse():
    # Known closed Greenhouse job token (e.g. Coinbase token=8175459 that was closed in the run)
    url = "https://boards.greenhouse.io/embed/job_app?token=8175459"
    is_live, reason = job_validator.is_job_active(url, timeout=5)
    assert is_live is False
    assert "closed" in reason.lower() or "not found" in reason.lower()

def test_live_job_detection():
    # Test fallback or live indicator
    # Dummy non-existent job URL should be detected as inactive
    fake_url = "https://boards.greenhouse.io/embed/job_app?token=999999999999"
    is_live, reason = job_validator.is_job_active(fake_url, timeout=5)
    assert is_live is False
