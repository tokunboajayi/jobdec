"""
Local application autofiller for AJ.
Usage:
    python fill.py "<application url>" [--resume path.pdf] [--company X --role Y] [--overwrite]

What it does:
  - Opens the application in a real, visible browser (your logins persist between runs).
  - Fills every field it can match from profile.json by typing like a person.
  - Uploads your resume to resume/CV upload fields.
  - Clicks Next/Submit by itself (default) ONLY when every required question on the page is answered;
    pauses for you on unknown questions, ASK answers, CAPTCHAs, logins, or validation errors.
    Use --review to make it stop on every page instead.
  - Lists anything it could not answer (and saves it to unanswered.json) so Claude can answer it later.
  - Detects the confirmation page and logs the application to ../applications.csv automatically.
"""
import argparse, csv, datetime, difflib, json, os, pathlib, re, sys, time
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")  # type: ignore # cp1252 pipes crashed on curly quotes
from dotenv import load_dotenv

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Playwright is not installed. Run setup.bat first.")

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent                                   # Job Applications folder
ENV_PATH = ROOT.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

try:
    from auth_manager import is_auth_screen, run_auth_flow, handle_workday_landing, dismiss_cookie_banner
except ImportError:
    is_auth_screen, run_auth_flow, handle_workday_landing, dismiss_cookie_banner = lambda p: False, lambda p: False, lambda p: False, lambda p: None

try:
    from ai_responder import generate_response, pick_best_option
except ImportError:
    generate_response = lambda q, field_type="text", options=None, company="", role="": ""
    pick_best_option = lambda q, options: ""

try:
    import results_engine as RE  # answer records, sensitive-question guard, sign-in lockout guard
except ImportError:
    RE = None
PICK_GUESSED = set()  # labels whose dropdown answer came from a fallback guess, not a rule
FIX_HINTS = []        # field labels the site flagged as invalid/required after the last Next click
try:
    from agents import options as OPTS  # answer -> option matching (months, yes/no year logic, aliases, embeddings)
except Exception:
    OPTS = None


def _hinted(label):
    """True if the site's last validation message names this field (so we re-answer it differently)."""
    k = " ".join(label.split()).lower().rstrip("*: ")[:45]
    return bool(k) and any(k in h for h in FIX_HINTS)

PROFILE =json.loads((HERE / "profile.json").read_text(encoding="utf-8"))
SKIP, ASK = None, "ASK"

SCAN_JS = r"""
() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     const isCheckOrRadio = e.type === 'radio' || e.type === 'checkbox' || e.type === 'file' || e.getAttribute('role') === 'checkbox' || e.getAttribute('role') === 'radio';
                     const pr = e.parentElement ? e.parentElement.getBoundingClientRect() : null;
                     const ps = e.parentElement ? getComputedStyle(e.parentElement) : null;
                     const parentVis = isCheckOrRadio && pr && pr.width > 0 && pr.height > 0 && ps && ps.visibility !== 'hidden' && ps.display !== 'none';
                     const hasDim = (r.width > 0 && r.height > 0) || parentVis;
                     const docTop = r.top + (window.pageYOffset || document.documentElement.scrollTop || 0);
                     const docLeft = r.left + (window.pageXOffset || document.documentElement.scrollLeft || 0);
                     return hasDim && s.visibility !== 'hidden' && s.display !== 'none' && (isCheckOrRadio || s.opacity !== '0')
                            && (parentVis || (docLeft >= -100 && docTop >= -100)) && e.getAttribute('aria-hidden') !== 'true'; };
  const txt = s => (s || '').replace(/\s+/g, ' ').trim();
  if (typeof window.__afn === 'undefined') {
    let maxId = 0;
    for (const el of document.querySelectorAll('[data-af-id]')) {
      const num = parseInt((el.dataset.afId || '').replace(/^af/, ''), 10);
      if (!isNaN(num) && num > maxId) maxId = num;
    }
    window.__afn = maxId;
  }
  const mark = e => { if (!e.dataset.afId) e.dataset.afId = 'af' + (++window.__afn); return e.dataset.afId; };
  const isGeneric = s => /^\s*(select(\s+one)?|choose(\s+one)?|options?|menu|required)\s*$/i.test((s || '').replace(/[*:\s]+/g, ' ').trim());
  const labelOf = e => {
    let t = '';
    if (e.id) {
      const origId = e.id.replace(/^s2id_/, '');
      const l = document.querySelector(`label[for="${CSS.escape(e.id)}"], label[for="${CSS.escape(origId)}"]`);
      if (l) t = l.innerText;
    }
    const s2c = e.closest('.select2-container');
    if (!t && s2c && s2c.id) {
      const origId = s2c.id.replace(/^s2id_/, '');
      const l = document.querySelector(`label[for="${CSS.escape(origId)}"]`);
      if (l) t = l.innerText;
    }
    if (!t && e.getAttribute('aria-labelledby')) t = e.getAttribute('aria-labelledby').split(/\s+/).map(i => document.getElementById(i)?.innerText || '').join(' ');
    const ariaLab = (e.getAttribute('aria-label') || '').trim();
    if (!t && ariaLab && !isGeneric(ariaLab)) t = ariaLab;
    if (!t) { const l = e.closest('label'); if (l) t = l.innerText; }
    if (!t) {
      let p = e.parentElement;
      for (let i = 0; i < 6 && p && !t; i++, p = p.parentElement) {
        const l = p.querySelector('label, [class*=label], [class*=Label]');
        if (l && !l.contains(e) && l.innerText.trim()) t = l.innerText;
      }
    }
    const fieldset = e.closest('fieldset');
    const isGenericLeg = (s) => /^(you are applying for|job application|application|personal information|candidate information|contact information|general information|profile|education|work experience|employment history)$/i.test((s || '').trim());
    if (!t && fieldset) {
      const fl = fieldset.querySelector('legend')?.innerText || '';
      if (!isGenericLeg(fl)) t = fl;
    }
    if (!t) t = e.placeholder || e.name || e.getAttribute('data-automation-id') || '';
    if (!t || /^(attach|browse|upload|choose file)$/i.test(t.trim())) {
      const upLab = e.id ? document.getElementById('upload-label-' + e.id) : null;
      if (upLab && txt(upLab.innerText)) {
        t = upLab.innerText;
      } else {
        const upGroup = e.closest('.file-upload, [role=group], .field-wrapper');
        const realLab = upGroup ? upGroup.querySelector('.upload-label, label:not(.visually-hidden), [class*=label]') : null;
        if (realLab && txt(realLab.innerText)) t = realLab.innerText;
      }
    }
    const leg = fieldset ? txt(fieldset.querySelector('legend')?.innerText || '') : '';
    if (leg && !isGenericLeg(leg) && (!t || isGeneric(t) || !t.toLowerCase().includes(leg.toLowerCase().replace(/\*/g, '').trim()))) {
      t = leg + (t && !isGeneric(t) ? ' ' + t : '');
    } else if (/startdate/i.test(e.id || '')) {
      t = 'From ' + t;
    } else if (/enddate/i.test(e.id || '')) {
      t = 'To ' + t;
    }
    const autoId = (e.getAttribute('data-automation-id') || '').trim();
    if (/countryphonecode|phonecountry/i.test(autoId)) t = 'Country Phone Code';
    else if (/phonedevicetype|devicetype/i.test(autoId)) t = 'Phone Device Type';
    else if (/datesectionmonth|month-input|\bmonth\b/i.test(autoId + ' ' + ariaLab) && !/month/i.test(t)) {
      t = (t ? t + ' ' : '') + 'Month';
    } else if (/datesectionday|day-input|\bday\b/i.test(autoId + ' ' + ariaLab) && !/day/i.test(t)) {
      t = (t ? t + ' ' : '') + 'Day';
    } else if (/datesectionyear|year-input|\byear\b/i.test(autoId + ' ' + ariaLab) && !/year/i.test(t)) {
      t = (t ? t + ' ' : '') + 'Year';
    } else if (ariaLab && !isGeneric(ariaLab) && (/country|code|device|type/i.test(ariaLab) && /phone/i.test(t))) {
      t = ariaLab;
    }
    if (e.tagName === 'SELECT' && e.options) {
      const optsText = [...e.options].map(o => (o.text || '').toLowerCase()).join(' ');
      if (/january|february|month\.\.\./.test(optsText) && !/month/i.test(t)) {
        t = (t ? t + ' ' : '') + 'Month';
      } else if ((/year\.\.\./.test(optsText) || [...e.options].some(o => /^\s*20\d\d\s*$/.test(o.text))) && !/year/i.test(t)) {
        t = (t ? t + ' ' : '') + 'Year';
      }
    }
    return txt(t).slice(0, 1000);
  };
  const out = [];
  for (const e of document.querySelectorAll('input,select,textarea,[role=checkbox]')) {
    const type = (e.type || (e.getAttribute('role') === 'checkbox' ? 'checkbox' : '')).toLowerCase();
    if (['hidden','submit','button','image','reset','radio','password','range'].includes(type)) continue;
    const lab = labelOf(e);
    const attrStr = ((e.name || '') + ' ' + (e.id || '') + ' ' + (e.className || '') + ' ' + (e.getAttribute('data-automation-id') || '') + ' ' + lab).toLowerCase();
    if (/honeypot|trap|hp_field|^hp$|website_hp|beecatcher|for robots only|do not (enter|fill)|leave this field blank|utilitymenu|search by keyword|search by location|^search\b|search jobs?|search postings/i.test(attrStr)) continue;
    if (type !== 'file' && !vis(e)) continue;
    if (type === 'file') {
      if (e.files && e.files.length) continue;
    }
    if (e.closest('#onetrust-consent-sdk, [id*=cookie], [class*=cookie]')) continue;
    out.push({ id: mark(e), tag: e.tagName.toLowerCase(), type, label: lab,
      name: e.name || '', elemId: e.id || '', placeholder: e.placeholder || '',
      required: e.required || e.getAttribute('aria-required') === 'true' || /\*/.test(lab),
      combobox: !/(?:dateWidget|calendarDialog|^date$)/i.test((e.getAttribute('data-automation-id') || '') + ' ' + (e.getAttribute('aria-haspopup') || '') + ' ' + type) && e.getAttribute('aria-haspopup') !== 'dialog' && (e.getAttribute('role') === 'combobox' || !!e.getAttribute('aria-autocomplete') || e.getAttribute('data-uxi-widget-type') === 'selectinput' || e.hasAttribute('aria-controls') || e.hasAttribute('aria-haspopup')),
      value: (() => {
        let v = e.tagName === 'SELECT' ? (e.selectedIndex > 0 ? txt(e.options[e.selectedIndex].text) : '')
                : (type === 'checkbox' ? (e.tagName === 'INPUT' ? (e.checked ? 'true' : 'false') : (e.checked || e.getAttribute('aria-checked') === 'true' ? 'true' : 'false')) : e.value);
        if (!v || /^[a-f0-9]{20,}$/i.test(v)) {
          let curr = e;
          for (let i = 0; i < 4 && curr; i++, curr = curr.parentElement) {
            const btn = curr.querySelector('button[aria-haspopup="listbox"]');
            if (btn) {
              const bt = txt(btn.innerText);
              if (bt && bt.length < 80 && (bt.match(/\+/g) || []).length <= 2) { v = bt; break; }
            }
            const sel = curr.querySelector('[data-automation-id="selectedItem"], [id*="pill"], [class*="single-value"], [class*="singleValue"], [class*="SingleValue"], [class*="selected-value"], [class*="selectedValue"]');
            if (sel) {
              const st = txt(sel.innerText || sel.getAttribute('aria-label') || '');
              if (st && st.length < 80 && (st.match(/\+/g) || []).length <= 2) { v = st; break; }
            }
          }
        }
        return v;
      })(),
      options: e.tagName === 'SELECT' ? [...e.options].map(o => txt(o.text)) : null });
  }
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio]')) {
    if (!vis(r) && !vis(r.parentElement)) continue;
    const k = r.name || ('g' + mark(r)); (groups[k] = groups[k] || []).push(r);
  }
  for (const [k, rs] of Object.entries(groups)) {
    const fs = rs[0].closest('fieldset'); let q = fs ? txt(fs.querySelector('legend')?.innerText || '') : '';
    if (!q) { let p = rs[0].parentElement;
      for (let i = 0; i < 7 && p; i++, p = p.parentElement) {
        if (rs.every(r => p.contains(r))) { const l = [...p.querySelectorAll('legend,label,[class*=question],[class*=label]')].find(l => !rs.some(r => l.contains(r))); if (l) { q = txt(l.innerText); break; } } } }
    if (/communicationconsent/i.test(k) || rs.some(r => r.closest('[class*=consent], [class*=Consent], [class*=texting]'))) {
      const cBox = rs[0].closest('[class*=consent], [class*=Consent], [class*=texting]');
      const cText = txt(cBox ? cBox.innerText : '');
      if (cText) q = 'Text Message Consent ' + (q || '');
    }
    out.push({ id: 'radio:' + k, tag: 'radio', type: 'radio', label: q.slice(0, 1000), required: /\*/.test(q),
      value: rs.find(r => r.checked) ? labelOf(rs.find(r => r.checked)) : '',
      options: rs.map(r => labelOf(r)), ids: rs.map(r => mark(r)) });
  }
  for (const lab of document.querySelectorAll('label, legend')) {
    const box = lab.parentElement; if (!box || !vis(lab)) continue;
    const bs = [...box.querySelectorAll('button')].filter(b => /^(yes|no)$/i.test(txt(b.innerText)));
    if (bs.length === 2) out.push({ id: 'yn:' + mark(lab), tag: 'buttons', type: 'yesno', label: txt(lab.innerText).slice(0, 1000),
      required: true, value: '', options: bs.map(b => txt(b.innerText)), ids: bs.map(b => mark(b)) });
  }
  for (const rg of document.querySelectorAll('[role=radiogroup]')) {
    if (!vis(rg)) continue;
    const rbtns = [...rg.querySelectorAll('[role=radio], button, input[type=radio]')];
    if (rbtns.length > 1) {
      const lab = labelOf(rg);
      out.push({ id: 'yn:' + mark(rg), tag: 'buttons', type: 'yesno', label: lab.slice(0, 1000),
        required: true, value: '', options: rbtns.map(b => txt(b.innerText || b.value || labelOf(b))), ids: rbtns.map(b => mark(b)) });
    }
  }
  for (const b of document.querySelectorAll('button[aria-haspopup=listbox], .select2-choice, a.select2-choice, [role=combobox]:not(input)')) {
    if (!vis(b)) continue; const lab = labelOf(b);
    out.push({ id: mark(b), tag: 'listbox', type: 'listbox', label: lab, required: /\*/.test(lab), value: txt(b.innerText), options: null });
  }
  return out;
}
"""


def rule_for(label):
    global PROFILE
    PROFILE = json.loads((HERE / "profile.json").read_text(encoding="utf-8"))  # live reload: edits apply without restarting
    lab = label.lower()
    lab_core = re.sub(r"[\s*:?]+$", "", lab.split(";")[0]).strip()
    for r in PROFILE["rules"]:
        q = r["q"]
        lit = re.sub(r"\\(.)", r"\1", q)
        if re.escape(lit) == q and len(lit) < 25:
            # a short learned label ("Date", "Location") must BE the question, not just appear in it:
            # 'Date' -> today's date used to answer "visa type and expiration date"
            if lab_core != lit.lower().strip(" *:?"):
                continue
        elif not re.search(q, lab, re.I):
            continue
        if True:
            a = r.get("a")
            if a in ("TODAY",) or (re.fullmatch(r"\d{2}/\d{2}/20\d\d", str(a or "")) and lit.lower().strip(" *:?") in ("date", "today's date", "todays date")):
                a = "TODAY"  # a learned 'Date' answer is always the actual day of the run, never a stale date
            if a == "TODAY":  # e.g. signature date: always the actual date of the run
                return {**r, "a": datetime.date.today().strftime("%m/%d/%Y")}
            elif a == "TODAY_DAY":
                d = datetime.date.today().day
                return {**r, "a": f"{d:02d}", "option": rf"^{d:02d}$|^{d}$"}
            elif a == "TODAY_MONTH":
                m = datetime.date.today().month
                return {**r, "a": f"{m:02d}", "option": rf"^{m:02d}$|^{m}$|October"}
            elif a == "TODAY_YEAR":
                y = datetime.date.today().year
                return {**r, "a": str(y), "option": rf"^{y}$"}
            return r
    return None


MONTHS_MAP = {
    "1": ("01", "1", "january", "jan"),
    "01": ("01", "1", "january", "jan"),
    "2": ("02", "2", "february", "feb"),
    "02": ("02", "2", "february", "feb"),
    "3": ("03", "3", "march", "mar"),
    "03": ("03", "3", "march", "mar"),
    "4": ("04", "4", "april", "apr"),
    "04": ("04", "4", "april", "apr"),
    "5": ("05", "5", "may"),
    "05": ("05", "5", "may"),
    "6": ("06", "6", "june", "jun"),
    "06": ("06", "6", "june", "jun"),
    "7": ("07", "7", "july", "jul"),
    "07": ("07", "7", "july", "jul"),
    "8": ("08", "8", "august", "aug"),
    "08": ("08", "8", "august", "aug"),
    "9": ("09", "9", "september", "sep", "sept"),
    "09": ("09", "9", "september", "sep", "sept"),
    "10": ("10", "october", "oct"),
    "11": ("11", "november", "nov"),
    "12": ("12", "december", "dec"),
}


def pick_option(options, rule, label=""):
    if not options:
        return None
    if rule and OPTS:
        hit = OPTS.resolve(label, rule.get("a"), options, rule.get("option"))
        if hit:
            return hit
    if rule:
        pat = rule.get("option") or re.escape(str(rule.get("a", "")))
        cands = [o for o in options if o and (re.search(pat, o, re.I) or re.search(pat, o.strip(), re.I))]
        if cands:  # exact, then whole-word, so "Male" never picks "Female"
            want = str(rule.get("a", "")).strip().lower()
            exact = [o for o in cands if o.strip().lower() == want]
            word = [o for o in cands if want and re.search(r"(?<![a-z])" + re.escape(want), o.strip(), re.I)]
            return (exact or word or cands)[0]
        ans = str(rule.get("a", "")).strip().lower()
        if ans in MONTHS_MAP:
            for syn in MONTHS_MAP[ans]:
                for o in options:
                    if o and re.search(rf"\b{syn}\b", o.strip(), re.I):
                        return o

        # Smart date-part extraction for month / year dropdowns
        is_month_dropdown = any(re.search(r"^(?:january|february|march|april|may|june|july|august|september|october|november|december|month\.\.\.)$", str(o).strip(), re.I) for o in options if o)
        is_year_dropdown = any(re.match(r"^20\d\d$", str(o).strip()) for o in options if o)

        if is_month_dropdown:
            m_val = None
            if ans == "today":
                import datetime
                m_val = str(datetime.date.today().month)
            else:
                date_m = re.search(r"\b(0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])?[-/](\d{4})\b", ans)
                if date_m:
                    m_val = date_m.group(1).lstrip("0") or "1"
                else:
                    month_names = {"jan": "1", "feb": "2", "mar": "3", "apr": "4", "may": "5", "jun": "6", "jul": "7", "aug": "8", "sep": "9", "oct": "10", "nov": "11", "dec": "12"}
                    for mn, mn_num in month_names.items():
                        if mn in ans:
                            m_val = mn_num
                            break
            if not m_val:
                m_val = "8" if "start" in label.lower() else "5"
            if m_val in MONTHS_MAP:
                for syn in MONTHS_MAP[m_val]:
                    for o in options:
                        if o and re.search(rf"\b{syn}\b", str(o).strip(), re.I):
                            return o

        if is_year_dropdown:
            y_val = None
            if ans == "today":
                import datetime
                y_val = str(datetime.date.today().year)
            else:
                y_m = re.search(r"\b(20\d\d)\b", ans)
                if y_m:
                    y_val = y_m.group(1)
            if not y_val:
                y_val = "2023" if ("start" in label.lower() and "education" in label.lower()) else "2027"
            for o in options:
                if str(o).strip() == y_val:
                    return o

        if ans in ("yes", "no"):
            for o in options:
                if o and re.search(rf"^\s*{ans}\b|\b{ans}\s*$", o.strip(), re.I):
                    return o
        if any(re.search(r"\+1\b|united states", str(o), re.I) for o in options if o):
            us_opt = next((o for o in options if o and re.search(r"united states|\+1\b|\busa?\b", str(o), re.I)), None)
            if us_opt:
                return us_opt
    # Sensitive question (legal / eligibility / EEO) and no rule option matched: never guess.
    if RE and RE.should_block(label):
        if RE.EEO_RE.search(label):
            dec = next((o for o in options if o and RE.DECLINE_RE.search(o)), None)
            if dec:
                return dec
        RE.SENSITIVE_HITS.append(label[:120])
        return None
    PICK_GUESSED.add(label)
    # Smart guessing fallback
    if label:
        best = pick_best_option(label, options)
        if best:
            return best
    # Filter placeholder options
    valid = [o for o in options if o and not re.match(r"^\s*(select|choose|please select|--\s*select\s*--|month\.\.\.|year\.\.\.|select\s+month|select\s+year)\s*$", str(o), re.I)]
    return valid[0] if valid else options[0]


def find_form_target(page):
    """Finds the page or active child iframe that contains the actual form inputs (e.g. iCIMS, Oracle iframes)."""
    for f in page.frames:
        try:
            if any(x in f.url.lower() for x in ["captcha", "hcaptcha", "recaptcha", "onetrust", "googletag", "cookie"]):
                continue
            if f.locator("input:not([type=hidden]), select, textarea").count() > 0:
                return f
        except Exception:
            pass
    return page


OPTION_SEL = "[data-automation-id='promptOption']:not([data-automation-id='selectedItem'] *), [role='listbox'] [role='option'], [role='option'], [role='treeitem'], [role='listbox'] li, .select2-results li, .select2-result, .select2-result-label, [id*='select2-result'], .autocomplete-suggestion, [class*='select__option'], [class*='option']:not(select *), div[id*='react-select'], [class*='menu'] [role='option'], [data-test-id*='option'], .oj-listbox-result, oj-option, [class*='oj-listbox-result'], .oj-select-results li"


def _visible_options(target):
    out = []
    # Check page-level for popups attached to body
    root = target.page if hasattr(target, "page") else target
    try:
        data = root.evaluate("""() => {
            const sel = "[data-automation-id='promptOption']:not([data-automation-id='selectedItem'] *), [role='listbox'] [role='option'], [role='option'], [role='treeitem'], [role='listbox'] li, .select2-results li, .select2-result, .select2-result-label, [id*='select2-result'], .autocomplete-suggestion, [class*='select__option'], [class*='option']:not(select *), div[id*='react-select'], [class*='menu'] [role='option'], [data-test-id*='option'], .oj-listbox-result, oj-option, [class*='oj-listbox-result'], .oj-select-results li";
            const els = [...document.querySelectorAll(sel)];
            const res = [];
            for (let i = 0; i < els.length && i < 300; i++) {
                const e = els[i];
                if (e.offsetParent !== null || e.getClientRects().length > 0) {
                    if (e.querySelector(sel)) continue;
                    const txt = (e.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (txt && !txt.toLowerCase().includes('delete to clear') && !txt.toLowerCase().includes('remove') && !/^no (?:options|results|matches)\b/i.test(txt)) {
                        if (txt.length > 150 && (txt.match(/\\+/g) || []).length > 2) continue;
                        res.push({ index: i, text: txt });
                    }
                }
            }
            return res;
        }""")
        opts = root.locator(OPTION_SEL)
        for item in data:
            out.append((item["text"], opts.nth(item["index"])))
        return out
    except Exception:
        pass
    opts = root.locator(OPTION_SEL)
    for i in range(min(opts.count(), 100)):
        o = opts.nth(i)
        try:
            if o.is_visible():
                txt = " ".join(o.inner_text(timeout=200).split())
                if txt and not any(bad in txt.lower() for bad in ["delete to clear", "remove", "no options", "no results", "no matches"]):
                    out.append((txt, o))
        except Exception:
            pass
    return out


def _best_option(options, want, pat, label=""):
    """Of the options matching the rule's pattern, pick the one closest to the answer, so
    'United States (+1)' picks 'United States of America (+1)', not '...Minor Outlying Islands (+1)'."""
    m = [(t, o) for t, o in options if re.search(pat, t, re.I)]
    if not m:
        clean_want = re.sub(r"[^\w\s]", "", want).strip().lower()
        m = [(t, o) for t, o in options if clean_want in t.lower() or (len(clean_want) > 3 and clean_want in re.sub(r"[^\w\s]", "", t).lower())]
    if not m and OPTS:
        r = OPTS.resolve(label, want, [t for t, _ in options])
        m = [x for x in options if x[0] == r] if r else []
    if not m:
        return None
    exact = ([x for x in m if x[0].lower() == want.lower()] or
             [x for x in m if re.search(r"(?<![a-z])" + re.escape(want.lower()), x[0].lower())] or
             [x for x in m if want.lower() in x[0].lower()])
    return exact[0] if exact else max(m, key=lambda x: difflib.SequenceMatcher(None, want.lower(), x[0].lower()).ratio())


def pick_prompt_option(page, target, loc, val, rule, label="", escalate=False):
    """Selects a value in a searchable dropdown (Workday 'prompt' fields, Greenhouse select2,
    or React comboboxes). Opens it, searches, clicks the closest option, and confirms the
    choice stuck. Returns the chosen option text, or typed fallback."""
    pat = rule.get("option") or re.escape(val)
    search = re.sub(r"\s*\(.*?\)", "", val.split(",")[0]).strip() or val  # 'United States (+1)' -> 'United States'
    if re.search(r"^united\s+states\s+of\s+america", search, re.I):
        search = "United States"
    search = re.sub(r"['’]s\b|\bdegree\b", "", search, flags=re.I).strip() or search
    is_yesno = str(val).strip().lower() in ("yes", "no")
    strict = is_yesno or bool(re.search(r"country|territory|phone|dial|code|state|province|device|intend to work|work location|reside|residence|citizen|authorized to work", label, re.I)) or bool(OPTS and OPTS.fact_category(label)[0])

    # Check if a matching choice is already selected in the field
    try:
        cur = loc.evaluate("e => { let curr = e; for (let i = 0; i < 4 && curr; i++, curr = curr.parentElement) { const s = curr.querySelector('[id*=\"pill\"], [data-automation-id=\"selectedItem\"]'); if (s) return s.innerText || s.getAttribute('aria-label') || ''; } return e.value || ''; }")
        if cur and len(cur.strip()) < 80 and cur.count("+") <= 2 and re.search(pat, cur, re.I):
            return cur
    except Exception:
        pass

    def open_field():
        try:
            btn = loc.locator('xpath=./parent::*//button[@aria-haspopup="listbox" or @aria-label="Prompt" or @data-automation-id="promptIcon"]').first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=1500)
            else:
                loc.click(timeout=1500)
        except Exception:
            try: loc.click(force=True, timeout=1200)
            except Exception: loc.focus()
        try: page.keyboard.press("ArrowDown")
        except Exception: pass
        time.sleep(0.35)

    def click_and_confirm(text, opt):
        try: opt.click(timeout=1500)
        except Exception:
            try: opt.click(force=True)
            except Exception: pass
        time.sleep(0.25)
        return True

    open_field()
    # If a category exists on Workday (e.g. Job Boards), click it first
    if "myworkdayjobs.com" in page.url:
        try:
            jb_cat = target.locator("[role='listbox'] *, [data-uxi-widget-type*='listitem'] *").filter(has_text=re.compile(r"^Job Boards|^Social Media|^Partial List|^All\b", re.I)).first
            if jb_cat.is_visible(timeout=400):
                jb_cat.click(force=True)
                time.sleep(0.5)
        except Exception:
            pass

    hit = _best_option(_visible_options(target), val, pat, label)
    if not hit:  # type to search
        try:
            loc.fill("", timeout=1200)
            loc.press_sequentially(search, delay=15, timeout=1500)
            try:
                if loc.evaluate("e => e.getAttribute('enterkeyhint') === 'search' || e.getAttribute('data-automation-id') === 'searchBox'"):
                    loc.press("Enter", timeout=1000)
                    time.sleep(0.5)
            except Exception:
                pass
        except Exception:
            pass
        if "myworkdayjobs.com" in page.url:
            try: page.keyboard.press("Enter")  # in a Workday search box, Enter runs the search (it does not commit)
            except Exception: pass
        # Direct container search if input defines aria-controls or aria-owns (Eightfold, Workday, etc.)
        try:
            ctrl_id = loc.get_attribute("aria-controls") or loc.get_attribute("aria-owns")
            if ctrl_id:
                ctrl = (target.page if hasattr(target, "page") else target).locator(f"#{ctrl_id}")
                if ctrl.count() > 0:
                    ctrl_opts = ctrl.locator("[role='option'], li, div")
                    opts_tuples = []
                    for idx in range(min(ctrl_opts.count(), 100)):
                        try:
                            co = ctrl_opts.nth(idx)
                            if co.is_visible(timeout=200):
                                txt = co.inner_text(timeout=200).strip()
                                if txt and not any(bad in txt.lower() for bad in ["delete to clear", "remove"]):
                                    opts_tuples.append((txt, co))
                        except Exception:
                            pass
                    if opts_tuples:
                        c_hit = _best_option(opts_tuples, val, pat, label)
                        if c_hit:
                            hit = c_hit
        except Exception:
            pass

        for _ in range(8 if not hit else 0):  # async lists (Greenhouse school search) fetch results after typing: wait up to ~3s
            time.sleep(0.4)
            hit = _best_option(_visible_options(target), val, pat, label)
            if hit:
                break
        if not hit:  # typed text filtered everything out ("0 results for 05/2028"): open the full list, let the resolver pick
            try:
                loc.fill("", timeout=1200)
                try:
                    if loc.evaluate("e => e.getAttribute('enterkeyhint') === 'search' || e.getAttribute('data-automation-id') === 'searchBox'"):
                        loc.press("Enter", timeout=1000)
                        time.sleep(0.3)
                except Exception:
                    pass
                page.keyboard.press("ArrowDown")
                time.sleep(0.4)
                hit = _best_option(_visible_options(target), val, pat, label)
            except Exception:
                pass

        # If user's specific school/major was not in closed options list, try searching 'Other'
        if not hit and re.search(r"school|university|college|institution|major|discipline|field of study|study", label, re.I):
            try:
                loc.fill("", timeout=1200)
                loc.press_sequentially("Other", delay=15, timeout=1500)
                try:
                    if loc.evaluate("e => e.getAttribute('enterkeyhint') === 'search' || e.getAttribute('data-automation-id') === 'searchBox'"):
                        loc.press("Enter", timeout=1000)
                        time.sleep(0.5)
                except Exception:
                    pass
                time.sleep(0.5)
                hit = _best_option(_visible_options(target), "Other", r"^(other|not listed)\b", label)
            except Exception:
                pass
        if not hit:
            try:
                page.keyboard.press("ArrowDown")
                time.sleep(0.25)
                hit = _best_option(_visible_options(target), val, pat, label)
            except Exception:
                pass

    # If full phrase search yielded nothing, try individual keywords
    if not hit and " " in search:
        for kw in search.split():
            if len(kw) < 4: continue
            try:
                loc.fill("", timeout=1200)
                loc.press_sequentially(kw, delay=15, timeout=1500)
                time.sleep(0.3)
                try:
                    if loc.evaluate("e => e.getAttribute('enterkeyhint') === 'search' || e.getAttribute('data-automation-id') === 'searchBox'"):
                        loc.press("Enter", timeout=1000)
                        time.sleep(0.5)
                    elif not strict:
                        page.keyboard.press("Enter")
                except Exception:
                    if not strict:
                        page.keyboard.press("Enter")
                time.sleep(0.4)
                hit = _best_option(_visible_options(target), val, pat, label)
                if hit: break
            except Exception:
                pass
        if not hit:
            try:
                loc.fill("", timeout=800)
            except Exception:
                pass

    # If still not found by pattern, pick top viable option if available (never for yes/no!).
    # escalate = the site rejected our last answer here: any non-fact, non-sensitive field takes its best option.
    if not hit and escalate and OPTS and not OPTS.fact_category(label)[0] and not (RE and RE.should_block(label)):
        vis = [v for v in _visible_options(target) if not OPTS.PLACEHOLDER.match(v[0])]
        if re.search(r"hear|source|referral", label, re.I):
            vis = [v for v in vis if not re.search(r"\+\d+|country|phone|mobile|device", v[0], re.I)]
        if vis:
            print(f"  [Repair] '{label[:50]}': site rejected '{val[:30]}' - choosing '{vis[0][0][:30]}'")
            hit = vis[0]
    if not hit and rule.get("ai_gen") and not strict:
        vis = _visible_options(target)
        if re.search(r"hear|source|referral", label, re.I):
            vis = [v for v in vis if not re.search(r"\+\d+|country|phone|mobile|device", v[0], re.I)]
        if vis:
            hit = vis[0]

    if hit and click_and_confirm(*hit):
        return hit[0]

    # For Ashby / React-Select / searchable comboboxes, press ArrowDown + Enter to commit filtered selection
    try:
        page.keyboard.press("ArrowDown")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(0.3)
        cur = loc.evaluate("e => { let curr = e; for (let i = 0; i < 4 && curr; i++, curr = curr.parentElement) { const s = curr.querySelector('[id*=\"pill\"], [data-automation-id=\"selectedItem\"], [class*=\"singleValue\"], [class*=\"single-value\"]'); if (s) return s.innerText || s.getAttribute('aria-label') || ''; } return e.value || ''; }")
        if cur and len(cur.strip()) > 1:
            return cur
    except Exception:
        pass

    # If the input already has the valid typed value, retain it rather than clearing
    try:
        cur_v = loc.input_value()
        if cur_v and len(cur_v.strip()) > 1:
            return cur_v
    except Exception:
        pass

    if strict:  # leave it empty (reported as unanswered) rather than commit a wrong country / state / yes-no
        try: page.keyboard.press("Escape")
        except Exception: pass
        return None
    # For React-Select / searchable comboboxes, press Enter to commit filtered selection
    try:
        page.keyboard.press("Enter")
        time.sleep(0.3)
        cur = loc.evaluate("e => { let curr = e; for (let i = 0; i < 4 && curr; i++, curr = curr.parentElement) { const s = curr.querySelector('[id*=\"pill\"], [data-automation-id=\"selectedItem\"], [class*=\"singleValue\"], [class*=\"single-value\"]'); if (s) return s.innerText || s.getAttribute('aria-label') || ''; } return ''; }")
        if cur:
            return cur
    except Exception:
        pass

    # Greenhouse / generic fallback: if value was typed into input, retain it
    try:
        cur_v = loc.evaluate("e => e.value")
        if cur_v and len(cur_v.strip()) > 1:
            if not is_yesno or cur_v.strip().lower() == val.lower():
                return cur_v
        loc.fill(search, timeout=1200)
        page.keyboard.press("Enter")
        return search
    except Exception:
        pass
    return None


def fill_page(page, resume, overwrite, company="", role=""):
    target = find_form_target(page)
    fields = target.evaluate(SCAN_JS)
    print(f"[Fill] {len(fields)} fields on this page ({time.strftime('%H:%M:%S')})", flush=True)
    filled, unanswered, optional_skipped, needs_you = [], [], [], []
    resume_done = False
    last_verification_code = None
    otp_attempted = False
    t_prev = None
    resume_fields = [f for f in fields if f["type"] == "file" and re.search(r"resume|\bcv\b|curriculum", f["label"], re.I)]
    sec_code_fields = [
        f for f in fields if (
            re.search(r"digit\s*(\d)\s*of\s*(?:six|6)", f.get("label", ""), re.I) or
            re.search(
                r"security\s*code|verification\s*code|8-character\s*code|confirm\s*you'?re\s*a\s*human|"
                r"one-time\s*(?:passcode|password|code)|\bpasscode\b|\botp\b|authentication\s*code|"
                r"enter\s*(?:the\s*)?(?:verification\s*)?code|code\s*sent\s*to|\bsecurity_code\b|\bverification_code\b",
                f"{f.get('label', '')} {f.get('name', '')} {f.get('elemId', '')} {f.get('placeholder', '')}", re.I
            )
        )
    ]
    for f in fields:
        label = f["label"]
        if t_prev and time.time() - t_prev[0] > 15:
            print(f"  [Slow] '{t_prev[1][:60]}' took {time.time() - t_prev[0]:.0f}s", flush=True)
        t_prev = (time.time(), label)
        if re.fullmatch(r"[a-z]+[A-Z][A-Za-z]*", label or "") and re.search(r"button|menu", label, re.I):
            continue  # Workday chrome like 'utilityMenuButton', not a question
        target_el_id = f["ids"][0] if f.get("ids") else f.get("id", "")
        loc = target.locator(f'[data-af-id="{target_el_id}"]').first if target_el_id else target.locator("body")
        try:
            # ---- resume upload
            if f["type"] == "file":
                has_existing = False
                try:
                    has_existing = bool(loc.evaluate("e => (e.files && e.files.length > 0) || !!e.closest('.file-upload, [data-automation-id*=\"file-upload\"], .field-wrapper, .field')?.querySelector('[data-automation-id*=\"file-upload-item\"], [data-automation-id*=\"delete-file\"], button[aria-label*=\"Remove\"], button[aria-label*=\"delete\" i]')"))
                except Exception:
                    pass
                # ONLY the real unofficial transcript downloaded from GSU (PAWS), saved under this exact name.
                # The generated "Ajayi_Olatokunbo_Transcript.pdf" (transcript_gen.py) imitates a registrar
                # document - never upload it. No real file -> transcript fields stay empty.
                transcript_path = ROOT / "resumes" / "GSU_Unofficial_Transcript_REAL.pdf"
                cover_path = ROOT / "resumes" / "Ajayi_Olatokunbo_Cover_Letter.pdf"  # resumes/cover_letter_gen.py
                if re.search(r"cover\s*letter", label, re.I):
                    if not has_existing and cover_path.exists():
                        try:
                            loc.set_input_files(str(cover_path))
                            filled.append(f"[cover letter] {cover_path.name}")
                            time.sleep(1.2)
                        except Exception as e:
                            print(f"[Cover Letter Upload Error] {e}")
                    continue
                if re.search(r"transcript|academic record", label, re.I):
                    if not has_existing:
                        upload_doc = transcript_path if transcript_path.exists() else None
                        if upload_doc:
                            try:
                                loc.set_input_files(str(upload_doc))
                                filled.append(f"[transcript] {upload_doc.name}")
                                time.sleep(1.2)
                            except Exception as e:
                                print(f"[Transcript Upload Error] {e}")
                    continue
                if resume_fields and f not in resume_fields:
                    continue  # e.g. Ashby's "autofill from resume" drop zone: uploading there crashed the tab
                if resume and not resume_done and not has_existing:
                    if not re.search(r"cover\s*letter|portfolio|writing\s*sample", label, re.I):
                        try:
                            loc.set_input_files(str(resume))
                            resume_done = True
                            r_name = getattr(resume, "name", Path(resume).name)
                            filled.append(f"[resume] {r_name}")
                            time.sleep(1.2)
                        except Exception as e:
                            print(f"[File Upload Error] {e}")
                elif (f.get("required") or ("*" in label and "optional" not in label.lower())) and not has_existing:
                    upload_doc = resume or (transcript_path if transcript_path.exists() else None)
                    if upload_doc:
                        try:
                            loc.set_input_files(str(upload_doc))
                            d_name = getattr(upload_doc, "name", Path(upload_doc).name)
                            filled.append(f"[doc] {d_name}")
                            time.sleep(1.2)
                        except Exception as e:
                            print(f"[Required Doc Upload Error] {e}")
                continue
            # Intercept email security / verification codes FIRST before any other rule (prevents e-mail rule from stealing code fields)
            is_sec_code = f in sec_code_fields
            m_digit = re.search(r"digit\s*(\d)\s*of\s*(?:six|6)", label, re.I)
            rule = None
            if is_sec_code:
                try:
                    cur_val = loc.evaluate("e => e.value") if loc else ""
                    if not cur_val and not last_verification_code and not otp_attempted:
                        otp_attempted = True
                        try:
                            import importlib
                            import gmail_auth
                            importlib.reload(gmail_auth)
                            fetch_code_fn = gmail_auth.fetch_verification_code
                        except Exception:
                            from gmail_auth import fetch_verification_code as fetch_code_fn
                        print(f"\n[Security Code] Verification code field detected: '{label[:60]}'. Listening to Gmail...")
                        clean_search = re.sub(r"\[.*?\]|\(.*?\)", "", company).split("-")[0].strip()
                        code = fetch_code_fn(timeout_sec=45, poll_interval=3, search_term=clean_search or company)
                        if code:
                            last_verification_code = code
                            print(f"[Security Code] Successfully retrieved code from Gmail: {code}")
                    elif cur_val and not last_verification_code:
                        last_verification_code = cur_val
                    if last_verification_code:
                        if m_digit:
                            d_idx = int(m_digit.group(1)) - 1
                            ans_char = last_verification_code[d_idx] if d_idx < len(last_verification_code) else ""
                            rule = {"q": re.escape(label), "a": ans_char, "ai_gen": True, "src": "code"}
                        elif len(sec_code_fields) > 1:
                            d_idx = sec_code_fields.index(f)
                            ans_char = last_verification_code[d_idx] if d_idx < len(last_verification_code) else ""
                            rule = {"q": re.escape(label), "a": ans_char, "ai_gen": True, "src": "code"}
                        else:
                            rule = {"q": re.escape(label), "a": last_verification_code, "ai_gen": True, "src": "code"}
                except Exception as ex:
                    print(f"[Security Code] IMAP fetch error: {ex}")
                if not last_verification_code:
                    unanswered.append({**f, "error": "verification code not received from email"})
                    continue
            else:
                rule = rule_for(label)
                if rule is None and not is_sec_code:
                    try:
                        from brain.vault import get_vault
                        ov = get_vault().get_field_override(label)
                        if ov:
                            rule = {"q": re.escape(label), "a": ov, "src": "brain_override"}
                    except Exception:
                        pass
                if rule is None and not is_sec_code:
                    try:
                        from brain.resolver import FastResolver
                        fast_ans = FastResolver.resolve(label, options=f.get("options"))
                        if fast_ans is not None:
                            rule = {"q": re.escape(label), "a": fast_ans, "src": "brain_resolver"}
                            print(f"  [Brain Resolver] '{label[:50]}' -> {fast_ans}")
                    except Exception:
                        pass
                if rule is None and f.get("required") and RE and not RE.SENSITIVE_RE.search(label):
                    try:  # new wording of a question a rule already answered (local neural match, >= 0.88)
                        from agents import semantic
                        if semantic.available():
                            hit = semantic.known_answer(label)
                            if hit:
                                rule = {"q": re.escape(label), "a": hit[1], "src": "semantic"}
                                print(f"  [Semantic] '{label[:50]}' ~ '{hit[0][:50]}' ({hit[2]}) -> {hit[1]}")
                    except Exception:
                        pass

            if rule is None and OPTS and not is_sec_code:
                cat, fr = OPTS.fact_rule(label, rule_for)
                if fr:
                    rule = fr
                elif cat:  # school / country / state / degree ... with no profile answer: leave it, never guess
                    unanswered.append({**f, "error": f"fact question ({cat}) - add a profile.json rule"})
                    continue

            if rule is None:
                    # Guess answer for unmapped fields
                    ai_ans = generate_response(label, field_type=f["type"], options=f.get("options"), company=company, role=role)
                    if ai_ans:
                        rule = {"q": re.escape(label), "a": ai_ans, "ai_gen": True}
                    elif f.get("options"):
                        rule = {"q": re.escape(label), "a": pick_best_option(label, f["options"]), "ai_gen": True}
                    elif f["type"] == "checkbox" and f.get("required"):
                        rule = {"q": re.escape(label), "a": "check", "ai_gen": True}
                    elif f.get("required") or f["tag"] == "textarea":
                        rule = {"q": re.escape(label), "a": "N/A", "ai_gen": True}
                    else:
                        continue
            if rule.get("only_combobox") and not f.get("combobox"):
                continue
            ans = rule.get("a")
            if ans is SKIP:
                if f.get("required") or ("*" in label and "optional" not in label.lower()):
                    if re.search(r"pronoun", label, re.I):
                        ans = "He/Him/His"
                    elif re.search(r"gender|sex\b", label, re.I):
                        ans = "Male"
                    elif re.search(r"race|ethnic", label, re.I):
                        ans = "Black or African American"
                    elif f.get("options"):
                        ans = f["options"][0]
                    else:
                        ans = "N/A"
                    rule = {**rule, "a": ans}
                else:
                    if rule.get("eeo"): optional_skipped.append(label)
                    continue
            if ans == ASK:
                # "scrap 3 and guess": auto-resolve ASK fields instead of pausing
                if f.get("options"):
                    ans = pick_best_option(label, f["options"]) or f["options"][0]
                else:
                    ans = generate_response(label, field_type=f["type"], options=f.get("options"), company=company, role=role) or "Yes"
                rule = {**rule, "a": ans, "ai_gen": True}
            src = rule.get("src") or ("guess" if rule.get("ai_gen") else "rule")
            if src == "guess" and RE and RE.should_block(label):
                # legal / eligibility / EEO question with no rule: don't guess - the job is skipped and logged
                RE.SENSITIVE_HITS.append(label[:120])
                unanswered.append({**f, "error": "sensitive question - not guessing"})
                continue
            escalate = bool(FIX_HINTS) and _hinted(label)
            has_val = f["value"] not in ("", "false", None) and not f["value"].lower().startswith(("please select", "select"))
            if len(str(f["value"] or "").strip()) > 80 or str(f["value"] or "").count("+") > 2:
                has_val = False
            if has_val and not overwrite and not escalate:
                val_matches = False
                cur_v = str(f["value"]).strip().lower()
                ans_v = str(ans).strip().lower()
                if cur_v == ans_v or (len(ans_v) > 2 and cur_v.startswith(ans_v)):
                    val_matches = True
                elif isinstance(rule.get("option"), str) and re.search(rule["option"], cur_v, re.I):
                    val_matches = True
                if val_matches and f["type"] not in ("yesno", "radio"):
                    continue

            # Smart subfield value normalization for split date inputs (e.g. Workday * Month, * Day, * Year)
            lab_low = label.lower()
            now = datetime.datetime.now()
            is_today_field = bool(re.search(r"today|signature|current\s*date|enter\s*today'?s\s*date|^date\b|^\*?\s*date\b", lab_low)) and not bool(re.search(r"birth|dob|graduat|start|end|from|to|prior|previous", lab_low))
            is_date_field = bool(re.search(r"\b(?:date|dob|birth|graduation|graduating|calendar|signature)\b|^(?:start|end|from|to)\b|(?:\bfrom|\bto)\s*(?:date|month|year|\*|:)?$", lab_low)) or is_today_field or f.get("type") == "date"
            if is_date_field and re.search(r"\bday\b", lab_low) and not re.search(r"\b(birthday|workday|everyday|holiday)\b|day-to-day|day to day|per day|days of|days per|how many days", lab_low):
                if is_today_field or ans == "TODAY_DAY":
                    d_val = f"{now.day:02d}"
                elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", str(ans)):
                    parts = str(ans).split("/")
                    d_val = parts[1] if len(parts) > 1 else f"{now.day:02d}"
                elif str(ans).isdigit() and 1 <= int(str(ans)) <= 31:
                    d_val = f"{int(str(ans)):02d}"
                else:
                    d_val = f"{now.day:02d}" if is_today_field else "01"
                ans = d_val
                rule = {**rule, "a": d_val, "option": rf"^{int(d_val)}$|^{d_val}$"}
            elif is_date_field and re.search(r"\bmonth\b", lab_low) and not re.search(r"year|how many months|months of experience|per month|a month|hours per", lab_low):
                if is_today_field or ans == "TODAY_MONTH":
                    m_num = f"{now.month:02d}"
                elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", str(ans)):
                    m_num = str(ans).split("/")[0]
                elif str(ans).isdigit() and 1 <= int(str(ans)) <= 12:
                    m_num = f"{int(str(ans)):02d}"
                else:
                    m_num = f"{now.month:02d}" if is_today_field else "06"
                m_int = int(m_num) if m_num.isdigit() else now.month
                m_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                m_name = m_names[m_int - 1] if 1 <= m_int <= 12 else "October"
                is_select_or_combo = f.get("type") in ("select", "listbox") or bool(f.get("combobox"))
                ans = m_name if is_select_or_combo else f"{m_int:02d}"
                rule = {**rule, "a": ans, "option": rf"^{m_int}$|^{m_int:02d}$|^{m_name}\b"}
            elif is_date_field and re.search(r"\byear\b", lab_low) and not re.search(r"month|years? of experience|how many years", lab_low):
                if is_today_field or ans == "TODAY_YEAR":
                    y_val = str(now.year)
                else:
                    m_yr = re.search(r"\b(20\d\d)\b", str(ans))
                    y_val = m_yr.group(1) if m_yr else (str(now.year) if is_today_field else "2027")
                ans = y_val
                rule = {**rule, "a": y_val, "option": rf"^{y_val}$"}

            # ---- by kind
            CHECK_ANSWERS = ("yes", "true", "check", "uncheck", "no", "false", "i agree", "agree", "accept", "i accept", "acknowledge", "i acknowledge", "consent", "i consent")
            if f["type"] == "checkbox" and isinstance(ans, str) and ans.lower() not in CHECK_ANSWERS and not rule.get("ai_gen"):
                # a text answer on a checkbox list ("Discipline(s) * Agriculture"): tick only the box that matches it
                opt_text = " ".join(label.rsplit(" * ", 1)[-1].split()).lower()
                a_text = " ".join(ans.split()).lower()
                if len(opt_text) > 3 and (opt_text in a_text or a_text in opt_text) and f["value"] != "true":
                    try: loc.check(timeout=1200)
                    except Exception:
                        try: loc.click(force=True, timeout=1200)
                        except Exception: pass
                else: continue
            elif f["type"] == "checkbox":
                # Ashby Yes/No button group support (<button data-option="yes"> / <button data-option="no">)
                ashby_btn = loc.locator("xpath=./preceding-sibling::button[@data-option] | ./parent::*//button[@data-option]")
                if ashby_btn.count() > 0:
                    try:
                        want_yes = (isinstance(ans, str) and ans.lower() in ("yes", "true", "check", "agree", "i agree", "accept", "1")) or (isinstance(ans, bool) and ans)
                        btn_sel = "./parent::*//button[@data-option='yes']" if want_yes else "./parent::*//button[@data-option='no']"
                        target_btn = loc.locator(f"xpath={btn_sel}").first
                        if target_btn.count() > 0:
                            target_btn.click(force=True, timeout=800)
                            filled.append(f"{label} = {'Yes' if want_yes else 'No'}")
                            continue
                    except Exception:
                        pass
                should_check = (ans == "check" or (f.get("required") and ans not in ("uncheck", "no", "false")) or
                                (isinstance(ans, str) and ans.lower() in ("yes", "true", "check", "agree", "i agree", "accept", "i accept", "acknowledge", "i acknowledge", "consent", "i consent")) or
                                re.search(r"undergraduate|bachelor|summer 2027|open to anything|applied ai|backend|fullstack|software|new york|san francisco|atlanta|agree|terms|consent|authorize|acknowledge|black or african american", label, re.I))
                already_checked = False
                try:
                    is_invalid = loc.get_attribute("aria-invalid") == "true"
                    already_checked = (loc.is_checked() or loc.get_attribute("aria-checked") == "true" or f.get("value") == "true") and not is_invalid
                except Exception:
                    pass
                if should_check and not already_checked:
                    checked_ok = False
                    # Visual label / container click FIRST (vital for Workday Canvas Kit, React-Select, and custom styled checkboxes)
                    try:
                        elem_id = loc.get_attribute("id")
                        if elem_id:
                            lbl = target.locator(f"label[for='{elem_id}']").first
                            if lbl.count() > 0 and lbl.is_visible(timeout=500):
                                lbl.click(force=True, timeout=800)
                                checked_ok = True
                    except Exception:
                        pass
                    if not checked_ok:
                        try:
                            parent_el = loc.locator("xpath=./ancestor::label[1] | ./ancestor::div[@data-automation-id='checkboxPanel'][1] | ./following-sibling::label[1] | ./parent::*//label | ./ancestor::div[contains(@class, 'checkbox')][1]")
                            if parent_el.count() > 0:
                                parent_el.first.click(force=True, timeout=800)
                                checked_ok = True
                        except Exception:
                            pass
                    if not checked_ok:
                        try:
                            loc.check(force=True, timeout=1000)
                            checked_ok = True
                        except Exception:
                            pass
                    if not checked_ok:
                        try: loc.click(force=True, timeout=1000)
                        except Exception: pass
                    # If native input is still not checked after click, apply prototype setter
                    try:
                        is_now_checked = loc.is_checked()
                    except Exception:
                        is_now_checked = False
                    if not is_now_checked:
                        try:
                            loc.evaluate("""e => {
                                if (e) {
                                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                                    if (setter) { setter.call(e, true); }
                                    else { e.checked = true; }
                                    e.dispatchEvent(new Event('input', {bubbles: true}));
                                    e.dispatchEvent(new Event('change', {bubbles: true}));
                                }
                            }""")
                        except Exception:
                            pass
                elif ans in ("uncheck", "no", "false") and f["value"] == "true":
                    unchecked_ok = False
                    try:
                        loc.uncheck(timeout=1000)
                        unchecked_ok = True
                    except Exception:
                        pass
                    if not unchecked_ok:
                        try:
                            parent_el = loc.locator("xpath=./ancestor::label[1] | ./ancestor::div[@data-automation-id='checkboxPanel'][1] | ./parent::*")
                            if parent_el.count() > 0:
                                parent_el.first.click(timeout=1000)
                                unchecked_ok = True
                        except Exception:
                            pass
                    if not unchecked_ok:
                        try: loc.click(force=True, timeout=1000)
                        except Exception: pass
                else: continue
            elif f["tag"] == "select":
                opt = pick_option(f["options"], rule, label=label)
                if not opt: unanswered.append(f); continue
                try:
                    raw = target.evaluate('(id)=>{ const el = document.querySelector(`[data-af-id="${id}"]`); return el && el.options ? [...el.options].map(o=>o.text) : []; }', f["id"])
                except Exception:
                    raw = []
                matched = next((o for o in raw if " ".join(o.split()).lower() == opt.lower()), opt)
                sel_done = False
                try:
                    loc.select_option(label=matched, timeout=1200)
                    sel_done = True
                except Exception:
                    pass
                if not sel_done:
                    try:
                        loc.select_option(value=opt, timeout=1200)
                        sel_done = True
                    except Exception:
                        pass
                if not sel_done:
                    try:
                        target.evaluate('''([id, opt]) => {
                            const el = document.querySelector(`[data-af-id="${id}"]`);
                            if (el) {
                                const m = opt.toLowerCase();
                                for (let i = 0; i < el.options.length; i++) {
                                    const t = el.options[i].text.toLowerCase();
                                    const v = el.options[i].value.toLowerCase();
                                    if (t === m || v === m || t.includes(m) || v.includes(m)) {
                                        el.selectedIndex = i;
                                        el.dispatchEvent(new Event("change", { bubbles: true }));
                                        el.dispatchEvent(new Event("input", { bubbles: true }));
                                        break;
                                    }
                                }
                            }
                        }''', [f["id"], opt])
                    except Exception:
                        pass
            elif f["type"] == "radio":
                opt = pick_option(f["options"], rule, label=label)
                if not opt: unanswered.append(f); continue
                idx = f["options"].index(opt)
                r_id = f["ids"][idx]
                try:
                    target.locator(f'[data-af-id="{r_id}"]').check(force=True, timeout=1200)
                except Exception:
                    try:
                        target.locator(f'[data-af-id="{r_id}"]').click(force=True, timeout=1200)
                    except Exception:
                        try:
                            target.evaluate(f'(id) => {{ const el = document.querySelector(`[data-af-id="${{id}}"]`); if (el) {{ el.checked = true; el.dispatchEvent(new Event("change", {{ bubbles: true }})); el.dispatchEvent(new Event("input", {{ bubbles: true }})); }} }}', r_id)
                        except Exception:
                            pass
            elif f["type"] == "yesno":
                opt = pick_option(f["options"], rule, label=label)
                if not opt: unanswered.append(f); continue
                yn_id = f["ids"][f["options"].index(opt)]
                try:
                    target.locator(f'[data-af-id="{yn_id}"]').click(timeout=1200)
                except Exception:
                    try:
                        target.locator(f'[data-af-id="{yn_id}"]').click(force=True, timeout=1200)
                    except Exception:
                        try:
                            target.evaluate(f'(id) => {{ const el = document.querySelector(`[data-af-id="${{id}}"]`); if (el) {{ el.click(); }} }}', yn_id)
                        except Exception:
                            pass
            elif f["type"] == "listbox":
                root = target.page if hasattr(target, "page") else target
                # Wait for any closing popup from previous question to finish closing
                try:
                    closing_lb = root.locator("div[visibility='closing'], [visibility='closing']")
                    if closing_lb.count() > 0:
                        closing_lb.first.wait_for(state="detached", timeout=800)
                except Exception:
                    pass
                try:
                    # Clean up any lingering closing popup divs from previous listbox selections
                    page.evaluate("() => document.querySelectorAll('[visibility=\"closing\"]').forEach(e => e.remove())")
                except Exception:
                    pass
                try:
                    loc.evaluate("e => e.scrollIntoView({ block: 'center' })")
                    time.sleep(0.3)
                except Exception:
                    pass
                opened = False
                try:
                    is_btn = loc.evaluate("e => e.tagName === 'BUTTON' || e.getAttribute('role') === 'button' || e.hasAttribute('aria-haspopup')")
                    if is_btn and loc.is_visible():
                        loc.click(timeout=1500)
                        opened = True
                except Exception:
                    pass
                if not opened:
                    try:
                        wd_btn = loc.locator('xpath=./parent::*//button[@aria-haspopup="listbox"]').first
                        if wd_btn.count() > 0 and wd_btn.is_visible():
                            wd_btn.click(timeout=1500)
                            opened = True
                    except Exception:
                        pass
                if not opened:
                    try:
                        loc.click(timeout=1500)
                        opened = True
                    except Exception:
                        pass
                if not opened:
                    try:
                        box = loc.bounding_box()
                        if box:
                            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            opened = True
                    except Exception:
                        pass
                if not opened:
                    try:
                        loc.evaluate("e => e.click()")
                    except Exception:
                        pass
                time.sleep(0.4)
                # If listbox didn't open from clicking button, try clicking the dropdown caret icon or keyboard
                active_lb = root.locator("div:not([visibility='closing']) > ul[role='listbox']:not([data-automation-id='selectedItemList']), div[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']), [role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing'])").last
                try:
                    if active_lb.count() == 0 or not active_lb.is_visible(timeout=400):
                        caret = loc.locator('xpath=./following-sibling::span[contains(@class, "menu-icon")] | ./parent::*//span[contains(@class, "menu-icon")] | ./following-sibling::*//svg').first
                        if caret.count() > 0 and caret.is_visible():
                            caret.click(timeout=1000)
                            time.sleep(0.4)
                            active_lb = root.locator("div:not([visibility='closing']) > ul[role='listbox']:not([data-automation-id='selectedItemList']), div[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']), [role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing'])").last
                except Exception:
                    pass
                try:
                    if active_lb.count() == 0 or not active_lb.is_visible(timeout=300):
                        loc.press("Space")
                        time.sleep(0.3)
                        active_lb = root.locator("div:not([visibility='closing']) > ul[role='listbox']:not([data-automation-id='selectedItemList']), div[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']), [role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing'])").last
                except Exception:
                    pass
                try:
                    if active_lb.count() == 0 or not active_lb.is_visible(timeout=300):
                        loc.press("ArrowDown")
                        time.sleep(0.3)
                        active_lb = root.locator("div:not([visibility='closing']) > ul[role='listbox']:not([data-automation-id='selectedItemList']), div[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']), [role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing'])").last
                except Exception:
                    pass
                opt_pat = str(rule["option"]) if isinstance(rule.get("option"), str) and rule["option"] else re.escape(str(ans))
                # Search visible options across page, strictly excluding closing popups and already-selected item pills
                try:
                    if active_lb.count() > 0 and active_lb.is_visible(timeout=800):
                        opts = active_lb.locator("[role='option']:not([aria-disabled='true']):not([id*='pill'])")
                    else:
                        opts = root.locator("[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']) [role='option']:not([aria-disabled='true']):not([visibility='closing'] *), [data-automation-id='menuItem']:not([data-automation-id*='selectedItem'] *):not([visibility='closing'] *), [data-automation-id='promptOption']:not([data-automation-id*='selectedItem'] *):not([id*='pill']):not([visibility='closing'] *), [role='option']:not([id*='pill']):not([data-automation-id*='selectedItem']):not([data-automation-id='selectedItemList'] *):not([visibility='closing'] *)")
                except Exception:
                    opts = root.locator("[role='listbox']:not([data-automation-id='selectedItemList']):not([visibility='closing']) [role='option']:not([aria-disabled='true']):not([visibility='closing'] *), [data-automation-id='menuItem']:not([data-automation-id*='selectedItem'] *):not([visibility='closing'] *), [data-automation-id='promptOption']:not([data-automation-id*='selectedItem'] *):not([id*='pill']):not([visibility='closing'] *), [role='option']:not([id*='pill']):not([data-automation-id*='selectedItem']):not([data-automation-id='selectedItemList'] *):not([visibility='closing'] *)")
                try:
                    opts.first.wait_for(state="visible", timeout=1000)
                except Exception:
                    pass
                clicked = False
                # Direct check on rule-specified option regex
                if isinstance(rule.get("option"), str) and rule["option"]:
                    try:
                        pat_re = re.compile(rule["option"], re.I)
                        target_opt = opts.filter(has_text=pat_re).first
                        if target_opt.count() > 0:
                            try: target_opt.scroll_into_view_if_needed(timeout=600)
                            except Exception: pass
                            target_opt.click(force=True, timeout=1200)
                            clicked = True
                    except Exception:
                        pass
                is_yesno = str(ans).strip().lower() in ("yes", "no")
                if not clicked and is_yesno:
                    try:
                        target_opt = opts.filter(has_text=re.compile(rf"\b{ans}\b", re.I)).first
                        if target_opt.count() > 0:
                            try: target_opt.scroll_into_view_if_needed(timeout=600)
                            except Exception: pass
                            target_opt.click(force=True, timeout=1200)
                            clicked = True
                    except Exception:
                        pass
                if not clicked and is_yesno and OPTS:
                    try:
                        yn_pat = OPTS.YES if str(ans).strip().lower() == "yes" else OPTS.NO
                        target_opt = opts.filter(has_text=yn_pat).first
                        if target_opt.count() > 0:
                            try: target_opt.scroll_into_view_if_needed(timeout=600)
                            except Exception: pass
                            target_opt.click(force=True, timeout=1200)
                            clicked = True
                    except Exception:
                        pass
                if not clicked and is_yesno:
                    for sel in ("[role='option']", "[data-automation-id='promptOption']", "[data-automation-id='menuItem']", "div[role='listbox'] div", "ul[role='listbox'] li"):
                        try:
                            candidate = root.locator(sel).filter(has_text=re.compile(rf"^\s*{ans}\s*$", re.I)).last
                            if candidate.count() == 0 or not candidate.is_visible(timeout=200):
                                candidate = page.locator(sel).filter(has_text=re.compile(rf"^\s*{ans}\s*$", re.I)).last
                            if candidate.count() == 0 or not candidate.is_visible(timeout=200):
                                candidate = page.locator(sel).filter(has_text=re.compile(rf"\b{ans}\b", re.I)).last
                            if candidate.count() > 0 and candidate.is_visible(timeout=400):
                                candidate.click(force=True)
                                clicked = True
                                break
                        except Exception:
                            pass
                if not clicked and OPTS:
                    # read ALL options at once (Workday's country list has 250; the old loop saw only the first 100,
                    # missed "United States" and clicked "Aland Islands"), then type-ahead if still not found
                    for attempt in range(2):
                        try:
                            texts = [" ".join(t.split()) for t in opts.all_inner_texts()]
                            texts = [t for t in texts if t and not OPTS.PLACEHOLDER.search(t)]
                        except Exception:
                            texts = []
                        if not texts and attempt == 0:
                            time.sleep(0.4)
                            try:
                                texts = [" ".join(t.split()) for t in opts.all_inner_texts()]
                                texts = [t for t in texts if t and not OPTS.PLACEHOLDER.search(t)]
                            except Exception:
                                texts = []
                        r = OPTS.resolve(label, ans, texts, rule.get("option")) if texts else None
                        if r:
                            # the same text can exist in hidden lists elsewhere on the page: click the visible copy
                            idxs = [k for k, t in enumerate(texts) if t == r]
                            o = next((opts.nth(k) for k in idxs if opts.nth(k).is_visible()), opts.nth(idxs[0]))
                            try: o.scroll_into_view_if_needed(timeout=2000)
                            except Exception: pass
                            try: o.click(timeout=2000)
                            except Exception: o.click(force=True)
                            clicked, ans = True, r
                            break
                        if attempt == 0 and not is_yesno:
                            cat, _ = OPTS.fact_category(label)
                            if cat in ("school", "country", "country_code", "state", "major", "degree") or re.search(r"country\s*code|phone\s*country", label, re.I):
                                type_txt = "United States" if re.search(r"country\s*code|phone\s*country", label, re.I) else re.sub(r"\s*\(.*?\)", "", str(ans)).strip()[:30]
                                page.keyboard.type(type_txt, delay=40)
                                time.sleep(0.6)
                for i in range(0 if clicked else min(opts.count(), 300)):
                    o = opts.nth(i)
                    try:
                        if o.is_visible():
                            txt = o.inner_text().strip()
                            if re.search(r"no\s+(?:results|options|matches|records)|loading\.*|searching\.*", txt, re.I):
                                continue
                            if re.search(opt_pat, txt, re.I) or (str(ans).lower() in ("yes", "no") and (re.search(rf"^\s*{ans}\s*$", txt, re.I) or (OPTS and (OPTS.YES if str(ans).lower() == "yes" else OPTS.NO).search(txt)))):
                                o.click(force=True)
                                clicked = True
                                break
                    except Exception:
                        pass
                if not clicked and is_yesno:
                    # Final safety type-ahead for yes/no combobox
                    try:
                        prev_txt = loc.inner_text(timeout=400) if loc else ""
                        page.keyboard.type(str(ans).capitalize(), delay=30)
                        time.sleep(0.4)
                        page.keyboard.press("Enter")
                        time.sleep(0.3)
                        new_txt = loc.inner_text(timeout=400) if loc else ""
                        if new_txt and new_txt != prev_txt and not re.search(r"select|choose", new_txt, re.I):
                            clicked = True
                    except Exception:
                        pass
                if not clicked and RE and RE.should_block(label):
                    # sensitive question and the rule's answer isn't offered: decline if possible, never guess
                    for i in range(min(opts.count(), 100)):
                        o = opts.nth(i)
                        try:
                            if o.is_visible() and RE.EEO_RE.search(label) and RE.DECLINE_RE.search(o.inner_text()):
                                o.click(force=True); clicked = True; ans = o.inner_text().strip(); break
                        except Exception:
                            pass
                    if not clicked:
                        RE.SENSITIVE_HITS.append(label[:120])
                        page.keyboard.press("Escape")
                        unanswered.append({**f, "error": "sensitive question - not guessing"})
                        continue
                if not clicked:
                    PICK_GUESSED.add(label)
                    # Smart option fallback for EEO/gender or non-empty options
                    for i in range(min(opts.count(), 100)):
                        o = opts.nth(i)
                        try:
                            if o.is_visible():
                                txt = o.inner_text().strip()
                                if re.search(r"decline|prefer not|choose not|not wish|don'?t wish", txt, re.I):
                                    o.click(force=True)
                                    clicked = True
                                    ans = txt
                                    break
                        except Exception:
                            pass
                fact_like = bool(OPTS and OPTS.fact_category(label)[0]) or re.search(r"country|territory|phone code|state|province", label, re.I)
                sensitive = bool(RE and (RE.should_block(label) or RE.EEO_RE.search(label)))
                if not clicked and f.get("required") and not fact_like and not is_yesno and not sensitive:  # never click first option for sensitive/country/state/yes-no
                    for i in range(min(opts.count(), 100)):
                        o = opts.nth(i)
                        try:
                            if o.is_visible():
                                txt = o.inner_text().strip()
                                if txt and not re.search(r"select|choose|--|^please", txt, re.I):
                                    o.click(force=True)
                                    clicked = True
                                    ans = txt
                                    break
                        except Exception:
                            pass
                if not clicked and is_yesno:
                    # Final direct locator fallback for Yes/No (prefer visible options over hidden ones from earlier questions)
                    try:
                        yn_pat = OPTS.YES if (OPTS and str(ans).strip().lower() == "yes") else (OPTS.NO if OPTS else re.compile(rf"^\s*{ans}\s*$", re.I))
                        yn_candidates = root.locator("[role='option'], [data-automation-id='promptOption'], button[role='radio']").filter(has_text=yn_pat)
                        for c_idx in range(min(yn_candidates.count(), 10)):
                            cand = yn_candidates.nth(c_idx)
                            try:
                                if cand.is_visible():
                                    opt_txt = cand.inner_text().strip()
                                    if not re.search(r"no\s+(?:results|options|matches|records)", opt_txt, re.I):
                                        cand.click(force=True)
                                        clicked = True
                                        break
                            except Exception:
                                pass
                    except Exception:
                        pass
                if not clicked and is_yesno:
                    # Final keyboard selection for select/combobox buttons (e.g. Workday Canvas Kit)
                    try:
                        loc.focus()
                        time.sleep(0.1)
                        loc.press("Space")
                        time.sleep(0.25)
                        key_to_press = "y" if str(ans).strip().lower() == "yes" else "n"
                        page.keyboard.press(key_to_press)
                        time.sleep(0.2)
                        page.keyboard.press("Enter")
                        time.sleep(0.2)
                        btn_txt = loc.inner_text(timeout=300).strip()
                        if btn_txt and not re.search(r"^\s*(?:select|choose|--|please)\b", btn_txt, re.I):
                            clicked = True
                    except Exception:
                        pass
                    if not clicked:
                        try:
                            loc.focus()
                            time.sleep(0.1)
                            loc.press("ArrowDown")
                            time.sleep(0.2)
                            if str(ans).strip().lower() == "no":
                                loc.press("ArrowDown")
                                time.sleep(0.15)
                            loc.press("Enter")
                            time.sleep(0.25)
                            btn_txt = loc.inner_text(timeout=300).strip()
                            if btn_txt and not re.search(r"^\s*(?:select|choose|--|please)\b", btn_txt, re.I):
                                clicked = True
                        except Exception:
                            pass
                if not clicked and not is_yesno:
                    try:
                        clean_txt = re.sub(r"\s*\(.*?\)", "", str(ans)).strip()
                        loc.focus()
                        time.sleep(0.1)
                        loc.press("Space")
                        time.sleep(0.25)
                        page.keyboard.type(clean_txt, delay=35)
                        time.sleep(0.4)
                        page.keyboard.press("Enter")
                        time.sleep(0.4)
                        btn_txt = loc.inner_text(timeout=300).strip()
                        if btn_txt and not re.search(r"^\s*(?:select|choose|--|please)\b", btn_txt, re.I):
                            clicked = True
                        else:
                            page.keyboard.press("Escape")
                    except Exception:
                        pass
                if not clicked:
                    # Check if the button itself already displays the chosen answer or a non-placeholder value
                    try:
                        cur_btn_txt = loc.inner_text(timeout=300).strip()
                        if cur_btn_txt and not re.search(r"^\s*(?:select|choose|--|please)\b", cur_btn_txt, re.I):
                            clicked = True
                    except Exception:
                        pass
                if not clicked:
                    unanswered.append({**f, "error": "could not select listbox option"})
                    continue
            else:
                val = str(ans)
                # Smart subfield value normalization for split date inputs (e.g. Workday * Month, * Day, * Year)
                lab_low = label.lower()
                now = datetime.datetime.now()
                is_today_field = bool(re.search(r"today|signature|current\s*date|enter\s*today'?s\s*date|^date\b|^\*?\s*date\b", lab_low)) and not bool(re.search(r"birth|dob|graduat|start|end|from|to|prior|previous", lab_low))
                is_date_field = bool(re.search(r"\b(?:date|dob|birth|graduation|graduating|calendar|signature)\b|^(?:start|end|from|to)\b|(?:\bfrom|\bto)\s*(?:date|month|year|\*|:)?$", lab_low)) or is_today_field or f.get("type") == "date"
                if re.search(r"^\s*today'?s\s*date|^\s*date\s*$", lab_low) or val == "TODAY":
                    val = now.strftime("%m/%d/%Y")
                elif is_date_field and re.search(r"\bday\b", lab_low) and not re.search(r"\b(birthday|workday|everyday|holiday)\b|day-to-day|day to day|per day|days of|days per|how many days", lab_low):
                    if is_today_field or val == "TODAY_DAY":
                        val = f"{now.day:02d}"
                    elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", val):
                        parts = val.split("/")
                        val = parts[1] if len(parts) > 1 else "01"
                    elif val.isdigit() and len(val) > 2:
                        val = "01"
                elif is_date_field and re.search(r"\bmonth\b", lab_low) and not re.search(r"year|how many months|months of experience|per month|a month|hours per", lab_low):
                    m_map = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
                    converted_m = None
                    for mn_prefix, mn_digit in m_map.items():
                        if mn_prefix in val.lower():
                            converted_m = mn_digit
                            break
                    if converted_m:
                        val = converted_m
                    elif is_today_field or val == "TODAY_MONTH":
                        val = f"{now.month:02d}"
                    elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", val):
                        val = val.split("/")[0]
                        if len(val) == 1: val = f"0{val}"
                elif is_date_field and re.search(r"\byear\b", lab_low) and not re.search(r"month|years? of experience|how many years", lab_low):
                    if is_today_field or val == "TODAY_YEAR":
                        val = str(now.year)
                    else:
                        m_yr = re.search(r"\b(20\d\d)\b", val)
                        if m_yr:
                            val = m_yr.group(1)
                        else:
                            val = "2027"
                if is_date_field and not re.search(r"\b(day|month|year)\b", lab_low):
                    ph = (f.get("placeholder") or "").lower()
                    m_my = re.search(r"([A-Za-z]+)\s+(20\d\d)", val)
                    m_slash = re.search(r"(\d{1,2})/(?:(\d{1,2})/)?(20\d\d)", val)
                    m_num = None
                    y_num = None
                    d_num = "01"
                    if m_my:
                        m_str, y_num = m_my.group(1).lower(), m_my.group(2)
                        for k_m, v_tuple in MONTHS_MAP.items():
                            if m_str in v_tuple:
                                m_num = int(k_m)
                                break
                    elif m_slash:
                        m_num = int(m_slash.group(1))
                        d_num = f"{int(m_slash.group(2)):02d}" if m_slash.group(2) else "01"
                        y_num = m_slash.group(3)

                    if m_num and y_num:
                        if f.get("type") == "date":
                            val = f"{y_num}-{m_num:02d}-{d_num}"
                        elif ("mm/yy" in ph or "mm/yyyy" in ph) and "dd" not in ph:
                            val = f"{m_num:02d}/{y_num}"
                        elif "dd" in ph or "mm/dd/yyyy" in ph or re.search(r"date", lab_low):
                            val = f"{m_num:02d}/{d_num}/{y_num}"

                if re.search(r"\bend\s*date\b", lab_low) and val.lower() == "present":
                    ph = (f.get("placeholder") or "").lower()
                    if "yyyy" in ph or "mm/dd" in ph or f.get("type") == "date":
                        val = now.strftime("%m/%d/%Y" if "dd" in ph else "%m/%Y")
                if re.search(r"salary|compensation|pay|rate", lab_low) and val.lower() == "open":
                    if f.get("type", "").lower() in ("number", "numeric") or "annual" in lab_low:
                        val = "60000"
                if f.get("type", "").lower() in ("number", "numeric"):
                    if not val.strip().isdigit():
                        digits = re.findall(r"\d+", val)
                        if digits:
                            val = "10" if re.search(r"scale|rate|rating|1[\s\-–to]+10", lab_low) else digits[0]
                        else:
                            val = "10" if re.search(r"scale|rate|rating|1[\s\-–to]+10", lab_low) else "0"
                if f.get("type", "").lower() == "url" or lab_low.strip() in ("link", "url", "website", "portfolio"):
                    if not val.startswith("http"):
                        val = os.getenv("CANDIDATE_LINKEDIN_URL", "https://www.linkedin.com")
                if re.search(r"phone|mobile|cell", lab_low) and not re.search(r"code|country|dial|device", lab_low):
                    ph = (f.get("placeholder") or "").lower()
                    raw_phone = re.sub(r"\D", "", os.getenv("CANDIDATE_PHONE", val))
                    if (escalate or "-" in ph or "(" in ph or "dash" in ph) and len(raw_phone) == 10:
                        val = f"{raw_phone[:3]}-{raw_phone[3:6]}-{raw_phone[6:]}"

                if f["combobox"]:
                    if re.match(r"^\+?\d{7,15}$", val.strip()) and re.search(r"phone|country|device|dial", label, re.I):
                        val = "United States (+1)"
                        rule = {"a": "United States (+1)", "option": "^(?:United States|USA|US|\\+1)\\b"}
                    chosen = pick_prompt_option(page, target, loc, val, rule, label=label, escalate=escalate)
                    if not chosen and f.get("tag") in ("input", "textarea"):
                        # Fallback for datepicker / text input with aria-haspopup (e.g. calendar dialog)
                        is_date_field = "date" in lab_low or "date" in (f.get("placeholder") or "").lower() or f.get("type") == "date"
                        if is_date_field:
                            try:
                                loc.click(timeout=800)
                                loc.fill("", timeout=400)
                                loc.press_sequentially(val, delay=25)
                                loc.press("Tab")
                                chosen = val
                            except Exception:
                                pass
                        if not chosen:
                            try:
                                loc.fill(val, timeout=1200)
                                loc.dispatch_event("blur")
                                chosen = val
                            except Exception:
                                try:
                                    loc.click(timeout=800)
                                    loc.press_sequentially(val, delay=25)
                                    loc.press("Tab")
                                    chosen = val
                                except Exception:
                                    try:
                                        loc.evaluate("""(e, v) => {
                                            e.removeAttribute('readonly');
                                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                                            if (setter) { setter.call(e, v); } else { e.value = v; }
                                            e.dispatchEvent(new Event('input', { bubbles: true }));
                                            e.dispatchEvent(new Event('change', { bubbles: true }));
                                            e.dispatchEvent(new Event('blur', { bubbles: true }));
                                        }""", val)
                                        chosen = val
                                    except Exception:
                                        pass
                    if not chosen:
                        unanswered.append({**f, "error": "could not select an option"}); continue
                    ans = chosen
                else:
                    filled_ok = False
                    if re.search(r"\b(day|month|year)\b", lab_low):
                        try:
                            loc.click(timeout=1000)
                            try:
                                loc.fill(val, timeout=800)
                            except Exception:
                                loc.fill("", timeout=400)
                                loc.press_sequentially(val, delay=30)
                            loc.press("Tab")
                            filled_ok = True
                        except Exception:
                            pass
                    if not filled_ok:
                        try:
                            loc.fill(val, timeout=1500)
                            filled_ok = True
                        except Exception:
                            try:
                                loc.fill(val, force=True, timeout=1500)
                                filled_ok = True
                            except Exception:
                                pass
                    if not filled_ok:
                        try:
                            loc.evaluate("""(e, v) => {
                                e.removeAttribute('readonly');
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                                if (setter) { setter.call(e, v); } else { e.value = v; }
                                e.dispatchEvent(new Event('input', { bubbles: true }));
                                e.dispatchEvent(new Event('change', { bubbles: true }));
                                e.dispatchEvent(new Event('blur', { bubbles: true }));
                            }""", val)
                            filled_ok = True
                        except Exception:
                            pass
                    try: loc.dispatch_event("blur")
                    except Exception: pass
            filled.append(f"{label[:60]} = {ans}")
            if RE:
                RE.record_answer(label, ans, "guess" if (src == "rule" and label in PICK_GUESSED) else src)
            time.sleep(0.15)
        except Exception as e:  # keep going; report
            unanswered.append({**f, "error": str(e)[:120]})
    # Eightfold / custom skills section auto-fill
    try:
        add_skill_btn = page.locator(".addSkillButton-33WrY, button:has-text('Add Skill')").first
        if add_skill_btn.count() > 0 and add_skill_btn.is_visible(timeout=500):
            pills = page.locator("[class*='skill-pill'], [class*='skillTag']")
            if pills.count() == 0:
                add_skill_btn.click()
                time.sleep(0.4)
                s_inp = page.locator("input[data-testid*='skills-search'], input[placeholder*='Add a skill']").first
                if s_inp.count() > 0 and s_inp.is_visible():
                    s_inp.press_sequentially("Python", delay=30)
                    time.sleep(0.8)
                    res_id = s_inp.get_attribute("aria-controls")
                    if res_id:
                        ctrl = page.locator(f"#{res_id}")
                        opt = ctrl.locator("li, div, [role='option']").filter(has_text=re.compile(r"^Python$", re.I)).first
                        if opt.count() == 0:
                            opt = ctrl.locator("li, div, [role='option']").first
                        if opt.count() > 0:
                            opt.click()
                            filled.append("Skills = Python")
                            time.sleep(0.4)
    except Exception:
        pass
    return filled, unanswered, optional_skipped, needs_you


def report(url, filled, unanswered, optional_skipped, needs_you):
    if filled:
        print("\n==== FILLED ====")
        for x in filled: print("  +", x)
    if needs_you:
        print("\n==== NEEDS YOUR ANSWER (set in profile.json, marked ASK) ====")
        for f in needs_you: print("  ?", f["label"][:100], ("| options: " + " / ".join(f["options"][:8])) if f.get("options") else "")
    if unanswered:
        print("\n==== UNRESOLVED FIELDS ====")
        for f in unanswered: print("  !", f["label"][:100], ("| options: " + " / ".join((f.get("options") or [])[:8])) if f.get("options") else "", f.get("error", ""))
    if optional_skipped:
        print("\n(Voluntary EEO questions left for you: " + "; ".join(s[:40] for s in optional_skipped) + ")")
    if unanswered or needs_you:
        p = HERE / "unanswered.json"
        try:
            from tools.file_lock import FileLock
            u_lock = FileLock(p)
        except Exception:
            from contextlib import nullcontext
            u_lock = nullcontext()
        with u_lock:
            data = []
            if p.exists() and p.stat().st_size > 0:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        data = []
                except Exception:
                    data = []
            data.append({"url": url, "when": datetime.datetime.now().isoformat(timespec="minutes"),
                         "questions": [{"label": f["label"], "options": f.get("options")} for f in unanswered + needs_you]})
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_applied(url, company, role, resume, job_url=None):
    target_url = job_url or url
    path = ROOT / "applications.csv"
    try:
        from tools.file_lock import FileLock
        csv_lock = FileLock(path)
    except Exception:
        from contextlib import nullcontext
        csv_lock = nullcontext()

    with csv_lock:
        try:
            raw_rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
            cols = [c.lstrip("\ufeff") for c in raw_rows[0].keys()] if raw_rows else []
            rows = [{k.lstrip("\ufeff"): v for k, v in r.items()} for r in raw_rows]
            today = datetime.date.today().isoformat()
            host = re.sub(r"^https?://", "", target_url).split("?")[0][:60]
            hit = None
            for r in rows:
                same_co = bool(company and r.get("Company", "").strip().lower() == company.strip().lower())
                url_matches = False
                r_u = ""
                t_u = ""
                if r.get("Job URL") and target_url:
                    r_u = re.sub(r"^https?://", "", r["Job URL"]).split("?")[0].strip().rstrip("/")
                    t_u = re.sub(r"^https?://", "", target_url).split("?")[0].strip().rstrip("/")
                    if r_u and t_u and (r_u == t_u or r_u in t_u or t_u in r_u):
                        if "completed" not in r_u.lower() and "jobtasks" not in r_u.lower():
                            url_matches = True

                role_matches = False
                if role and r.get("Role"):
                    r_role = r["Role"].strip().lower()
                    t_role = role.strip().lower()
                    r_clean = re.sub(r"\[.*?\]|\(.*?\)", "", r_role).strip()
                    t_clean = re.sub(r"\[.*?\]|\(.*?\)", "", t_role).strip()
                    role_matches = (r_clean == t_clean) or (r_clean in t_clean and abs(len(r_clean) - len(t_clean)) < 8)

                if url_matches:
                    hit = r
                    break
                if same_co and role_matches:
                    # If both have URLs that clearly point to different job postings, do not treat as same role
                    if not (r_u and t_u and r_u != t_u and len(r_u) > 15 and len(t_u) > 15):
                        hit = r
                        break

            if hit is None:
                hit = {c: "" for c in cols}
                hit["ID"] = str(len(rows) + 1)
                hit["Company"] = company or host.split("/")[0]
                hit["Role"] = role or ""
                rows.append(hit)
            applied_url = target_url if target_url and "completed" not in target_url.lower() else (hit["Job URL"] or target_url)
            hit.update({"Stage": "Applied", "Date Applied": today, "Job URL": applied_url,
                        "Resume Version": resume.name if resume else hit.get("Resume Version", ""),
                        "Next Action": "Watch email for confirmation; find 1-2 contacts", "Next Action Date": today})
            for attempt in range(10):
                try:
                    w = csv.DictWriter(open(path, "w", newline="", encoding="utf-8"), fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                    break
                except OSError:
                    time.sleep(0.05 * (attempt + 1))
            print(f"Logged as Applied in applications.csv: {hit['Company']} - {hit['Role']}")
        except Exception as e:
            print(f"[Log Applied Error] {e}")
    if RE:
        try:
            RE.ledger_add(company or "Unknown", role or "Unknown", target_url, "submitted")
        except Exception:
            pass


NAV_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.disabled; };
  const t = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  const isWd = e => e.matches('[data-automation-id*="next-button" i], [data-automation-id*="NextButton" i], [data-automation-id*="submit-button" i], [data-automation-id*="SubmitButton" i], [data-automation-id*="pageFooterNextButton" i]') || !!e.closest('[data-automation-id*="next-button" i], [data-automation-id*="NextButton" i], [data-automation-id*="submit-button" i], [data-automation-id*="SubmitButton" i], [data-automation-id*="pageFooterNextButton" i]');
  const cands = [...document.querySelectorAll('button, input[type=submit], a[role=button], [role=button], a.btn, a.button, input[type=button], a[id*="submit" i], button[id*="submit" i], a[href*="apply" i], a[href*="application" i], a[data-test-id*="apply" i], [data-automation-id*="apply" i], [data-automation-id="adventureButton"]')].filter(vis)
     .filter(e => isWd(e) || !e.closest('#onetrust-consent-sdk, [id*=cookie], [class*=cookie], [class*=stepper], [class*=progress], [role=tablist], ol, [class*=step-nav], [class*=breadcrumb]'));
  const bad = /back|previous|cancel|upload|autofill|remove|delete|add another|sign in|log ?in|save for later|withdraw|replace|create account|register|sign up/i;
  const pri = [
    /^verify\s*(and|&)\s*submit(\s*application)?$/i,
    /^verify(\s*code)?$/i,
    /^confirm\s*(and|&)\s*submit$/i,
    /^submit\s*code$/i,
    /^verify$/i,
    /^confirm$/i,
    /^submit( my)? application$/i, /^submit$/i, /^send application$/i,
    /^save (and|&) continue$/i, /^continue$/i, /^next$/i, /^next step$/i,
    /^review and submit$/i, /^apply manually$/i, /^apply( now)?$/i, /^start application$/i,
    /^apply online$/i, /^begin application$/i, /^proceed$/i, /^i'?m interested$/i, /^i am interested$/i
  ];
  document.querySelectorAll('[data-af-nav]').forEach(e => e.removeAttribute('data-af-nav'));
  for (const re of pri) { const m = cands.filter(e => re.test(t(e)) && !bad.test(t(e))); const b = m[m.length - 1]; if (b) { b.dataset.afNav = '1'; return t(b); } }
  return null;
}
"""
DONE_RE = re.compile(r"application (was |has been )?(successfully )?(submitted|received)|thank you for (applying|your application|your interest)|thanks for (applying|your interest)|we('ve| have) received your application|application complete|congratulations|application submitted|^thank you!?$|your application has been submitted|application received|received your response|thank you for taking the time to apply|application (has been )?saved|your submission has been received|we have received your submission|submission successful|submission received", re.I)
BLOCK_RE = re.compile(r"captcha|verify you are human|i'?m not a robot|captcha-delivery|datadome", re.I)
DENIED_RE = re.compile(r"you have been blocked|403 forbidden|security service to protect itself|incident id: [a-f0-9]+|cf-ray|blocked by cloudflare|error code 1020", re.I)


def dismiss_cookie_banners(page):
    """Automatically dismisses cookie consent banners ('I accept', 'Accept cookies', etc.)."""
    try:
        legal = page.locator("[data-automation-id='legalNoticeAcceptButton'], #onetrust-accept-btn-handler").first
        if legal.is_visible(timeout=1000):
            legal.click()
            time.sleep(0.5)
    except Exception:
        pass
    try:
        page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button, a[role="button"]')];
            for (const b of btns) {
                const txt = (b.innerText || '').trim().toLowerCase();
                if (/^(i accept|accept all( cookies)?|accept cookies|agree|allow all|got it|close)$/i.test(txt)) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
    except Exception:
        pass


from waits import settle  # adaptive wait: replaces fixed sleeps


def click_nav(page, btn):
    """Clicks a Next/Submit button. Workday lays a transparent div[data-automation-id=click_filter]
    over its buttons, so a normal click times out with 'intercepts pointer events'. Fall back to a
    real mouse click at the button's center (lands on whatever is on top, like a person's click),
    then to a DOM click. Apply *links* (SmartRecruiters "I'm interested" -> /oneclick-ui/...) are opened directly:
    the marked one is often a hidden duplicate that can't be clicked."""
    try:
        href = btn.evaluate("e => e.tagName === 'A' && /^https?:/.test(e.href) && !/#$/.test(e.href) ? e.href : ''", timeout=2000)
        if href and re.search(r"apply|oneclick|interested|application", href + " " + (btn.inner_text(timeout=1000) or ""), re.I):
            page.goto(href, wait_until="domcontentloaded", timeout=30000)
            return True
    except Exception:
        pass
    try:
        btn.click(timeout=5000)
        return True
    except Exception as e:
        print(f"[Click] Normal click failed ({str(e).splitlines()[0][:80]}) - trying overlay click...")
    try:
        btn.scroll_into_view_if_needed(timeout=3000)
        box = btn.bounding_box()
        if box:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            return True
    except Exception:
        pass
    try:
        btn.evaluate("e => e.click()")
        return True
    except Exception:
        return False


def page_state(page):
    if "maintenance-page" in page.url.lower(): return "blocked"
    try: body = page.inner_text("body", timeout=5000)
    except Exception: body = ""
    frames = " ".join(f.url for f in page.frames)
    u = page.url.lower()
    if DONE_RE.search(body) or any(k in u for k in ["/confirmation", "/submitted", "/success", "/thank-you", "/thanks", "/complete", "apply/thank_you", "status=submitted", "/application-received"]):
        return "done"
    if re.search(r"page you are looking for doesn't exist|job is no longer available|position has been closed|this job has expired|no longer accepting applications|job requisition is closed|posting is no longer active|this posting has closed", body, re.I):
        return "closed"
    if "error=true" in u or (("greenhouse.io" in u or "boards.greenhouse.io" in u) and not any(k in u for k in ["/jobs/", "/applications/"])):
        return "closed"

    # Allow form elements a brief moment to mount if still loading
    try:
        page.locator("input:not([type=hidden]):visible, select:visible, textarea:visible, [data-automation-id='pageFooterNextButton']:visible").first.wait_for(state="visible", timeout=3000)
    except Exception:
        pass

    try:
        from account_verifier import is_verification_waiting_screen
        if is_verification_waiting_screen(page):
            return "login"
    except Exception:
        pass

    try:
        if page.locator("input:not([type=hidden]):visible, select:visible, textarea:visible, [data-automation-id='pageFooterNextButton']:visible").count() > 0:
            if is_auth_screen(page): return "login"
            return "form"
    except Exception:
        pass

    try:
        cap_loc = page.locator(".h-captcha, .g-recaptcha, iframe[src*='hcaptcha'], iframe[src*='recaptcha'], iframe[src*='turnstile'], #h-captcha, #g-recaptcha, [data-sitekey]").first
        if cap_loc.count() > 0 and cap_loc.is_visible(timeout=500):
            return "captcha"
    except Exception:
        pass

    m_denied = DENIED_RE.search(body)
    if m_denied:
        print(f"\n[DEBUG WAF] Block triggered by pattern '{m_denied.group(0)}' on {page.url}")
        return "blocked"
    if BLOCK_RE.search(body) or re.search(r"recaptcha|hcaptcha|turnstile|captcha-delivery|datadome", frames + " " + u, re.I): return "captcha"
    if is_auth_screen(page): return "login"
    return "form"


def safe_input(prompt):
    if not sys.stdin or not getattr(sys.stdin, "isatty", lambda: False)():
        print(prompt + " [autonomous headless mode: continuing]")
        return ""
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"


def main():
    if os.environ.get("AF_DEADLINE", "").isdigit():  # batch run: log the stack 10s before the batch kills this job
        import faulthandler
        faulthandler.dump_traceback_later(max(30, int(os.environ["AF_DEADLINE"]) - 10), exit=False, file=sys.stdout)
    try:  # neural matcher loads while the browser opens and signs in, not when the first question needs it
        from agents import semantic
        semantic.warm()
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--resume", default=PROFILE.get("default_resume"))
    ap.add_argument("--company"); ap.add_argument("--role")
    ap.add_argument("--overwrite", action="store_true", help="replace values the site pre-filled")
    ap.add_argument("--review", action="store_true", help="do NOT auto-submit; stop on every page for you")
    ap.add_argument("--headless", action="store_true", help="run browser in headless mode (no UI)")
    ap.add_argument("--headful", action="store_true", help="force visible browser window")
    ap.add_argument("--worker-id", type=int, default=None, help="Worker ID for multi-process parallel execution")
    ap.add_argument("--profile-dir", default=None, help="Explicit path to isolated browser profile directory")
    ap.add_argument("--block-assets", action="store_true", default=True, help="Block heavy images/media and tracking scripts for 3x speedup")
    ap.add_argument("--no-block-assets", action="store_false", dest="block_assets", help="Disable asset blocking")
    a = ap.parse_args()
    auto = not a.review
    resume = (ROOT / a.resume).resolve() if a.resume and not pathlib.Path(a.resume).is_absolute() else (pathlib.Path(a.resume) if a.resume else None)
    if resume and not resume.exists(): sys.exit(f"Resume not found: {resume}")

    # Determine headless mode
    env_headless = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
    headless_mode = False if a.headful else (True if a.headless else env_headless)

    # Worker-isolated browser profile setup
    worker_id = a.worker_id
    if a.profile_dir:
        profile_path = pathlib.Path(a.profile_dir).resolve()
    elif worker_id is not None:
        profile_path = (HERE / f".browser-profile-w{worker_id}").resolve()
    else:
        profile_path = (HERE / ".browser-profile").resolve()

    profile_path.mkdir(parents=True, exist_ok=True)
    # Clear stale locks from previously killed browser processes
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        lf = profile_path / lock_name
        if lf.exists():
            try:
                lf.unlink(missing_ok=True)
            except Exception:
                pass

    # If this is an isolated worker profile and uninitialized, copy base auth/prefs from master profile
    master_profile = (HERE / ".browser-profile").resolve()
    if worker_id is not None and master_profile.exists() and not (profile_path / "Default").exists():
        try:
            import shutil
            def _ignore_locks(src, names):
                return [n for n in names if "lock" in n.lower() or "singleton" in n.lower() or n.endswith(".tmp") or n == "Crashpad"]
            shutil.copytree(str(master_profile), str(profile_path), ignore=_ignore_locks, dirs_exist_ok=True)
        except Exception:
            pass

    import urllib.parse
    parsed_domain = urllib.parse.urlparse(a.url).netloc.lower()
    try:
        from brain.stealth_engine import get_stealth_engine
        stealth_eng = get_stealth_engine()
    except Exception:
        stealth_eng = None

    with sync_playwright() as p:
        if stealth_eng:
            kw = stealth_eng.get_launch_kwargs(parsed_domain, requested_headless=headless_mode, worker_id=worker_id, profile_dir=str(profile_path))
            stealth_js = stealth_eng.get_stealth_script(parsed_domain)
        else:
            kw = dict(
                user_data_dir=str(profile_path),
                headless=headless_mode,
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                ],
            )
            stealth_js = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
            """

        try:
            ctx = p.chromium.launch_persistent_context(**kw)  # type: ignore
        except Exception:
            kw_fallback = dict(kw)
            kw_fallback.pop("channel", None)
            ctx = p.chromium.launch_persistent_context(**kw_fallback)  # type: ignore

        ctx.add_init_script(stealth_js)
        ctx.set_default_timeout(10000)

        # Asset Blocker: 3x speedup by aborting heavy images/media and tracking pixels in headless mode
        if a.block_assets and headless_mode:
            TRACKERS = (
                "google-analytics.com", "googletagmanager.com", "hotjar.com",
                "facebook.net", "clarity.ms", "segment.io", "datadoghq-browser-agent.com",
                "doubleclick.net", "quantserve.com", "scorecardresearch.com"
            )
            def _route_filter(route):
                req = route.request
                res_type = req.resource_type
                if res_type in ("image", "media"):
                    route.abort()
                    return
                u_low = req.url.lower()
                if any(trk in u_low for trk in TRACKERS):
                    route.abort()
                    return
                route.continue_()

            try:
                ctx.route("**/*", _route_filter)
            except Exception:
                pass

        # Close any leftover tabs so we start cleanly
        while len(ctx.pages) > 1:
            try: ctx.pages[-1].close()
            except Exception: break
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"\n[AJ Pipeline] Opening URL (Headless: {headless_mode}): {a.url}")
        if a.company:
            try:
                from brain.knowledge_graph import get_kg
                kg_paths = get_kg().find_referral_paths(a.company)
                if kg_paths:
                    top_ref = kg_paths[0]
                    print(f"[JOBDEC-KG] Warm referral route found at {a.company}: {top_ref['name']} ({top_ref['role']}, Warmth: {top_ref['warmth_score']}/100)")
            except Exception:
                pass
        try:
            page.goto(a.url, wait_until="domcontentloaded", timeout=30000)
            settle(page, 3)
        except Exception as e:
            print(f"\n[Page Error] Could not load URL ({str(e).splitlines()[0][:80]}). Skipping to next job.")
            sys.exit(2)
        print(f"Mode: {'AUTO-SUBMIT (hands-free)' if auto else 'REVIEW'}")

        submitted = False
        submit_clicked = False
        final_status, auth_failed = "incomplete", False
        steps, last_sig = 0, None
        pause_retries, no_btn_retries, stuck_retries, auth_retries = 0, 0, 0, 0
        while steps < 40:
            page = ctx.pages[-1]
            try:
                page.bring_to_front()
                page.evaluate("1")
            except Exception as ex:
                if "crash" in str(ex).lower() or "closed" in str(ex).lower():
                    print("\n[Recovery] Tab crashed - reopening the application page...")
                    page = ctx.new_page()
                    page.goto(a.url, wait_until="domcontentloaded", timeout=30000)
                    settle(page, 3)
                    steps += 1
                    continue
            dismiss_cookie_banner(page)
            steps += 1

            # Handle Workday initial landing / "Apply Manually"
            if "myworkdayjobs.com" in page.url.lower() and "/apply" not in page.url.lower():
                if "candidatehome" in page.url.lower():
                    if a.url and page.url.lower() != a.url.lower():
                        print(f"\n[Workday Recovery] Redirected to {page.url} instead of application. Navigating back to job: {a.url}")
                        page.goto(a.url, wait_until="domcontentloaded", timeout=25000)
                        settle(page, 3)
                        continue
                try:
                    if handle_workday_landing(page):
                        settle(page, 3)
                        continue
                except Exception:
                    pass

            # Auto-recover from transient Workday errors
            try:
                b_check = page.inner_text("body", timeout=1500)
                if "myworkdayjobs.com" in page.url and ("something went wrong" in b_check.lower() or "please refresh the page" in b_check.lower()):
                    print("\n[Workday Recovery] Transient error detected. Reloading page...")
                    page.reload()
                    settle(page, 4)
                    continue
            except Exception:
                pass

            # Handle Ashby initial landing / "Apply for this Job"
            if "ashbyhq.com" in page.url.lower() and "/application" not in page.url.lower():
                try:
                    apply_btn = page.locator("button:has-text('Apply for this Job'), a:has-text('Apply for this Job'), button:has-text('Apply Now'), a:has-text('Apply Now'), button:has-text('Apply'), a:has-text('Apply')").first
                    if apply_btn.count() > 0 and apply_btn.is_visible(timeout=1500):
                        print("\n[Ashby Landing] Clicking 'Apply for this Job' button...")
                        apply_btn.click()
                        settle(page, 3)
                        continue
                    else:
                        clean_u = page.url.split("?")[0].rstrip("/") + "/application"
                        print(f"\n[Ashby Landing] Navigating directly to application page: {clean_u}")
                        page.goto(clean_u, wait_until="domcontentloaded", timeout=25000)
                        settle(page, 3)
                        continue
                except Exception as ex:
                    print(f"[Ashby Landing] {ex}")

            # General landing page detection when 0 form fields exist on initial load
            if steps <= 3:
                try:
                    inputs_cnt = page.locator("input:not([type=hidden]), textarea, select").count()
                    if inputs_cnt == 0:
                        gen_apply = page.locator("button, a").filter(has_text=re.compile(r"^\s*Apply\s+for\s+this\s+(?:job|role)\b|^\s*Apply\s+Now\b|^\s*Apply\b", re.I)).first
                        if gen_apply.count() > 0 and gen_apply.is_visible(timeout=1000):
                            txt = gen_apply.inner_text().strip()
                            if txt.lower() not in ("apply with linkedin", "apply with indeed"):
                                print(f"\n[Landing Page] Found '{txt}'. Clicking to open application...")
                                gen_apply.click()
                                settle(page, 3)
                                continue
                except Exception:
                    pass

            st = page_state(page)
            if st == "done":
                print("\n[SUCCESS] Confirmation page detected - application submitted.")
                log_applied(page.url, a.company, a.role, resume, job_url=a.url)
                submitted = True
                break
            if st == "closed":
                print("\n[CLOSED] Job posting is closed or no longer available. Advancing to next job.")
                final_status = "closed"
                break
            if st == "blocked":
                print("\n[BLOCKED] Site security / WAF block detected. Skipping automatically.")
                if stealth_eng:
                    stealth_eng.record_challenge(parsed_domain, "waf_block", f"WAF challenge on {page.url}")
                break

            pause_reason = None
            if st == "login":
                if RE and RE.auth_blocked(a.url):
                    print(f"\n[Account Guard] Sign-in already failed on {RE.site_key(a.url)} - not retrying (avoids a lockout). "
                          "Sign in by hand, then delete that site from auth_state.json.")
                    final_status = "skipped_account_guard"
                    break
                auth_retries += 1
                if auth_retries > 3:
                    print("\n[Auth] Authentication retry limit reached (3 attempts). Skipping automatically.")
                    auth_failed = True
                    break
                print("\n[Auth] Account/Login screen detected. Handling automatically...")
                handled = run_auth_flow(page, job_url=getattr(a, "url", ""))
                if handled:
                    settle(page, 4)
                    steps += 1
                    pause_retries = 0
                    continue
                else:
                    pause_reason = "Auth screen requires manual intervention"
            elif st == "captcha":
                pause_reason = "CAPTCHA detected on page"
                if headless_mode:
                    print("\n[CAPTCHA] Can't be solved in headless mode. Skipping automatically.")
                    break
            else:
                if "myworkdayjobs.com" in page.url:
                    try:
                        page.locator('[data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"]').wait_for(state="visible", timeout=12000)
                        time.sleep(1)
                    except Exception:
                        pass
                else:
                    try:
                        page.locator("input:not([type=hidden]), select, textarea, button[type=submit], [role=combobox]").first.wait_for(state="visible", timeout=8000)
                        time.sleep(1)
                    except Exception:
                        pass
                filled, unanswered, eeo, needs = fill_page(page, resume, a.overwrite, company=a.company or "", role=a.role or "")
                report(page.url, filled, unanswered, eeo, needs)
                if RE:
                    RE.UNANSWERED.extend(x["label"][:150] for x in unanswered + needs if x.get("required") or x in needs)
                if RE and RE.SENSITIVE_HITS and auto:
                    print(f"\n[Sensitive Question] No rule for: {RE.SENSITIVE_HITS[:3]}. Not guessing - skipping this job. "
                          "Add a rule to profile.json to answer it next time.")
                    final_status = "skipped_sensitive"
                    break
                req_open = [f for f in unanswered + needs if f.get("required") or f in needs]
                if not auto:
                    pause_reason = "review mode"
                elif req_open:
                    print(f"\n[Autonomous Guess] Proceeding past {len(req_open)} question(s) using auto-filled answers...")

            if pause_reason:
                if headless_mode and auto:
                    print(f"\n[Headless Autonomous Pause] {pause_reason}")
                    pause_retries += 1
                    if pause_retries > 2:
                        print(f"[Autonomous Skip] Cannot resolve: {pause_reason}. Advancing to next job.")
                        break
                    time.sleep(2)
                    continue
                elif headless_mode:
                    print(f"\n[Headless Pause] {pause_reason}")
                    cmd = safe_input("[Enter] retry/continue   [s] log as applied   [x] skip to next job   [q] quit  > ")
                else:
                    cmd = safe_input(f"\nPAUSED: {pause_reason}.\n[Enter] continue (after you fix/click)   [s] I submitted - log it   [x] skip to next job   [q] quit  > ")
                if cmd == "q": sys.exit(0)
                if cmd in ("x", "skip"): print("[Skip] Skipping to next job..."); break
                if cmd == "s": log_applied(page.url, a.company, a.role, resume); break
                if not auto: continue

            # auto: click the best forward button
            target = find_form_target(page)
            wd_next = page.locator("[data-automation-id='pageFooterNextButton'], [data-automation-id='bottom-navigation-next-button'], [data-automation-id='pageFooterSubmitButton'], [data-automation-id='bottom-navigation-submit-button'], [data-automation-id*='submit-button' i]").first
            if wd_next.is_visible():
                wd_next.evaluate("e => e.dataset.afNav = '1'")
                label = wd_next.inner_text().strip() or "Next"
                click_target = page
            else:
                label = target.evaluate(NAV_JS)
                click_target = target
                if not label and target != page:
                    label = page.evaluate(NAV_JS)
                    click_target = page

            if not label:
                # Re-check if auth screen appeared dynamically
                if is_auth_screen(page):
                    continue
                if submit_clicked:
                    has_err = False
                    try:
                        err_cnt = page.locator("[data-automation-id*='error' i], [class*='error' i], [data-automation-id*='validationMessage'], [aria-invalid='true']").filter(has_text=re.compile(r"error|required|invalid|must", re.I)).count()
                        has_err = err_cnt > 0
                    except Exception:
                        pass
                    if not has_err:
                        print("\n[SUCCESS] Submit was clicked and form is completed - application submitted.")
                        log_applied(page.url, a.company, a.role, resume, job_url=a.url)
                        submitted = True
                        break
                if headless_mode and auto:
                    no_btn_retries += 1
                    if no_btn_retries > 6:
                        print("\n[Headless Autonomous] No Next/Submit button detected after retries. Advancing to next job.")
                        break
                    settle(page, 3)
                    continue
                elif headless_mode:
                    print("\n[Headless] No Next/Submit button detected.")
                    cmd = safe_input("[Enter] retry   [s] log as applied   [x] skip to next job   [q] quit  > ")
                    if cmd == "s": log_applied(page.url, a.company, a.role, resume); break
                    if cmd in ("x", "skip"): print("[Skip] Skipping to next job..."); break
                    if cmd == "q": sys.exit(0)
                    continue
                else:
                    safe_input("\nNo Next/Submit button found. Click it yourself, then press [Enter]  > "); continue

            step_snapshot = page.evaluate("() => [...document.querySelectorAll('h1, h2, h3, [data-automation-id*=\"step\" i]')].map(e => e.innerText.trim()).filter(Boolean).join('|') + '::' + [...document.querySelectorAll('label, legend')].map(e => e.innerText.trim()).slice(0, 10).join('|')")
            sig = (page.url, label, step_snapshot)
            if sig == last_sig:
                if headless_mode and auto:
                    stuck_retries += 1
                    # Check for validation messages
                    try:
                        err_msgs = page.evaluate("() => [...document.querySelectorAll('[data-automation-id*=\"error\" i], [class*=\"error\" i], [data-automation-id*=\"validationMessage\"]')].filter(e => (e.offsetParent !== null || e.getClientRects().length > 0) && e.innerText && e.innerText.trim().length > 1).map(e => e.innerText.trim())")
                        if err_msgs:
                            print(f"[Validation Alert] Site reported: {'; '.join(err_msgs[:3])}")
                            FIX_HINTS[:] = [" ".join(m.split()).lower() for m in err_msgs[:20]]
                            try:
                                fix_btn = page.locator("button, a").filter(has_text=re.compile(r"Go to Next Issue|Next Issue|Fix Issue", re.I)).first
                                if fix_btn.count() > 0 and fix_btn.is_visible(timeout=800):
                                    print("[Validation Alert] Clicking 'Go to Next Issue' to expose problematic field...")
                                    fix_btn.click(force=True)
                                    time.sleep(1)
                            except Exception:
                                pass
                            try:
                                filled_re, _, _, _ = fill_page(page, resume, overwrite=False, company=getattr(a, "company", ""), role=getattr(a, "role", ""))
                                if filled_re:
                                    print(f"[Validation Repair] Re-filled {len(filled_re)} fields: {', '.join(filled_re)}")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Check for validation messages or HTML5 invalid inputs
                    try:
                        invalids = page.evaluate("""() => {
                            const invs = [...document.querySelectorAll(':invalid')];
                            return invs.map(e => ({
                                tag: e.tagName.toLowerCase(),
                                type: (e.type || '').toLowerCase(),
                                name: e.name || '',
                                id: e.dataset.afId || e.id || '',
                                msg: e.validationMessage || ''
                            }));
                        }""")
                        if invalids:
                            print(f"[Validation Repair] Auto-remedying {len(invalids)} invalid field(s)...")
                            for inv in invalids:
                                el_id = inv.get("id")
                                if not el_id: continue
                                loc_inv = page.locator(f"[data-af-id='{el_id}']").first
                                if loc_inv.count() > 0:
                                    if inv["type"] == "checkbox":
                                        loc_inv.check(force=True)
                                    elif inv["tag"] == "select":
                                        loc_inv.select_option(index=1)
                                    elif inv["type"] in ("text", "tel", "email", "url"):
                                        if not loc_inv.input_value():
                                            loc_inv.fill("N/A")
                    except Exception:
                        pass
                    if stuck_retries > 5:
                        if "submit" in label.lower():
                            print("[Submit Force] Attempting emergency direct form submission before advancing...")
                            try:
                                page.evaluate("""() => {
                                    const f = document.querySelector('form');
                                    if (f && typeof f.requestSubmit === 'function') { f.requestSubmit(); return true; }
                                    const b = document.querySelector('[data-af-nav="1"], button[type=submit], button.ashby-application-form-submit-button');
                                    if (b) { b.click(); return true; }
                                    return false;
                                }""")
                                time.sleep(3)
                                if page_state(page) == "done" or DONE_RE.search(page.inner_text("body", timeout=1000)):
                                    print("\n[SUCCESS] Confirmation page detected post emergency submit - application submitted.")
                                    log_applied(page.url, a.company, a.role, resume, job_url=a.url)
                                    submitted = True
                                    break
                            except Exception:
                                pass
                        print("\n[Headless Autonomous] Page did not advance after multiple clicks. Advancing to next job.")
                        break
                    print(f"\n[Headless Autonomous] Waiting for page transition / retrying advance (attempt {stuck_retries}/5)...")
                    settle(page, 4)
                    # Re-click nav button in case pointer event was swallowed
                    try:
                        click_nav(page, click_target.locator('[data-af-nav="1"]').first)
                    except Exception:
                        pass
                    continue
                elif headless_mode:
                    print("\n[Headless] Page did not advance after click (possible validation error).")
                    cmd = safe_input("[Enter] retry   [s] log as applied   [x] skip to next job   [q] quit  > ")
                    if cmd == "s": log_applied(page.url, a.company, a.role, resume, job_url=a.url); break
                    if cmd in ("x", "skip"): print("[Skip] Skipping to next job..."); break
                    if cmd == "q": sys.exit(0)
                else:
                    cmd = safe_input("\nPage did not change after clicking - probably a validation error. Fix it in the browser, then [Enter] (or q)  > ")
                    if cmd == "q": sys.exit(0)
                last_sig = None; continue
            last_sig = sig
            FIX_HINTS.clear()  # new page: old validation messages no longer apply
            no_btn_retries = 0
            stuck_retries = 0
            print(f"\n>> Clicking '{label}'")
            try: page.keyboard.press("Escape"); time.sleep(0.4)
            except Exception: pass
            if not click_nav(page, click_target.locator('[data-af-nav="1"]').first):
                print("[Click] Could not click the button - treating as no-advance.")
            if "submit" in label.lower():
                submit_clicked = True
                print("[Submit] Submit clicked! Waiting for submission processing...")
                try: page.wait_for_load_state("networkidle", timeout=8000)
                except Exception: pass
                # Check if a verification modal or code input appeared immediately post-submit
                try:
                    sec_inputs = page.locator(
                        "input[name*='verification' i], input[id*='verification' i], input[placeholder*='verification' i], input[aria-label*='verification' i], "
                        "input[name*='passcode' i], input[id*='passcode' i], input[placeholder*='passcode' i], input[aria-label*='passcode' i], "
                        "input[name*='security_code' i], input[id*='security_code' i], input[placeholder*='security_code' i], input[aria-label*='security_code' i], "
                        "input[name*='otp' i], input[id*='otp' i], input[placeholder*='otp' i], input[aria-label*='otp' i], "
                        "input[aria-label*='digit' i][aria-label*='six' i], input[aria-label*='digit' i][aria-label*='6' i]"
                    )
                    if sec_inputs.first.is_visible(timeout=3000):
                        print("\n[Security Code] Verification code input appeared post-submit! Listening to Gmail...")
                        try:
                            import importlib
                            import gmail_auth
                            importlib.reload(gmail_auth)
                            fetch_code_fn = gmail_auth.fetch_verification_code
                        except Exception:
                            from gmail_auth import fetch_verification_code as fetch_code_fn
                        target_company = getattr(a, "company", "")
                        code = fetch_code_fn(timeout_sec=45, poll_interval=3, search_term=target_company)
                        if code:
                            print(f"[Security Code] Submitting verification code: {code}")
                            n_in = sec_inputs.count()
                            if n_in > 1:
                                for idx in range(min(n_in, len(code))):
                                    try:
                                        inp = sec_inputs.nth(idx)
                                        inp.fill(code[idx])
                                        inp.dispatch_event("input")
                                        inp.dispatch_event("change")
                                    except Exception:
                                        pass
                            else:
                                sec_inputs.first.fill(code)
                                try:
                                    sec_inputs.first.click()
                                    page.keyboard.type(code, delay=40)
                                except Exception:
                                    pass
                            time.sleep(1)
                            v_btn = page.locator("button:has-text('Verify'), input[type=submit], button:has-text('Submit'), [role=button]:has-text('Verify')").first
                            if v_btn.is_visible():
                                print("[Security Code] Clicking verification submit button...")
                                try:
                                    v_btn.click(timeout=3000)
                                except Exception:
                                    try:
                                        v_btn.click(force=True, timeout=2000)
                                    except Exception:
                                        v_btn.dispatch_event("click")
                                time.sleep(4)
                except Exception as ex:
                    print(f"[Security Code Post-Submit Check] {ex}")

                # Check if an email verification link was sent post-submit
                try:
                    from account_verifier import is_verification_waiting_screen, verify_account_and_proceed, check_post_submit_verification
                    clean_co = re.sub(r"\[.*?\]|\(.*?\)", "", getattr(a, "company", "")).split("-")[0].strip()
                    if is_verification_waiting_screen(page):
                        print("\n[Account Verification] Verification required post-submit! Listening to Gmail...")
                        verify_account_and_proceed(page, timeout_sec=45, tenant_hint=clean_co, job_url=getattr(a, "url", ""))
                    else:
                        check_post_submit_verification(page, company=clean_co, timeout_sec=6)
                except Exception as ex:
                    print(f"[Account Verification Post-Submit Check] {ex}")
                for _ in range(5):
                    time.sleep(2)
                    try:
                        u_now = page.url.lower()
                        b_text = page.inner_text("body", timeout=1500)
                        if page_state(page) == "done" or DONE_RE.search(b_text) or any(k in u_now for k in ["/confirmation", "/submitted", "/success", "/thank-you", "/thanks", "/complete", "apply/thank_you"]):
                            print("\n[SUCCESS] Confirmation page detected - application submitted.")
                            log_applied(page.url, a.company, a.role, resume, job_url=a.url)
                            submitted = True
                            break
                        if page.locator("input:not([type=hidden]):visible").count() == 0 and not re.search(r"error|required|missing", b_text, re.I):
                            print("\n[SUCCESS] Form cleared without error - application submitted.")
                            log_applied(page.url, a.company, a.role, resume, job_url=a.url)
                            submitted = True
                            break
                    except Exception:
                        pass
                if submitted:
                    break
            else:
                try: page.wait_for_load_state("domcontentloaded", timeout=15000)
                except PWTimeout: pass
                settle(page, 4)
        if RE and not submitted:
            try:  # page snapshot for the site fixer's offline replay (scripts stripped)
                snap = page.content()
                snap = re.sub(r"(?is)<script.*?</script>", "", snap)
                d = RE.RECORDS_DIR / datetime.date.today().isoformat()
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{RE._slug(a.company or '', a.role or '')}.html").write_text(snap, encoding="utf-8")
            except Exception:
                pass
        if stealth_eng and submitted:
            stealth_eng.record_success(parsed_domain)
        if RE:
            if submitted:
                final_status = "submitted"
                if "myworkday" in a.url:
                    RE.record_auth(a.url, True)
            elif auth_failed:
                RE.record_auth(a.url, False)
            rec = RE.write_record(a.company or "", a.role or "", a.url, final_status)
            g = sum(1 for x in RE.ANSWERS if x["source"] == "guess")
            print(f"[Record] {final_status}: {len(RE.ANSWERS)} answers ({g} guessed) saved to {rec.relative_to(HERE)}")
        if submitted:
            sys.exit(0)
        else:
            sys.exit(2)


if __name__ == "__main__":
    main()

