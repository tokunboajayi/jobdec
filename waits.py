"""Adaptive waits shared by fill.py and auth_manager.py: move on as soon as the page is ready."""
import time

SIG_JS = "() => location.href + '|' + document.querySelectorAll('input,select,textarea,button').length + '|' + (document.body ? document.body.innerText.length : 0)"


def settle(page, max_s=3.0, quiet=0.6):
    """Wait until the page stops changing (URL, field count, text length steady for `quiet` s), at most max_s.
    Replaces fixed sleeps: fast pages move on in ~0.6s, slow ones still get the full max_s."""
    try:
        # Fast-check and wait for async loading skeletons to detach (e.g. Oracle JET cx-select--loading)
        page.wait_for_selector(".cx-select--loading, [aria-busy='true'], .loading-skeleton", state="detached", timeout=3500)
    except Exception:
        pass
    end = time.time() + max_s
    last, stable_since = None, time.time()
    while time.time() < end:
        try:
            sig = page.evaluate(SIG_JS)
        except Exception:
            sig = None  # mid-navigation
        now = time.time()
        if sig != last:
            last, stable_since = sig, now
        elif sig is not None and now - stable_since >= quiet:
            return
        time.sleep(0.15)
