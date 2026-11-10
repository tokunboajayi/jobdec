#!/usr/bin/env python3
"""
Interactive Setup Wizard & Onboarding Guide for Job Deck
Guides new users step-by-step through configuring their candidate profile,
resumes, Telegram bot, Gmail recruiter radar, and dependencies.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BANNER = """
========================================================================
             AJ AUTONOMOUS APPLICATION ENGINE & JOB DECK
                     Step-by-Step Setup Wizard
========================================================================
"""


def clear_screen():
    os.system("cls" if sys.platform == "win32" else "clear")


def print_step_header(step_num: int, title: str):
    print(f"\n[Step {step_num}/5] {title}")
    print("-" * 68)


def check_python_and_deps() -> bool:
    print_step_header(1, "Environment & Dependencies Check")
    py_ver = sys.version_info
    print(f"• Python Version: {py_ver.major}.{py_ver.minor}.{py_ver.micro}", end=" ")
    if py_ver >= (3, 10):
        print("[OK]")
    else:
        print("[WARNING: Python 3.10+ recommended]")

    # Check key packages
    required_packages = ["psutil", "playwright", "dotenv", "telegram"]
    missing = []
    for pkg in required_packages:
        try:
            __import__(pkg)
            print(f"• Package '{pkg}': [OK]")
        except ImportError:
            print(f"• Package '{pkg}': [MISSING]")
            missing.append(pkg)

    if missing:
        print(f"\nInstalling missing packages: {', '.join(missing)}...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=str(ROOT), check=True)
            print("Installed dependencies successfully.")
        except Exception as e:
            print(f"Pip install error: {e}")
            return False

    # Check Playwright Chromium
    print("• Checking Playwright Chromium browser binary...", end=" ")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        print("[OK]")
    except Exception:
        print("[INSTALLING NOW]")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            print("Chromium browser installed successfully.")
        except Exception as e:
            print(f"Error installing Chromium: {e}")
            return False

    return True


def check_or_setup_profile() -> bool:
    print_step_header(2, "Candidate Profile Verification (profile.json)")
    profile_path = ROOT / "profile.json"
    data = {}
    if profile_path.exists():
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    facts = data.get("facts", {})
    name = facts.get("legal_name") or facts.get("first_name", "") + " " + facts.get("last_name", "")
    email = facts.get("email", "")
    school = facts.get("education_school", "")
    major = facts.get("education_major", "")
    degree = facts.get("education_degree", "")
    gpa = facts.get("education_gpa", "")

    print(f"• Candidate:     {name if name.strip() else '[Not Set]'}")
    print(f"• Email:         {email if email else '[Not Set]'}")
    print(f"• University:    {school if school else '[Not Set]'}")
    print(f"• Degree/Major:  {degree} in {major if major else '[Not Set]'}")
    print(f"• GPA:           {gpa if gpa else '[Not Set]'}")

    if not name.strip() or not email:
        print("\nCandidate profile needs setup. Let's enter your core facts:")
        c_name = input("Enter Full Name: ").strip() or "Michael Azuka"
        c_email = input("Enter Email Address: ").strip() or "mazuka146@gmail.com"
        c_phone = input("Enter Phone Number: ").strip() or "404-645-0373"
        c_school = input("Enter University/College: ").strip() or "Kennesaw State University"
        c_degree = input("Enter Degree (e.g. Bachelor of Science): ").strip() or "Bachelor of Science"
        c_major = input("Enter Major (e.g. Cybersecurity): ").strip() or "Cybersecurity"
        c_gpa = input("Enter GPA (e.g. 3.35): ").strip() or "3.35"

        facts.update({
            "legal_name": c_name,
            "email": c_email,
            "phone": c_phone,
            "education_school": c_school,
            "education_degree": c_degree,
            "education_major": c_major,
            "education_gpa": c_gpa,
        })
        data["facts"] = facts
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print("profile.json saved successfully!")
    else:
        print("Candidate profile is fully verified!")

    return True


def check_resume() -> bool:
    print_step_header(3, "Master Resume Verification")
    res_candidates = [
        ROOT / "resumes" / "Candidate_Resume.pdf",
        ROOT / "resumes" / "master_resume.pdf",
        ROOT / "resumes" / "Resume.pdf"
    ]
    found = None
    for r in res_candidates:
        if r.exists():
            found = r
            break

    if found:
        print(f"• Master Resume Found: {found.relative_to(ROOT)} ({found.stat().st_size / 1024:.1f} KB) [OK]")
        return True
    else:
        print("• Master resume not found in resumes/ directory.")
        print("  Place your standard PDF resume at 'resumes/Candidate_Resume.pdf'.")
        return False


def check_env_credentials() -> bool:
    print_step_header(4, "Telegram & Email Credentials (.env)")
    env_path = ROOT / ".env"
    from dotenv import dotenv_values
    config = dotenv_values(env_path) if env_path.exists() else {}

    tg_token = config.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = config.get("TELEGRAM_CHAT_ID", "").strip()
    gmail_user = config.get("GMAIL_USER", "").strip()
    gmail_pass = config.get("GMAIL_APP_PASSWORD", "").strip()

    print(f"• Telegram Bot Token: {'[Configured]' if tg_token else '[MISSING]'}")
    print(f"• Telegram Chat ID:   {'[Configured]' if tg_chat else '[MISSING]'}")
    print(f"• Gmail User:         {gmail_user if gmail_user else '[Optional]'}")
    print(f"• Gmail App Password: {'[Configured]' if gmail_pass else '[Optional]'}")

    if not tg_token or not tg_chat:
        print("\nTelegram Bot is required for remote command & control.")
        print("1. Open Telegram and search for @BotFather.")
        print("2. Send /newbot and copy the API token.")
        print("3. Search for @userinfobot to get your numeric Chat ID.")
        token_input = input("Enter TELEGRAM_BOT_TOKEN (or press Enter to skip): ").strip()
        chat_input = input("Enter TELEGRAM_CHAT_ID (or press Enter to skip): ").strip()
        if token_input and chat_input:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nTELEGRAM_BOT_TOKEN={token_input}\nTELEGRAM_CHAT_ID={chat_input}\n")
            print(".env updated with Telegram credentials!")

    return True


def run_preflight_and_finish():
    print_step_header(5, "Pre-Flight Diagnostics & Ready to Run")
    print("Testing PC Optimizer priority setting...", end=" ")
    try:
        from agents.pc_optimizer import set_process_priority
        set_process_priority(os.getpid(), priority="below_normal")
        print("[OK]")
    except Exception as e:
        print(f"[NOTE: {e}]")

    print("\n" + "=" * 68)
    print("      CONGRATULATIONS! JOB DECK IS FULLY CONFIGURED.")
    print("=" * 68)
    print("\nYou can now start the system:")
    print("1. Run the Telegram Bot Control Panel:")
    print("   python telegram_bot_service.py")
    print("2. Run the Autonomous Parallel Applicator directly:")
    print("   python batch_apply_parallel.py --queue queue_cyber_iam.txt")
    print("3. Use Telegram commands:")
    print("   /setup    - Launch the interactive in-chat onboarding walkthrough")
    print("   /status   - View live milestone dashboard")
    print("   /run      - Start 3 parallel headless workers")
    print("   /turbo    - Start maximum dynamic workers")
    print("   /optimize - Free RAM and eliminate zombie browsers")
    print("=" * 68 + "\n")


def main():
    clear_screen()
    print(BANNER)
    check_python_and_deps()
    check_or_setup_profile()
    check_resume()
    check_env_credentials()
    run_preflight_and_finish()


if __name__ == "__main__":
    main()
