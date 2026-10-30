"""
Shared Claude client for all agents: config, structured output, daily budget cap, logging.

Every call returns a validated Pydantic object or None. None always means "fall back to rules" -
no key, budget spent, refusal, API error, or the agent is switched off in strategy.json.
"""
import datetime, json, os, pathlib, threading
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
AUTOFILL = HERE.parent
LOG_DIR = HERE / "logs"
CACHE_DIR = HERE / "cache"
USAGE_FILE = HERE / "usage.json"
ENV_PATH = AUTOFILL.parent.parent / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except Exception:
    pass

DEFAULTS = {
    "enabled": True,
    "engine": "auto",                 # auto = AI when ANTHROPIC_API_KEY is set, else rule-based | local | ai
    "models": {                       # tier -> model; change here, not in code
        "fast": "claude-haiku-5-5",     # high-volume reading: job scoring, email triage
        "writer": "claude-sonnet-5-5",  # resume ordering, form answers, outreach notes
        "expert": "claude-opus-5-5",    # site fixer (debugging code from logs + page snapshots)
    },
    "autonomy": {                     # auto = act without asking | off = use rule-based fallback
        "job_scout": "auto",
        "resume_tailor": "auto",
        "cover_letter": "auto",       # per-job cover letter (same facts as the generic one)
        "form_answerer": "auto",
        "outreach_drafter": "auto",   # always drafts only - never sends
        "inbox_analyst": "auto",
        "site_fixer": "auto",         # rules auto-applied; code patches applied only if replay tests pass
    },
    "daily_budget_usd": 3.0,
    "scout_limit_per_run": 150,
}

# $ per 1M tokens (input, output) - for the budget guard only
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}  # support server-side refusal fallbacks

_lock = threading.Lock()
_client = None


def config():
    try:
        s = json.loads((AUTOFILL / "strategy.json").read_text(encoding="utf-8")).get("agents", {})
    except Exception:
        s = {}
    cfg = {**DEFAULTS, **s}
    cfg["models"] = {**DEFAULTS["models"], **s.get("models", {})}
    cfg["autonomy"] = {**DEFAULTS["autonomy"], **s.get("autonomy", {})}
    return cfg


def has_credentials():
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def active(agent):
    """True if this agent should run: agents enabled, autonomy not 'off', and an API key present."""
    c = config()
    return bool(c["enabled"] and c["autonomy"].get(agent, "auto") != "off" and has_credentials())


def engine(agent):
    """'ai' (Claude API), 'local' (rule-based, free) or 'off' for this agent."""
    c = config()
    if not c["enabled"] or c["autonomy"].get(agent, "auto") == "off":
        return "off"
    mode = c.get("engine", "auto")
    if mode != "local" and has_credentials():
        return "ai"
    return "local" if mode in ("auto", "local") else "off"


def _today():
    return datetime.date.today().isoformat()


def spent_today():
    try:
        u = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    return u.get(_today(), {}).get("usd", 0.0)


def _record_usage(model, usage, agent):
    pin, pout = PRICES.get(model, (4.0, 20.0))
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    usd = (usage.input_tokens * pin + cached * pin * 0.1 + created * pin * 1.25 + usage.output_tokens * pout) / 1e6
    with _lock:
        try:
            u = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            u = {}
        d = u.setdefault(_today(), {"usd": 0.0, "calls": 0, "by_agent": {}})
        d["usd"] = round(d["usd"] + usd, 5)
        d["calls"] += 1
        d["by_agent"][agent] = round(d["by_agent"].get(agent, 0.0) + usd, 5)
        USAGE_FILE.write_text(json.dumps(u, indent=2), encoding="utf-8")
    return usd


def _log(agent, model, system, user, result, usd, error=""):
    LOG_DIR.mkdir(exist_ok=True)
    rec = {"when": datetime.datetime.now().isoformat(timespec="seconds"), "agent": agent, "model": model,
           "usd": round(usd, 5), "error": error, "input": user[:4000], "output": result}
    with _lock, open(LOG_DIR / f"{_today()}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=3, timeout=180.0)
    return _client


def ask(agent, tier, system, user, schema, effort=None, max_tokens=16000):
    """One structured call. Returns a validated `schema` instance, or None (caller falls back to rules)."""
    if not active(agent):
        return None
    cfg = config()
    if spent_today() >= cfg["daily_budget_usd"]:
        _log(agent, "", "", user, None, 0, "daily budget reached - using rule-based fallback")
        return None
    model = cfg["models"][tier]
    kwargs: dict[str, Any] = dict(
        model=model, max_tokens=max_tokens,
        # stable system prompt first so it can be cached across calls
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    if effort:
        kwargs["output_config"] = {"effort": effort}
    import anthropic
    try:
        if model in FALLBACK_MODELS:
            # server-side refusal fallback: if a safety classifier declines, the API retries on a fallback model
            resp = client().beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client().messages.parse(**kwargs)
    except anthropic.AuthenticationError:
        _log(agent, model, system, user, None, 0, "authentication failed - check ANTHROPIC_API_KEY")
        return None
    except anthropic.RateLimitError:
        _log(agent, model, system, user, None, 0, "rate limited")
        return None
    except anthropic.BadRequestError as e:
        _log(agent, model, system, user, None, 0, f"bad request: {e.message[:300]}")
        return None
    except anthropic.APIStatusError as e:
        _log(agent, model, system, user, None, 0, f"api error {e.status_code}")
        return None
    except anthropic.APIConnectionError:
        _log(agent, model, system, user, None, 0, "network error")
        return None
    usd = _record_usage(model, resp.usage, agent)
    if resp.stop_reason == "refusal":
        _log(agent, model, system, user, None, usd, "refusal")
        return None
    if resp.stop_reason == "max_tokens":
        _log(agent, model, system, user, None, usd, "hit max_tokens")
        return None
    parsed = getattr(resp, "parsed_output", None)
    _log(agent, model, system, user, parsed.model_dump() if parsed is not None else None, usd,
         "" if parsed is not None else "no parsed output")
    return parsed


# ---------------------------------------------------------------- small JSON cache helpers
def cache_get(name, key):
    try:
        return json.loads((CACHE_DIR / f"{name}.json").read_text(encoding="utf-8")).get(key)
    except Exception:
        return None


def cache_put(name, key, value):
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"{name}.json"
    with _lock:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        d[key] = value
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
