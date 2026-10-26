"""
Autonomous Account Verification & Confirmation Link Clicker.
Listens for activation emails sent to Gmail, opens and clicks verification
links in the browser context, confirms the account, and proceeds with application submission.
"""
import os
import pathlib
import re
import time
from dotenv import load_dotenv
from waits import settle

HERE = pathlib.Path(__file__).resolve().parent
ENV_PATH = HERE.parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

GMAIL_USER = os.getenv("GMAIL_EMAIL") or os.getenv("GMAIL_USER") or ""
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD", "").strip()

try:
    from gmail_auth import fetch_verification_data, mark_link_used
except ImportError:
    fetch_verification_data, mark_link_used = None, None


WAITING_SCREEN_PATTERNS = [
    r"check your (?:inbox|email)",
    r"(?:activation|verification|confirmation)\s*(?:email|link)\s*(?:has been\s*)?sent",
    r"sent\s*(?:an?\s*)?(?:activation|verification|confirmation)\s*(?:email|link)",
    r"click the link\s*(?:in|we sent)",
    r"verify your (?:email|candidate account|account)",
    r"activate your (?:candidate account|account)",
    r"a verification link has been sent",
    r"please verify your email address",
    r"email sent to confirm",
    r"we have sent an email with instructions",
]
WAITING_SCREEN_RE = re.compile("|".join(WAITING_SCREEN_PATTERNS), re.I)


def is_verification_waiting_screen(page):
    """Detects whether the page is currently stuck on an 'email verification link sent' waiting room."""
    try:
        body = page.inner_text("body", timeout=1500)
    except Exception:
        return False
    # If standard form navigation or 3+ input fields exist, it's an active form, not a waiting screen
    try:
        if page.locator("[data-automation-id='pageFooterNextButton']:visible, [data-automation-id='bottom-navigation-next-button']:visible").count() > 0:
            return False
        if page.locator("input:not([type=hidden]):visible").count() >= 3:
            return False
    except Exception:
        pass
    return bool(WAITING_SCREEN_RE.search(body))


def click_activation_triggers(v_page):
    """Finds and clicks any 'Activate', 'Confirm', 'Verify', or 'Continue' buttons on the activation landing page."""
    # Common selectors on activation landing pages
    selectors = [
        "[data-automation-id='activateButton']",
        "[data-automation-id='confirmButton']",
        "[data-automation-id='verifyButton']",
        "button:has-text('Activate Account')",
        "button:has-text('Activate')",
        "button:has-text('Confirm Email')",
        "button:has-text('Confirm Account')",
        "button:has-text('Confirm')",
        "button:has-text('Verify Email')",
        "button:has-text('Verify Account')",
        "button:has-text('Verify')",
        "button:has-text('Continue to Sign In')",
        "button:has-text('Proceed to Application')",
        "button:has-text('Continue')",
        "button:has-text('Complete Registration')",
        "a:has-text('Activate Account')",
        "a:has-text('Confirm Email')",
        "a:has-text('Verify Email')",
        "a:has-text('Sign In')",
        "button:has-text('Sign In')",
    ]
    for sel in selectors:
        try:
            btn = v_page.locator(sel).first
            if btn.is_visible(timeout=1200):
                txt = btn.inner_text().strip() or sel
                print(f"[Account Verifier] Clicking activation button: '{txt}'")
                btn.click()
                settle(v_page, 2.5)
                return True
        except Exception:
            pass
    return False


def verify_account_and_proceed(page, link=None, code=None, email=GMAIL_USER, password=PORTAL_PASSWORD, timeout_sec=60, tenant_hint="", job_url=""):
    """
    Automates the entire email verification process:
    1. Fetches link or 6-digit code from Gmail via IMAP if not provided.
    2. Opens and clicks the verification link in the browser context.
    3. Clicks any confirmation / activation buttons.
    4. Completes any required post-activation sign in.
    5. Returns user to the application flow to proceed with submission.
    """
    print(f"\n[Account Verifier] Starting account verification (listening to {email}, timeout={timeout_sec}s)...")
    if not link and not code and fetch_verification_data:
        code, link = fetch_verification_data(timeout_sec=timeout_sec, poll_interval=3, search_term=tenant_hint)

    # Case A: 6-digit PIN / verification code
    if code and not link:
        print(f"[Account Verifier] Verification code received: {code}")
        try:
            # Check for multi-digit input boxes (e.g. 6 single-digit inputs)
            multi_digits = page.locator("input[aria-label*='digit' i], input[data-automation-id*='digit' i], input[placeholder*='digit' i], input[name*='digit' i]")
            if multi_digits.count() >= 6:
                print(f"[Account Verifier] Filling multi-digit verification inputs (count={multi_digits.count()})...")
                for idx in range(min(multi_digits.count(), len(code))):
                    try:
                        inp = multi_digits.nth(idx)
                        inp.fill(code[idx])
                        inp.dispatch_event("input")
                        inp.dispatch_event("change")
                        time.sleep(0.08)
                    except Exception:
                        pass
                time.sleep(0.8)
                sub_btn = page.locator("button[data-automation-id='submitButton'], button:has-text('Submit'), button:has-text('Verify'), button:has-text('Continue'), button:has-text('Sign In')").first
                if sub_btn.is_visible():
                    sub_btn.click()
                else:
                    multi_digits.last.press("Enter")
                settle(page, 4)
                return True

            code_input = page.locator("input[data-automation-id='verificationCode'], input[data-automation-id='securityCode'], input[autocomplete='one-time-code'], input[aria-label*='verification' i], input[aria-label*='security code' i], input[name*='code' i], input[placeholder*='code' i]").first
            if not code_input.is_visible(timeout=1500):
                code_input = page.locator("input[type=text]:visible, input[type=number]:visible").first
            if code_input.is_visible(timeout=1000):
                print(f"[Account Verifier] Typing verification code into input...")
                code_input.fill(code)
                time.sleep(0.8)
                sub_btn = page.locator("button[data-automation-id='submitButton'], button:has-text('Submit'), button:has-text('Verify'), button:has-text('Continue'), button:has-text('Sign In')").first
                if sub_btn.is_visible():
                    sub_btn.click()
                else:
                    code_input.press("Enter")
                settle(page, 4)
                return True
        except Exception as e:
            print(f"[Account Verifier] Error filling verification code: {e}")

    # Case B: Activation / confirmation link
    if not link:
        print("[Account Verifier] No verification link or code found in Gmail within timeout.")
        return False

    print(f"[Account Verifier] >> Automating activation link: {link}")

    # Use a new page in the SAME browser context so authentication cookies are shared
    v_page = None
    created_new_tab = False
    try:
        if hasattr(page, "context") and page.context:
            v_page = page.context.new_page()
            created_new_tab = True
        else:
            v_page = page

        print(f"[Account Verifier] Navigating browser to activation URL...")
        v_page.goto(link, wait_until="domcontentloaded", timeout=35000)
        settle(v_page, 3)

        # 1. Click any activation triggers on the landing page
        click_activation_triggers(v_page)

        # 2. Check if the activation landing page asks to sign in to confirm
        try:
            pwd_inp = v_page.locator("input[data-automation-id='password'], input[type=password]:visible").first
            if pwd_inp.is_visible(timeout=2000):
                print("[Account Verifier] Activation page requires sign-in. Completing login...")
                email_inp = v_page.locator("input[data-automation-id='email'], input[data-automation-id='userName'], input[type=email]:visible").first
                if email_inp.is_visible():
                    email_inp.fill(email)
                pwd_inp.fill(password)
                time.sleep(1)
                sign_btn = v_page.locator("button[data-automation-id='signInSubmitButton'], button:has-text('Sign In'), button:has-text('Log In')").first
                if sign_btn.is_visible():
                    sign_btn.click()
                else:
                    pwd_inp.press("Enter")
                settle(v_page, 4)
        except Exception as e:
            print(f"[Account Verifier] Note on sign-in after activation: {e}")

        # 3. Check for verification confirmation text
        try:
            v_body = v_page.inner_text("body", timeout=2000)
            if re.search(r"account (?:has been |is )?(?:activated|verified|confirmed)|email (?:has been )?verified|registration complete|thank you for verifying", v_body, re.I):
                print("[Account Verifier] [SUCCESS] Account successfully verified and activated!")
        except Exception:
            pass

        # 4. If opened in a new tab, transition back to the main application flow:
        if created_new_tab:
            is_form_in_vpage = v_page.locator("[data-automation-id='pageFooterNextButton']:visible, [data-automation-id*='legalName']:visible, input[type=file]:visible").count() > 0
            if is_form_in_vpage or "/apply" in v_page.url.lower():
                print(f"[Account Verifier] Activation redirected to application form ({v_page.url}). Navigating main page to form...")
                page.goto(v_page.url, wait_until="domcontentloaded", timeout=25000)
                settle(page, 3)
            elif job_url and not any(k in page.url.lower() for k in ("/apply", "/jobs/")):
                print(f"[Account Verifier] Account activated. Navigating main page to job application URL ({job_url})...")
                page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                settle(page, 3)
            else:
                # Reload or advance main page to refresh authenticated session
                print("[Account Verifier] Account activated. Refreshing main application page...")
                page.bring_to_front()
                try:
                    verified_btn = page.locator("button:has-text('I verified'), button:has-text('I have verified'), button:has-text('Continue'), button:has-text('Check Status')").first
                    if verified_btn.is_visible(timeout=1000):
                        verified_btn.click()
                    elif job_url:
                        page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                    else:
                        page.reload()
                except Exception:
                    page.reload()
                settle(page, 3)

            try:
                v_page.close()
            except Exception:
                pass
        else:
            if job_url and "/apply" not in page.url.lower():
                print(f"[Account Verifier] Account activated in-place. Navigating to job application URL ({job_url})...")
                page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                settle(page, 3)

        # Mark link as used now that activation execution succeeded
        if mark_link_used:
            mark_link_used(link)

        return True
    except Exception as e:
        print(f"[Account Verifier] Error executing verification flow: {e}")
        if created_new_tab and v_page:
            try: v_page.close()
            except Exception: pass
    return False


def check_post_submit_verification(page, company="", timeout_sec=12):
    """
    Checks if a post-submission email verification link or confirmation was sent.
    If found, opens and activates it in the background browser context.
    """
    if not fetch_verification_data:
        return False
    print(f"[Account Verifier] Checking for post-submit email confirmation (max {timeout_sec}s)...")
    code, link = fetch_verification_data(timeout_sec=timeout_sec, poll_interval=3, search_term=company, require_link=True)
    if link:
        print(f"[Account Verifier] Found post-submission confirmation link: {link}")
        return verify_account_and_proceed(page, link=link)
    return False

