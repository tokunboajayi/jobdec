"""
AJ AGENT BRAIN // CONTINUALLY UPDATING & IMPROVING ANTI-BOT ENGINE
Monitors WAF/bot challenge signatures across all job portals, maintains
dynamic domain reputation and stealth tiers, and automatically tunes
fingerprint evasions, latency profiles, and browser launch arguments.
"""
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
METRICS_FILE = HERE / "domain_metrics.json"
RULES_FILE = HERE / "rules.json"

_LOCK = threading.Lock()

# Stealth Tiers
TIER_STANDARD = "standard"        # Clean headless execution (Greenhouse, Lever, standard ATS)
TIER_ELEVATED = "elevated"        # Sensitive WAF (Workday, Ashby, SmartRecruiters) -> Real Chrome, HTTP/2, randomized typing
TIER_HARDENED = "hardened"        # Aggressive Bot Defense (Cloudflare Turnstile, Akamai) -> Max stealth JS, human jitter
TIER_MANUAL = "manual_required"   # Hard CAPTCHA / Bot block -> routes to visible headful or manual apply


class StealthEngine:
    """Continuously evolving anti-bot detection and browser stealth manager."""

    def __init__(self, brain_dir: Optional[pathlib.Path] = None):
        self.brain_dir = brain_dir or HERE
        self.metrics_file = self.brain_dir / "domain_metrics.json"
        self.rules_file = self.brain_dir / "rules.json"
        self._chrome_path = self._detect_chrome_executable()

    @staticmethod
    def _detect_chrome_executable() -> Optional[str]:
        """Locates installed Google Chrome binary on Windows/macOS/Linux."""
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            "/usr/bin/google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return shutil.which("google-chrome") or shutil.which("chrome")

    def _load_json(self, p: pathlib.Path) -> Dict[str, Any]:
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_json(self, p: pathlib.Path, data: Any):
        try:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_domain_tier(self, domain: str) -> str:
        """Determines the current stealth tier for a target domain."""
        dom = domain.lower().strip()
        metrics = self._load_json(self.metrics_file)
        d_data = metrics.get("domains", {}).get(dom, {})
        return d_data.get("stealth_tier", TIER_STANDARD)

    def record_challenge(self, domain: str, challenge_type: str, details: str = "") -> str:
        """
        Records a detected WAF, Cloudflare, Akamai, or CAPTCHA challenge.
        Automatically promotes the domain to a higher stealth tier.
        """
        dom = domain.lower().strip()
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        with _LOCK:
            metrics = self._load_json(self.metrics_file)
            doms = metrics.setdefault("domains", {})
            d = doms.setdefault(dom, {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "challenges": 0,
                "stealth_tier": TIER_STANDARD,
                "challenge_history": []
            })
            d["challenges"] = d.get("challenges", 0) + 1
            d["last_challenge"] = now
            d["challenge_history"] = d.get("challenge_history", [])[-10:] + [{
                "type": challenge_type,
                "details": details[:200],
                "time": now
            }]

            # Adaptive tier escalation logic
            ch_count = d["challenges"]
            if ch_count >= 3:
                d["stealth_tier"] = TIER_MANUAL
            elif ch_count >= 2:
                d["stealth_tier"] = TIER_HARDENED
            else:
                d["stealth_tier"] = TIER_ELEVATED

            self._save_json(self.metrics_file, metrics)

            # Sync rule into rules.json if promoted to manual
            if d["stealth_tier"] == TIER_MANUAL:
                rules = self._load_json(self.rules_file)
                ff = rules.setdefault("fast_fail_domains", [])
                if dom not in ff:
                    ff.append(dom)
                    self._save_json(self.rules_file, rules)

            return d["stealth_tier"]

    def record_success(self, domain: str):
        """Reinforces confidence in current stealth settings upon clean execution."""
        dom = domain.lower().strip()
        with _LOCK:
            metrics = self._load_json(self.metrics_file)
            doms = metrics.setdefault("domains", {})
            d = doms.setdefault(dom, {})
            d["successes"] = d.get("successes", 0) + 1
            d["consecutive_clean"] = d.get("consecutive_clean", 0) + 1

            # If clean 5 times in a row, gradually de-escalate if not manual
            if d.get("consecutive_clean", 0) >= 5 and d.get("stealth_tier") == TIER_HARDENED:
                d["stealth_tier"] = TIER_ELEVATED

            self._save_json(self.metrics_file, metrics)

    def get_launch_kwargs(self, domain: str, requested_headless: bool = True, worker_id: Optional[int] = None, profile_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates dynamically optimized Playwright persistent context kwargs
        based on target domain reputation and stealth tier.
        Supports worker isolation for multi-process parallel execution.
        """
        tier = self.get_domain_tier(domain)
        if profile_dir:
            user_data_dir = str(profile_dir)
        elif worker_id is not None:
            user_data_dir = str(ROOT / f".browser-profile-w{worker_id}")
        else:
            user_data_dir = str(ROOT / ".browser-profile")

        # Viewport with subtle natural randomization to prevent fingerprint clustering
        vp_width = 1280 + random.choice([0, 8, 16])
        vp_height = 900 + random.choice([0, 10, 20])

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
        ]

        # Use modern new headless mode if headless is requested
        if requested_headless:
            args.append("--headless=new")

        # User-Agent matching standard desktop Google Chrome 129
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        )

        kwargs: Dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": False if tier == TIER_MANUAL else requested_headless,
            "viewport": {"width": vp_width, "height": vp_height},
            "user_agent": ua,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "args": args,
            "ignore_default_args": ["--enable-automation"],
        }

        # Prefer real installed Google Chrome binary for authentic TLS & WebGL
        if self._chrome_path:
            kwargs["channel"] = "chrome"

        return kwargs

    def get_stealth_script(self, domain: str) -> str:
        """
        Generates advanced anti-detection JavaScript to inject into every frame.
        Thoroughly patches navigator, chrome runtime, WebGL, permissions, and plugins.
        """
        tier = self.get_domain_tier(domain)

        return """
        (() => {
            // 1. Wipe webdriver indicator cleanly
            try {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });
                delete navigator.__proto__.webdriver;
            } catch (e) {}

            // 2. Realistic Chrome runtime and window properties
            try {
                if (!window.chrome) {
                    window.chrome = {};
                }
                window.chrome.runtime = window.chrome.runtime || {
                    connect: () => {},
                    sendMessage: () => {},
                    onMessage: { addListener: () => {} }
                };
                window.chrome.loadTimes = window.chrome.loadTimes || function() {
                    return {
                        requestTime: performance.now() / 1000,
                        startLoadTime: performance.now() / 1000,
                        commitLoadTime: performance.now() / 1000,
                        finishDocumentLoadTime: performance.now() / 1000,
                        finishLoadTime: performance.now() / 1000,
                        firstPaintTime: performance.now() / 1000,
                        firstPaintAfterLoadTime: 0,
                        navigationType: 'Other'
                    };
                };
                window.chrome.csi = window.chrome.csi || function() {
                    return { onLoad: performance.now(), pageT: performance.now(), startE: performance.now(), tran: 15 };
                };
                window.chrome.app = window.chrome.app || {
                    isInstalled: false,
                    InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                    RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
                };
            } catch (e) {}

            // 3. Realistic Plugins Array
            try {
                const pluginMocks = [
                    { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
                ];
                Object.defineProperty(navigator, 'plugins', {
                    get: () => pluginMocks,
                    configurable: true
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                    configurable: true
                });
            } catch (e) {}

            // 4. Permissions API query mask
            try {
                if (navigator.permissions && navigator.permissions.query) {
                    const origQuery = navigator.permissions.query.bind(navigator.permissions);
                    navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            origQuery(parameters)
                    );
                }
            } catch (e) {}

            // 5. WebGL Vendor & Renderer Masking
            try {
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    // UNMASKED_VENDOR_WEBGL
                    if (parameter === 37445) {
                        return 'Google Inc. (Intel)';
                    }
                    // UNMASKED_RENDERER_WEBGL
                    if (parameter === 37446) {
                        return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                    }
                    return getParameter.apply(this, arguments);
                };
            } catch (e) {}
        })();
        """

    def get_typing_delay_range(self, domain: str) -> Tuple[int, int]:
        """Provides humanized typing speed based on domain sensitivity."""
        tier = self.get_domain_tier(domain)
        if tier in (TIER_HARDENED, TIER_MANUAL):
            return (40, 95)   # Slower, natural human cadences
        elif tier == TIER_ELEVATED:
            return (25, 60)
        return (15, 40)


_GLOBAL_STEALTH = None

def get_stealth_engine() -> StealthEngine:
    global _GLOBAL_STEALTH
    if _GLOBAL_STEALTH is None:
        _GLOBAL_STEALTH = StealthEngine()
    return _GLOBAL_STEALTH
