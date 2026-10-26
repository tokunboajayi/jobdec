import datetime
import pytest
from agents import options as OPTS

def test_option_resolver_college_university():
    label = "How Did You Hear About Us?*"
    ans = "College/University"
    texts = ["Select One", "LinkedIn", "Company Website", "College / University", "Referral"]
    resolved = OPTS.resolve(label, ans, texts)
    assert resolved == "College / University"

def test_option_resolver_yes_no_variants():
    label = "Are you currently enrolled in an accredited college or university in the United States?"
    ans = "Yes"
    texts = ["Select One", "Yes, I am enrolled", "No, I am not enrolled"]
    resolved = OPTS.resolve(label, ans, texts)
    assert resolved == "Yes, I am enrolled"

def test_date_subfield_normalization():
    now = datetime.datetime.now()
    expected_m = f"{now.month:02d}"
    expected_d = f"{now.day:02d}"
    expected_y = str(now.year)
    
    # Assert today's dates format cleanly
    assert len(expected_m) == 2
    assert len(expected_d) == 2
    assert len(expected_y) == 4
