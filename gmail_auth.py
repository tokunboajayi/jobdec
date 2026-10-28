"""
Gmail Automated Verification Helper.
Reads verification codes (6-digit PINs, OTPs) and confirmation links directly from Gmail via IMAP.
"""
import datetime
import email
import email.utils
from email.header import decode_header
import imaplib
import os
import pathlib
import re
import sys
import time
from dotenv import load_dotenv

# Load .env from workspace root or current folder
HERE = pathlib.Path(__file__).resolve().parent
ENV_PATH = HERE.parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

GMAIL_USER = os.getenv("GMAIL_EMAIL") or os.getenv("GMAIL_USER") or ""
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()


def get_imap_client(retries=3):
    """Connects to Gmail IMAP with a 16-character App Password (never the main Gmail password)."""
    if not GMAIL_APP_PASSWORD:
        return None, ("GMAIL_APP_PASSWORD not set in .env - you'll be asked to type the code instead "
                      "(create one at https://myaccount.google.com/apppasswords).")
    last_err = "Unknown error"
    for attempt in range(max(1, retries)):
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15)
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            return mail, "Connected"
        except Exception as e:
            last_err = str(e)
            if "AUTHENTICATIONFAILED" in last_err:
                return None, "Google rejected the App Password in GMAIL_APP_PASSWORD - regenerate it."
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
    return None, f"IMAP connection error: {last_err}"


def decode_str(val):
    if not val:
        return ""
    decoded, enc = decode_header(val)[0]
    if isinstance(decoded, bytes):
        try:
            return decoded.decode(enc or "utf-8", errors="ignore")
        except LookupError:  # charsets Python doesn't know, e.g. "unknown-8bit"
            return decoded.decode("utf-8", errors="ignore")
    return str(decoded)


def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition") or "")
            if ctype in ("text/plain", "text/html") and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    body += " " + payload.decode(errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="ignore")
    return body


WORD_BLACKLIST = {
    "valid", "hours", "please", "verify", "email", "address", "account",
    "expires", "within", "click", "below", "button", "candidate", "application",
    "identity", "thank", "regards", "access", "following", "security", "portal",
    "password", "passcode", "minute", "minutes"
}


def extract_code(text):
    """Finds a verification/security code in email text. Bare 6-digit numbers count only
    when the email is clearly a verification email (avoids grabbing phone/req/zip numbers)."""
    if not text:
        return None
    # Strip HTML and normalize whitespace
    text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
    # Normalize spaced or hyphenated 6-digit codes (e.g. "123 456" or "123-456")
    text = re.sub(r'\b([0-9]{3})[\s\-]([0-9]{3})\b', r'\1\2', text)

    # 1. High precision patterns targeting numeric codes
    num_patterns = [
        r"(?:one-time\s*(?:pass\s*)?code|pass\s*code|passcode|verification\s*code|security\s*code|confirmation\s*code)\s*(?:is|:)?\s*([0-9]{4,8})",
        r"\bcode\s+is\s*:?\s*([0-9]{4,8})\b",
        r"(?:use|enter)\s+(?:the\s+)?(?:following\s+)?(?:pass\s*code|code)?\s*:?\s*([0-9]{4,8})\b",
        r"(?:verification code|security code|confirmation code|one-time\s*(?:pass\s*)?code|passcode|confirm\s*(?:your\s+)?identity|\bpin\b|\botp\b)[^0-9a-zA-Z]{0,60}?\b([0-9]{4,8})\b",
    ]
    for pat in num_patterns:
        m = re.search(pat, text, re.I)
        if m:
            val = m.group(1).strip()
            if val.lower() not in WORD_BLACKLIST:
                return val

    # 2. Check for 6-digit candidate numbers in verification emails
    if re.search(r"verif|security code|one-time|passcode|pass\s*code|confirm\s*(?:your\s+)?identity|pin\b|otp\b", text, re.I):
        nums = [n for n in re.findall(r"(?<![\d-])([0-9]{6})(?![\d-])", text) if not n.startswith(("202", "201"))]
        if len(set(nums)) == 1:
            return nums[0]
        elif len(set(nums)) > 1:
            for n in nums:
                if re.search(r"(?:code|pin|passcode|pass\s*code|identity|otp)[^\d]{1,35}" + re.escape(n), text, re.I):
                    return n
            return nums[0]

    # 3. Alphanumeric patterns (checked against WORD_BLACKLIST and not pure alpha words)
    alpha_patterns = [
        r"(?:Copy and paste this code[^:]*:|security code field on your application:)\s*([a-zA-Z0-9]{6,10})",
        r"(?:verification\s*code|security\s*code|confirmation\s*code)\s*:\s*([0-9a-zA-Z]{4,8})",
    ]
    for pat in alpha_patterns:
        m = re.search(pat, text, re.I)
        if m:
            val = m.group(1).strip()
            if val.lower() not in WORD_BLACKLIST and not val.isalpha():
                return val
    return None


USED_LINKS_FILE = HERE / ".used_auth_links.txt"
USED_CODES_FILE = HERE / ".used_auth_codes.txt"

def is_link_used(link):
    if not USED_LINKS_FILE.exists():
        return False
    try:
        used = set(USED_LINKS_FILE.read_text(encoding="utf-8").splitlines())
        return link.strip() in used
    except Exception:
        return False

def mark_link_used(link):
    try:
        with open(USED_LINKS_FILE, "a", encoding="utf-8") as f:
            f.write(link.strip() + "\n")
    except Exception:
        pass

def is_code_used(code):
    if not code or not USED_CODES_FILE.exists():
        return False
    try:
        used = set(USED_CODES_FILE.read_text(encoding="utf-8").splitlines())
        return code.strip() in used
    except Exception:
        return False

def mark_code_used(code):
    if not code:
        return
    try:
        with open(USED_CODES_FILE, "a", encoding="utf-8") as f:
            f.write(code.strip() + "\n")
    except Exception:
        pass


import html

def clean_url(url):
    """Unescapes HTML entities, strips trailing HTML tags, brackets, and punctuation from URL."""
    if not url:
        return ""
    url = html.unescape(url.strip())
    # Strip any trailing HTML tag fragments (e.g. <br>, </div>, </a>)
    url = re.sub(r'</?(?:br|div|p|span|a)[^>]*>.*$', '', url, flags=re.I)
    # Strip trailing quotes, angle brackets, whitespace
    url = re.sub(r'[\s\'"<>]+$', '', url)
    # Strip trailing punctuation that gets caught in plain text
    url = re.sub(r'[\.,;\)]+$', '', url)
    return url.strip()


def extract_verification_link(text):
    """
    Finds activation or verification links in email text or HTML, skipping previously used links.
    Handles Workday, Greenhouse, SmartRecruiters, Taleo, iCIMS, Oracle Cloud, and general ATS links.
    """
    if not text:
        return None

    candidates = []

    # 1. Inspect HTML anchor tags
    anchor_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.DOTALL)
    for m in anchor_pattern.finditer(text):
        href = clean_url(m.group(1))
        anchor_text = re.sub(r'<[^>]+>', ' ', m.group(2)).strip().lower()
        if not href.startswith("http"):
            continue
        # Skip image assets or CDN image URLs
        if re.search(r'\.(?:png|jpg|jpeg|gif|svg|webp)(?:\?|$)|wday/image|myworkdaycdn\.com', href, re.I):
            continue
        # Check if anchor text indicates account activation or email verification
        if re.search(r"activate|verify|confirm|complete\s*(?:your\s+)?(?:registration|setup|application)|validate|get\s*started|click\s*here|access\s*(?:your\s+)?application|continue\s*(?:your\s+)?application", anchor_text, re.I):
            candidates.append(href)
        elif re.search(r"/activate/|/verify|/confirm|token=|action=verify|email-universal", href, re.I):
            candidates.append(href)

    # 2. Plaintext Workday activation endpoints
    wd_urls = re.findall(r'https?://[^\s"\'<>]*myworkdayjobs\.com[^\s"\'<>]+/activate/[^\s"\'<>]+', text, re.I)
    for u in wd_urls:
        candidates.append(clean_url(u))

    # 3. URLs immediately following an activation/verification instruction
    follow_urls = re.findall(r'(?:confirm|verify|activate|complete setup|click this link|click here)[^\n<]{0,100}?(?:<br\s*/?>|\n|\s)+(https?://[^\s"\'<>]+)', text, re.I)
    for u in follow_urls:
        candidates.append(clean_url(u))

    # 4. Raw activation/verification URLs
    raw_urls = re.findall(r'https?://[^\s"\'<>]+(?:/activate/[^\s"\'<>]*|/verify[^\s"\'<>]*|/confirm[^\s"\'<>]*|token=[^\s"\'<>]*|action=verify[^\s"\'<>]*)', text, re.I)
    for u in raw_urls:
        candidates.append(clean_url(u))

    # Exclude false positives: unsubscribe, privacy, terms, marketing trackers
    # Note: NEVER ignore known ATS domains, and DO NOT block employers like TransUnion!
    ignore_patterns = re.compile(
        r"unsubscribe|privacy|terms|opt-out|preferences|contact-us|cookie|support|help|"
        r"careers/login|facebook\.com|twitter\.com|linkedin\.com|instagram\.com|lendingtree|creditkarma|"
        r"experian\.com|equifax|chase\.com|capitalone|discover\.com|promotions|newsletter",
        re.I
    )

    ats_domains = ("myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "oraclecloud.com", "icims.com", "ashbyhq.com", "jobvite.com")

    for cand in candidates:
        if not cand:
            continue
        # Never select image URLs
        if re.search(r'\.(?:png|jpg|jpeg|gif|svg|webp)(?:\?|$)|wday/image|myworkdaycdn\.com', cand, re.I):
            continue
        is_ats = any(d in cand.lower() for d in ats_domains)
        if not is_ats and ignore_patterns.search(cand):
            continue
        if not is_link_used(cand):
            return cand

    return None


def fetch_verification_data(timeout_sec=60, poll_interval=3, search_term="", require_code=False, require_link=False):
    """
    Polls Gmail for a verification code (PIN/OTP) OR an activation link.
    Returns (code, link).
    Features smart fuzzy matching for company / ATS tenants with a reliable fallback
    to the most recent valid OTP arriving during this application window.
    """
    print(f"[Gmail Auth] Listening for verification email on {GMAIL_USER} (max {timeout_sec}s, filter='{search_term or 'any'}')...")
    start = time.time()
    since = time.strftime("%d-%b-%Y", time.gmtime(start - 86400))

    mail, err = get_imap_client(retries=3)
    if not mail or mail is None:
        print(f"[Gmail Auth] Note: {err}")
        return None, None
    imap_session = mail

    def uids_since():
        try:
            imap_session.select("INBOX")
            _, data = imap_session.uid("search", None, f"(SINCE {since})")  # type: ignore
            return set(data[0].split()) if data and data[0] else set()
        except Exception:
            return set()

    try:
        baseline = uids_since()
        # Look back up to 60 most recent existing UIDs to catch emails delivered right before/during baseline
        sorted_base = sorted(baseline, key=int, reverse=True)
        recent_check = set(sorted_base[:60])
    except Exception as e:
        print(f"[Gmail Auth] Could not read inbox: {e}")
        return None, None

    code, link = None, None
    checked_uids = set()
    fallback_candidates = []

    while time.time() - start < timeout_sec and not (code or link):
        try:
            current_uids = uids_since()
            new_uids = current_uids - baseline
            # Candidates: strictly new UIDs first, followed by recent_check fallback
            candidates = sorted(new_uids, key=int, reverse=True) + sorted(recent_check, key=int, reverse=True)
            for uid in candidates:
                if time.time() - start > timeout_sec:
                    break  # fetching up to 60 full emails ignored the limit: a "6s" check ran for minutes
                if uid in checked_uids:
                    continue
                checked_uids.add(uid)
                try:
                    _, raw = imap_session.uid("fetch", uid, "(BODY.PEEK[])")
                except Exception:
                    continue
                if not raw or not raw[0] or not isinstance(raw[0], tuple):
                    continue
                msg = email.message_from_bytes(raw[0][1])

                # Check email age (ignore if older than 15 minutes / 900s)
                msg_age_sec = 0
                date_hdr = msg.get("Date")
                if date_hdr:
                    try:
                        msg_dt = email.utils.parsedate_to_datetime(date_hdr)
                        now_utc = datetime.datetime.now(datetime.timezone.utc)
                        if msg_dt.tzinfo is None:
                            msg_dt = msg_dt.replace(tzinfo=datetime.timezone.utc)
                        msg_age_sec = (now_utc - msg_dt).total_seconds()
                        if msg_age_sec > 900:  # Older than 15 minutes
                            continue
                    except Exception:
                        pass

                subj = decode_str(msg.get("Subject", ""))
                sender = decode_str(msg.get("From", ""))
                body = extract_body(msg)
                full_text = subj + "\n" + sender + "\n" + body

                if not re.search(
                    r"verif|security code|passcode|confirm\s*(?:your\s+)?(?:identity|email|account)|"
                    r"activate\s*(?:your\s+)?account|candidate account|one-time\s*(?:pass\s*)?(?:code|pin|password)|"
                    r"complete your application|continue your application|almost there",
                    full_text, re.I
                ):
                    continue

                # Check company or ATS matching
                term_matched = False
                if search_term:
                    clean_term = re.sub(r'([a-z])([A-Z])', r'\1 \2', search_term)
                    st_words = [w for w in re.split(r'[\s\-_]+', clean_term.lower()) if len(w) >= 3 and w not in ('the', 'inc', 'corp', 'llc', 'ltd', 'intern', 'engineering', 'analytics', 'company', 'position', 'internship', 'summer')]
                    norm_term = re.sub(r'[^a-z0-9]', '', search_term.lower())
                    norm_full = re.sub(r'[^a-z0-9]', '', full_text.lower())
                    term_matched = (any(w in full_text.lower() for w in st_words) or (norm_term in norm_full)) if st_words else (norm_term in norm_full)

                    # Also match known ATS domains/senders if search_term or full_text references an ATS
                    ats_keywords = ('oracle', 'oraclecloud', 'workday', 'myworkday', 'greenhouse', 'smartrecruiters', 'taleo', 'icims', 'lever', 'jobvite', 'ashby')
                    if any(k in search_term.lower() for k in ats_keywords) and any(k in full_text.lower() for k in ats_keywords):
                        term_matched = True
                else:
                    term_matched = True

                cand_code = extract_code(full_text)
                cand_link = extract_verification_link(full_text)

                valid_code = cand_code if (cand_code and not is_code_used(cand_code)) else None
                valid_link = cand_link if (cand_link and not is_link_used(cand_link)) else None

                # Enforce caller expectations
                if require_code and not valid_code:
                    continue
                if require_link and not valid_link:
                    continue

                if valid_code or valid_link:
                    if term_matched:
                        code, link = valid_code, valid_link
                        if code: mark_code_used(code)
                        print(f"[Gmail Auth] Matched verification email: '{subj[:45]}' (Code: {code}, Link: {bool(link)})")
                        break
                    elif valid_code and not search_term:
                        # Fallback only for codes when we have no company to match. Never for links: with parallel
                        # workers this took another site's Workday activation link (that account then never activated).
                        fallback_candidates.append((uid, valid_code, None, subj, msg_age_sec))

            # If we didn't find an exact term match, but we have a fresh fallback candidate (received recently)
            # and we've polled for at least 8 seconds or checked all new UIDs
            if not (code or link) and fallback_candidates:
                if time.time() - start > 8 or not new_uids:
                    # Pick the freshest fallback candidate
                    fallback_candidates.sort(key=lambda x: x[4])  # sort by msg_age_sec ascending (freshest first)
                    fb_uid, fb_code, fb_link, fb_subj, _ = fallback_candidates[0]
                    code, link = fb_code, fb_link
                    if code: mark_code_used(code)
                    print(f"[Gmail Auth] Using fallback verification email: '{fb_subj[:45]}' (Code: {code}, Link: {bool(link)})")
                    break

        except Exception as e:
            print(f"[Gmail Auth] Polling tick note: {e}")
            mail, err = get_imap_client(retries=2)
            if not mail:
                time.sleep(2)
        if not (code or link):
            time.sleep(poll_interval)

    try:
        if mail: mail.logout()
    except Exception: pass
    return code, link


def find_activation_link(tenant, max_age_days=7, wait_sec=0, poll_interval=5):
    """Newest unused account-activation link for one employer tenant (e.g. 'spgi' for spgi.wd5.myworkdayjobs.com).
    Unlike fetch_verification_data this also finds emails from earlier runs (accounts created but never
    activated), and searches All Mail so archived/categorised mail counts. Optionally waits for a new one."""
    tenant = (tenant or "").lower().strip()
    if not tenant:
        return None
    tenant_words = [w for w in re.split(r'[\s\-_]+', tenant) if len(w) >= 3 and w not in ('careers', 'external', 'jobs', 'corp', 'inc')]
    since = time.strftime("%d-%b-%Y", time.gmtime(time.time() - max_age_days * 86400))
    end = time.time() + wait_sec
    while True:
        mail, err = get_imap_client(retries=2)
        if mail:
            try:
                for box in ('"[Gmail]/All Mail"', "INBOX"):
                    if mail.select(box, readonly=True)[0] == "OK":
                        break
                _, d = mail.uid("search", None, f'(SINCE {since} OR OR SUBJECT "verify" SUBJECT "activate" SUBJECT "candidate account")')  # type: ignore
                for uid in sorted(d[0].split() if d and d[0] else [], key=int, reverse=True)[:40]:
                    _, raw = mail.uid("fetch", uid, "(BODY.PEEK[])")
                    if not raw or not raw[0] or not isinstance(raw[0], tuple):
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    body = extract_body(msg)
                    full_text = (decode_str(msg.get("Subject", "")) + " " + decode_str(msg.get("From", "")) + " " + body).lower()
                    
                    # Match tenant either as whole or by primary keyword
                    matched = (tenant in full_text) or any(w in full_text for w in tenant_words)
                    if not matched:
                        continue
                    link = extract_verification_link(body)
                    if link and not is_link_used(link):
                        link_lower = link.lower()
                        link_matched = (tenant in link_lower) or any(w in link_lower for w in tenant_words) or ("myworkdayjobs.com" in link_lower)
                        if link_matched:
                            print(f"[Gmail Auth] Activation link found for '{tenant}': {decode_str(msg.get('Subject', ''))[:50]}")
                            return link
            except Exception as e:
                print(f"[Gmail Auth] Activation search note: {e}")
            finally:
                try: mail.logout()
                except Exception: pass
        if time.time() >= end:
            return None
        time.sleep(poll_interval)


def fetch_verification_code(timeout_sec=60, poll_interval=4, search_term=""):
    code, _ = fetch_verification_data(timeout_sec, poll_interval, search_term, require_code=True)
    return code


if __name__ == "__main__":
    print(f"Testing Gmail IMAP connection for: {GMAIL_USER}")
    client, msg = get_imap_client()
    if client:
        print("[SUCCESS] Connected to Gmail IMAP successfully!")
        try:
            client.logout()
        except Exception:
            pass
    else:
        print(f"[FAILED] {msg}")

