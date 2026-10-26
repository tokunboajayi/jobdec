"""
Automated Job Portal Account Creation & Authentication Manager.
Handles automatic account registration, login, and email verification
for Workday, iCIMS, Taleo, and generic candidate portals.
"""
import os
import pathlib
import re
import time
from waits import settle
from dotenv import load_dotenv

HERE = pathlib.Path(__file__).resolve().parent
ENV_PATH = HERE.parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

GMAIL_USER = os.getenv("GMAIL_EMAIL") or os.getenv("GMAIL_USER") or ""
# Portal password comes ONLY from PORTAL_PASSWORD in .env. Never fall back to the Gmail password:
# that would type it into every ATS login page. If it's missing, auth screens pause for you.
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD", "").strip()

try:
    from gmail_auth import fetch_verification_code, fetch_verification_data
except ImportError:
    fetch_verification_code, fetch_verification_data = None, None

try:
    from account_verifier import verify_account_and_proceed, is_verification_waiting_screen
except ImportError:
    verify_account_and_proceed, is_verification_waiting_screen = None, None


def _activate_workday_from_gmail(page, wait_sec=0, job_url=""):
    """Open this tenant's 'Verify your candidate account' link (new, or left over from an earlier run), then return
    to the page we were on or proceed directly into the application form. Workday rejects sign-in for an account that was never activated."""
    try:
        from gmail_auth import find_activation_link
        m = re.search(r"https?://([^./]+)\.wd\d*\.myworkdayjobs\.com", page.url) or re.search(r"https?://([^./]+)\.", page.url)
        tenant = m.group(1) if m else ""
        link = find_activation_link(tenant, max_age_days=7, wait_sec=wait_sec)
        if not link:
            print(f"[Auth Manager] No activation email for '{tenant}' found.")
            return False
        if verify_account_and_proceed:
            return verify_account_and_proceed(page, link=link, tenant_hint=tenant, job_url=job_url or page.url)
        back = page.url
        print("[Auth Manager] Opening the account activation link...")
        page.goto(link, wait_until="domcontentloaded", timeout=30000)
        settle(page, 4)
        if "/apply" in page.url.lower():
            return True
        if job_url:
            page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
        else:
            page.goto(back, wait_until="domcontentloaded", timeout=30000)
        settle(page, 3)
        return True
    except Exception as e:
        print(f"[Auth Manager] Activation attempt note: {e}")
        return False


def is_auth_screen(page):
    """Checks if the page (or any child frame) is currently on a login, registration, or verification screen."""
    dismiss_cookie_banner(page)
    if is_verification_waiting_screen and is_verification_waiting_screen(page):
        return True
    try:
        if page.locator("[data-automation-id='pageFooterNextButton'], [data-automation-id='bottom-navigation-next-button']").is_visible():
            return False
    except Exception:
        pass

    try:
        if page.locator("[data-automation-id='SignInWithEmailButton'], button:has-text('Sign in with email')").first.is_visible(timeout=1000):
            return True
        if page.locator("[data-automation-id='createAccountSubmitButton']:visible, [data-automation-id='signInSubmitButton']:visible, [data-automation-id='signInLink']:visible, [data-automation-id='createAccountLink']:visible").count() > 0:
            return True
    except Exception:
        pass

    for f in page.frames:
        try:
            if any(x in f.url.lower() for x in ["captcha", "hcaptcha", "recaptcha", "onetrust"]):
                continue
            if f.locator("input[type=password]:visible").count() > 0:
                return True
            if f.locator("input[data-automation-id='verificationCode']:visible, input[name*='verification' i]:visible, input[autocomplete='one-time-code']:visible").count() > 0:
                body = f.inner_text("body", timeout=1500)
                if re.search(r"verification code|security code|passcode|sent a code", body, re.I):
                    return True
            # iCIMS email login screen
            if f.locator("input#email:visible, input[name='css_loginName']:visible").count() > 0 and f.locator("input#enterEmailSubmitButton:visible, input[type=submit]:visible").count() > 0:
                return True
        except Exception:
            pass

    return False



def dismiss_cookie_banner(page):
    """Dismisses GDPR/cookie banners on career sites that block form interactions."""
    try:
        btn = page.locator("[data-automation-id='legalNoticeAcceptButton'], button:has-text('Accept Cookies'), button:has-text('Accept All'), button:has-text('Accept all cookies'), button:has-text('I Accept'), button:has-text('Agree'), #onetrust-accept-btn-handler").first
        if btn.is_visible(timeout=1000):
            btn.click()
            time.sleep(1)
    except Exception:
        pass


def handle_workday_landing(page):
    dismiss_cookie_banner(page)
    """Handles Workday landing: clicks Apply Manually if present, or clicks Apply -> Apply Manually."""
    if "/apply" in page.url.lower():
        try:
            chooser = page.locator("[data-automation-id='SignInWithEmailButton'], button:has-text('Sign in with email')").first
            if chooser.is_visible(timeout=1000):
                print("[Auth Manager] Selecting 'Sign in with email' on Workday...")
                chooser.click()
                settle(page, 2)
        except Exception:
            pass
        return False
    try:
        # Give Workday SPA time to hydrate its dynamic UI
        try:
            page.wait_for_selector(
                "[data-automation-id='applyManually'], [data-automation-id='adventureButton'], [data-automation-id='applyButton'], "
                "[data-automation-id='jobPostingApplyButton'], a[href*='/apply'], button:has-text('Apply'), a:has-text('Apply')",
                timeout=4000
            )
        except Exception:
            pass

        # 1. Direct Apply Manually button (e.g. Home Depot, Cox, Invesco)
        apply_m = page.locator("[data-automation-id='applyManually'], a:has-text('Apply Manually'), button:has-text('Apply Manually')").first
        try:
            if apply_m.is_visible(timeout=1500):
                print("[Auth Manager] Selecting 'Apply Manually' on Workday...")
                apply_m.click()
                try:
                    page.locator("input[data-automation-id='email'], input[type=password]").first.wait_for(state="visible", timeout=4000)
                except Exception:
                    settle(page, 2)
                return True
        except Exception:
            pass

        # 2. Top-level Apply button
        top_apply = page.locator(
            "[data-automation-id='adventureButton'], a[data-automation-id='applyButton'], button[data-automation-id='applyButton'], "
            "[data-automation-id='jobPostingApplyButton'], [data-automation-id*='apply' i], a[href*='/apply'], "
            "button:has-text('Apply'), a:has-text('Apply')"
        ).first
        try:
            if top_apply.is_visible(timeout=3000):
                print("[Auth Manager] Found Workday Apply button, clicking...")
                top_apply.click()
                time.sleep(2)
                apply_m = page.locator("[data-automation-id='applyManually'], a:has-text('Apply Manually'), button:has-text('Apply Manually')").first
                try:
                    if apply_m.is_visible(timeout=4000):
                        print("[Auth Manager] Selecting 'Apply Manually'...")
                        apply_m.click()
                        try:
                            page.locator("input[data-automation-id='email'], input[type=password]").first.wait_for(state="visible", timeout=5000)
                        except Exception:
                            settle(page, 2)
                        return True
                except Exception:
                    pass
                if "/apply" in page.url.lower():
                    return True
        except Exception:
            pass
    except Exception as e:
        print(f"[Auth Manager] Note on Workday landing: {e}")
    return False




def handle_verification_screen(page, job_url=""):
    """Detects and fills 6-digit email verification / security code screens or follows activation links."""
    try:
        tenant_kw = ""
        try:
            url_match = re.search(r"https?://([^/]+)", page.url)
            if url_match:
                host = url_match.group(1).lower()
                if "oraclecloud" in host:
                    tenant_kw = "oracle"
                elif "myworkdayjobs" in host:
                    tenant_kw = host.split(".")[0]
                elif "greenhouse" in host:
                    tenant_kw = "greenhouse"
                elif "smartrecruiters" in host:
                    tenant_kw = "smartrecruiters"
                elif "icims" in host:
                    tenant_kw = "icims"
                else:
                    tenant_kw = host.split(".")[0]
        except Exception:
            pass

        body = page.inner_text("body", timeout=2000)
        is_verif = bool(re.search(r"verification code|security code|one-time passcode|passcode sent to|enter the code|confirm your email|activate your account|sent an email to|check your (?:inbox|email)|a verification link has been sent|confirm your identity", body, re.I))
        waiting = bool(is_verification_waiting_screen and is_verification_waiting_screen(page))
        if not is_verif and not waiting:
            return False

        print(f"\n[Auth Manager] >> Verification / Activation required by portal (tenant: '{tenant_kw or 'any'}').")
        if verify_account_and_proceed:
            return verify_account_and_proceed(page, email=GMAIL_USER, password=PORTAL_PASSWORD, timeout_sec=60, tenant_hint=tenant_kw, job_url=job_url)

        code, link = None, None
        if fetch_verification_data:
            code, link = fetch_verification_data(timeout_sec=60, search_term=tenant_kw)

        if link and ("activate" in link or "verify" in link):
            print(f"[Auth Manager] Navigating to account activation link: {link}")
            try:
                page.goto(link, wait_until="domcontentloaded", timeout=30000)
                settle(page, 4)
                return True
            except Exception as e:
                print(f"[Auth Manager] Activation link navigation error: {e}")

        if code:
            multi_digits = page.locator("input[aria-label*='digit' i], input[data-automation-id*='digit' i], input[placeholder*='digit' i], input[name*='digit' i]")
            if multi_digits.count() >= 6:
                print(f"[Auth Manager] Submitting multi-digit verification code: {code}")
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
                submit_btn = page.locator("button[data-automation-id='submitButton'], button:has-text('Submit'), button:has-text('Verify'), button:has-text('Continue')").first
                if submit_btn.is_visible(timeout=2000):
                    submit_btn.click()
                else:
                    multi_digits.last.press("Enter")
                settle(page, 5)
                return True

            code_input = page.locator("input[data-automation-id='verificationCode'], input[data-automation-id='securityCode'], input[autocomplete='one-time-code'], input[aria-label*='verification' i], input[aria-label*='security code' i]").first
            if not code_input.is_visible(timeout=2000):
                code_input = page.locator("input[type=text]:visible, input[type=number]:visible").first

            if code_input.is_visible(timeout=1000):
                print(f"[Auth Manager] Submitting verification code: {code}")
                code_input.fill(code)
                time.sleep(1)
                submit_btn = page.locator("button[data-automation-id='submitButton'], button:has-text('Submit'), button:has-text('Verify'), button:has-text('Continue')").first
                if submit_btn.is_visible(timeout=2000):
                    submit_btn.click()
                else:
                    code_input.press("Enter")
                settle(page, 5)
                return True
    except Exception as e:
        print(f"[Auth Manager] Note on verification screen: {e}")
    return False


def handle_workday_account_creation(page, email=GMAIL_USER, password=PORTAL_PASSWORD, allow_signin_retry=True, job_url=""):
    """Fills Workday Create Account fields and submits."""
    try:
        email_inp = page.locator("input[data-automation-id='email']").first
        pwd_inp = page.locator("input[data-automation-id='password']").first
        verify_pwd_inp = page.locator("input[data-automation-id='verifyPassword']").first
        terms_chk = page.locator("input[data-automation-id='createAccountCheckbox'], [data-automation-id='agreementCheckbox']").first
        filter_btn = page.locator("div[data-automation-id='click_filter']").first
        submit_btn = page.locator("[data-automation-id='createAccountSubmitButton'], button:has-text('Create Account')").first

        if pwd_inp.is_visible(timeout=2000) and verify_pwd_inp.is_visible(timeout=2000):
            print(f"[Auth Manager] Creating Workday Account with {email}...")
            if email_inp.is_visible():
                email_inp.fill(email)
            pwd_inp.fill(password)
            verify_pwd_inp.fill(password)

            if terms_chk.is_visible():
                try:
                    terms_chk.check(force=True)
                except Exception:
                    terms_chk.click(force=True)

            time.sleep(1)
            submitted_acct = False
            for loc in [filter_btn, submit_btn]:
                try:
                    if loc.is_visible(timeout=1000):
                        print("[Auth Manager] Clicking Create Account button...")
                        loc.click(force=True)
                        submitted_acct = True
                        break
                except Exception:
                    pass
            if not submitted_acct:
                pwd_inp.press("Enter")
            settle(page, 4)

            # Wait for transition to form or check for duplicate account / redirect to login
            for _ in range(10):
                time.sleep(1.5)
                try: body = page.inner_text("body")
                except Exception: body = ""

                # Only transition to Sign In if Workday explicitly says account already exists
                if re.search(r"an account with this email already exists|user name already exists|account already exists|already registered", body, re.I):
                    if not allow_signin_retry:
                        print("[Auth Manager] Account already exists but sign in already failed. Stopping.")
                        return False
                    print("[Auth Manager] Account exists. Switching to Sign In...")
                    sign_in_tab = page.locator("[data-automation-id='signInLink']").first
                    if sign_in_tab.is_visible():
                        sign_in_tab.click()
                        settle(page, 2)
                    return handle_workday_sign_in(page, email, password, allow_create_retry=False, job_url=job_url)

                # If verifyPassword field is gone, check if redirected to Sign In or into form
                if page.locator("input[data-automation-id='verifyPassword']:visible").count() == 0 and page.locator("input[data-automation-id='createAccountCheckbox']:visible").count() == 0:
                    # 1. Did it directly load the application form?
                    if page.locator("[data-automation-id='pageFooterNextButton'], [data-automation-id='bottom-navigation-next-button']").is_visible() or "/apply" in page.url.lower():
                        print("[Auth Manager] Workday account successfully created. Application form loaded directly!")
                        return True

                    # 2. Is there an actual verification waiting screen?
                    if is_verification_waiting_screen and is_verification_waiting_screen(page):
                        tenant_kw = ""
                        try:
                            url_match = re.search(r"https?://([^/]+)", page.url)
                            if url_match:
                                tenant_kw = url_match.group(1).split(".")[0]
                        except Exception:
                            pass

                        print(f"[Auth Manager] Workday account submitted. Verification screen detected! Listening for activation link in Gmail (tenant: {tenant_kw or 'any'})...")
                        if verify_account_and_proceed:
                            verified = verify_account_and_proceed(page, email=email, password=password, timeout_sec=40, tenant_hint=tenant_kw, job_url=job_url)
                            if verified:
                                print("[Auth Manager] Account verified via email. Checking if sign-in or form is active...")
                                if page.locator("input[type=password]:visible").count() > 0 or "login" in page.url.lower():
                                    return handle_workday_sign_in(page, email, password, allow_create_retry=False, job_url=job_url)
                                return True

                    pw_visible = page.locator("input[type=password]:visible").count()
                    if pw_visible == 1 or "login" in page.url.lower():
                        # Workday won't sign in a new account until its "Verify your candidate account" link is opened
                        print("[Auth Manager] Redirected to Sign In after registration. Activating the account from Gmail first...")
                        _activate_workday_from_gmail(page, wait_sec=90, job_url=job_url)
                        return handle_workday_sign_in(page, email, password, allow_create_retry=False, job_url=job_url)
                    print("[Auth Manager] Workday account successfully created. Proceeding to form...")
                    return True

            handle_verification_screen(page, job_url=job_url)
            return True
    except Exception as e:
        print(f"[Auth Manager] Error in Workday account creation: {e}")
    return False


def handle_workday_sign_in(page, email=GMAIL_USER, password=PORTAL_PASSWORD, allow_create_retry=True, _activated=False, job_url=""):
    """Signs into Workday or switches to Create Account if not registered."""
    try:
        dismiss_cookie_banner(page)
        # Check if chooser button "Sign in with email" is present
        try:
            chooser = page.locator("[data-automation-id='SignInWithEmailButton'], button:has-text('Sign in with email')").first
            if chooser.is_visible(timeout=1500):
                print("[Auth Manager] Selecting 'Sign in with email' on Workday...")
                chooser.click()
                settle(page, 2)
        except Exception:
            pass

        # Check if we need to switch view from Create Account to Sign In
        verify_pwd_inp = page.locator("input[data-automation-id='verifyPassword']").first
        if verify_pwd_inp.is_visible(timeout=2000):
            print("[Auth Manager] On Create Account tab. Switching to Sign In...")
            sign_in_tab = page.locator("[data-automation-id='signInLink']").first
            if sign_in_tab.is_visible():
                sign_in_tab.click(force=True)
            settle(page, 2)

        email_inp = page.locator("input[data-automation-id='email'], input[data-automation-id='userName'], input[type=email]").first
        pwd_inp = page.locator("input[data-automation-id='password'], input[type=password]").first
        filter_btn = page.locator("div[data-automation-id='click_filter']").first
        sign_in_btn = page.locator("button[data-automation-id='signInSubmitButton']").first

        try:
            pwd_inp.wait_for(state="visible", timeout=8000)
        except Exception:
            pass

        if email_inp.is_visible(timeout=3000) and pwd_inp.is_visible(timeout=3000):
            print(f"[Auth Manager] Attempting Workday Sign In for {email}...")
            email_inp.fill(email)
            pwd_inp.fill(password)
            time.sleep(1)

            sign_in_clicked = False
            for loc in [
                page.locator("button[data-automation-id='signInSubmitButton']:visible").first,
                page.locator("div[data-automation-id='click_filter']:visible").first,
                page.locator("button:has-text('Sign In'):visible").first,
                page.locator("button[type=submit]:visible").first,
            ]:
                try:
                    if loc.is_visible(timeout=1000):
                        loc.click(force=True)
                        sign_in_clicked = True
                        break
                except Exception:
                    pass
            if not sign_in_clicked:
                pwd_inp.press("Enter")

            # Wait until form or Step 2 is loaded
            for _ in range(12):
                time.sleep(1.5)
                try: body = page.inner_text("body")
                except Exception: body = ""

                # Check for bad credentials / locked account / no account
                if re.search(r"wrong email|wrong password|\baccount\s+is\s+locked\b|\baccount\s+might\s+be\s+locked\b", body, re.I):
                    # often an account created earlier but never activated: use its activation email, then retry once
                    if not _activated and _activate_workday_from_gmail(page, wait_sec=0 if allow_create_retry else 60, job_url=job_url):
                        return handle_workday_sign_in(page, email, password, allow_create_retry=allow_create_retry, _activated=True, job_url=job_url)
                    if not allow_create_retry:
                        print("[Auth Manager] Portal login failed and Create Account already attempted.")
                        return False
                    create_tab = page.locator("[data-automation-id='createAccountLink']").first
                    if create_tab.is_visible():
                        print("[Auth Manager] Sign in failed (unregistered or locked). Trying 'Create Account' first...")
                        create_tab.click(force=True)
                        settle(page, 3)
                        return handle_workday_account_creation(page, email, password, allow_signin_retry=False, job_url=job_url)
                    print("[Auth Manager] Portal login failed: wrong credentials or account locked on this site.")
                    return False

                if re.search(r"invalid|incorrect|no account|not recognized", body, re.I):
                    if not allow_create_retry:
                        print("[Auth Manager] Sign in failed and Create Account already attempted.")
                        return False
                    print("[Auth Manager] Sign in failed — switching to 'Create Account'...")
                    create_tab = page.locator("[data-automation-id='createAccountLink']").first
                    if create_tab.is_visible():
                        create_tab.click(force=True)
                        settle(page, 3)
                        return handle_workday_account_creation(page, email, password, allow_signin_retry=False, job_url=job_url)

                # Check for transient Workday error
                if re.search(r"something went wrong|please refresh the page", body, re.I):
                    print("[Auth Manager] Transient Workday error ('Something went wrong'). Reloading page...")
                    try:
                        page.reload()
                        settle(page, 3)
                    except Exception:
                        pass
                    continue

                # Check if transitioned to actual application form (password field must be gone)
                pw_gone = page.locator("input[type=password]:visible").count() == 0
                has_form = page.locator("[data-automation-id='pageFooterNextButton']:visible, [data-automation-id*='legalName'], [data-automation-id='contactInformationPage'], input[type=file]:visible").count() > 0
                if pw_gone and (has_form or re.search(r"step [2-9] of|my information|my experience", body, re.I) or "candidatehome" in page.url.lower()):
                    print("[Auth Manager] Workday sign in successful. Form loaded.")
                    if "candidatehome" in page.url.lower() and job_url:
                        print(f"[Auth Manager] On candidatehome dashboard. Navigating directly to target job: {job_url}")
                        page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                        settle(page, 3)
                    handle_verification_screen(page, job_url=job_url)
                    return True

            handle_verification_screen(page, job_url=job_url)
            if page.locator("input[type=password]:visible").count() == 0:
                return True

            if not allow_create_retry:
                if not _activated and _activate_workday_from_gmail(page, wait_sec=60, job_url=job_url):
                    return handle_workday_sign_in(page, email, password, allow_create_retry=False, _activated=True, job_url=job_url)
                print("[Auth Manager] Password field still visible and Create Account already tried.")
                return False

            create_tab = page.locator("[data-automation-id='createAccountLink']").first
            if create_tab.is_visible():
                print("[Auth Manager] Sign In did not advance. Switching to 'Create Account'...")
                create_tab.click()
                settle(page, 2.5)
                return handle_workday_account_creation(page, email, password, allow_signin_retry=False, job_url=job_url)

            print("[Auth Manager] Password field still visible — sign in did not complete.")
            return False
    except Exception as e:
        print(f"[Auth Manager] Error in Workday sign in: {e}")
    return False


def handle_generic_auth(page, email=GMAIL_USER, password=PORTAL_PASSWORD, job_url=""):
    """Handles generic candidate portal account creation and login."""
    try:
        pw_inputs = page.locator("input[type=password]:visible")
        pw_count = pw_inputs.count()
        if pw_count == 0:
            return False

        # If 2 password fields -> Registration / Create Account
        if pw_count >= 2:
            print(f"[Auth Manager] Generic registration form detected (2 password fields). Creating account for {email}...")
            email_input = page.locator("input[type=email]:visible, input[name*='email' i]:visible, input[id*='email' i]:visible").first
            if email_input.is_visible():
                email_input.fill(email)
            pw_inputs.nth(0).fill(password)
            pw_inputs.nth(1).fill(password)

            # Tick only a terms/privacy checkbox (never the first random one, e.g. marketing opt-ins)
            terms_label = re.compile(r"terms|privacy|i agree|i accept|acknowledge", re.I)
            boxes = page.locator("input[type=checkbox]:visible")
            for i in range(boxes.count()):
                box = boxes.nth(i)
                try:
                    lab = box.evaluate("e => (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.getAttribute('aria-label') || (e.closest('label') ? e.closest('label').innerText : '')")
                    if terms_label.search(lab or "") and not re.search(r"marketing|newsletter|sms|text message", lab or "", re.I):
                        box.check(force=True)
                except Exception:
                    pass

            time.sleep(1)
            # Submit button
            reg_btn = page.locator("button:has-text('Create Account'), button:has-text('Sign Up'), button:has-text('Register'), input[type=submit]").first
            if reg_btn.is_visible():
                reg_btn.click()
            else:
                pw_inputs.nth(1).press("Enter")
            settle(page, 4)
            handle_verification_screen(page, job_url=job_url)
            return True

        # If 1 password field -> Sign In form
        if pw_count == 1:
            print(f"[Auth Manager] Generic Sign In form detected. Attempting login for {email}...")
            email_input = page.locator("input[type=email]:visible, input[name*='user' i]:visible, input[name*='email' i]:visible, input[id*='user' i]:visible").first
            if email_input.is_visible():
                email_input.fill(email)
            pw_inputs.nth(0).fill(password)
            time.sleep(1)

            submit_btn = page.locator("button:has-text('Sign In'), button:has-text('Log In'), input[type=submit]").first
            if submit_btn.is_visible():
                submit_btn.click()
            else:
                pw_inputs.nth(0).press("Enter")
            settle(page, 4)

            # Check if login failed or account doesn't exist
            body = page.inner_text("body", timeout=2000)
            if re.search(r"invalid|incorrect|no account|not found", body, re.I):
                print("[Auth Manager] Login failed. Looking for 'Create Account' / 'Register' link...")
                create_link = page.locator("a:has-text('Create Account'), a:has-text('Register'), a:has-text('Sign Up'), button:has-text('Create Account')").first
                if create_link.is_visible():
                    create_link.click()
                    settle(page, 3)
                    return handle_generic_auth(page, email, password, job_url=job_url)
                return False

            handle_verification_screen(page, job_url=job_url)
            if page.locator("input[type=password]:visible").count() > 0:
                print("[Auth Manager] Generic sign in did not complete (password field still visible).")
                return False
            return True

    except Exception as e:
        print(f"[Auth Manager] Error in generic auth: {e}")
    return False


def run_auth_flow(page, email=GMAIL_USER, password=PORTAL_PASSWORD, job_url=""):
    """Main entrypoint: checks and resolves any authentication or account creation step."""
    if not password:
        print("[Auth Manager] PORTAL_PASSWORD is not set in .env - handing this screen to you.")
        return False
    dismiss_cookie_banner(page)
    # 1. First check if it's a Workday landing page
    if "myworkdayjobs.com" in page.url:
        handle_workday_landing(page)

    # 1b. Check for Workday modern "Sign in with email" choice screen
    try:
        chooser = page.locator("[data-automation-id='SignInWithEmailButton'], button:has-text('Sign in with email')").first
        if chooser.is_visible(timeout=1000):
            print("[Auth Manager] Workday chooser screen detected. Clicking 'Sign in with email'...")
            chooser.click()
            settle(page, 2)
    except Exception:
        pass

    # 2. Check for verification code screen
    if handle_verification_screen(page, job_url=job_url):
        return True

    # 3. Check iCIMS email login in any frame
    for f in page.frames:
        try:
            email_inp = f.locator("input#email:visible, input[name='css_loginName']:visible").first
            btn = f.locator("input#enterEmailSubmitButton:visible, input[type=submit]:visible").first
            if email_inp.is_visible(timeout=1000) and btn.is_visible(timeout=1000):
                print(f"[Auth Manager] iCIMS login detected. Submitting email {email}...")
                email_inp.fill(email)
                time.sleep(1)
                btn.click()
                settle(page, 4)
                return True
        except Exception:
            pass

    # 4. Check for Workday authentication
    if "myworkdayjobs.com" in page.url or page.locator("button[data-automation-id='signInSubmitButton']:visible, [data-automation-id='signInLink']:visible, button[data-automation-id='createAccountSubmitButton']:visible").count() > 0:
        # If on Create Account view, check if Sign In tab is visible and try signing in first
        sign_in_tab = page.locator("[data-automation-id='signInLink']").first
        if sign_in_tab.is_visible() and page.locator("input[data-automation-id='verifyPassword']:visible").count() > 0:
            print("[Auth Manager] On Workday Create Account screen. Attempting Sign In first...")
            try:
                sign_in_tab.click(force=True)
                settle(page, 2)
            except Exception:
                pass
        if page.locator("button[data-automation-id='signInSubmitButton']:visible").count() > 0 or (page.locator("input[type=password]:visible").count() == 1 and page.locator("input[data-automation-id='verifyPassword']:visible").count() == 0):
            return handle_workday_sign_in(page, email, password, job_url=job_url)
        if page.locator("input[data-automation-id='verifyPassword']:visible, button[data-automation-id='createAccountSubmitButton']:visible").count() > 0:
            return handle_workday_account_creation(page, email, password, job_url=job_url)

    # 6. Generic ATS auth
    if page.locator("input[type=password]:visible").count() > 0:
        return handle_generic_auth(page, email, password, job_url=job_url)

    return False
