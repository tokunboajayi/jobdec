"""OpenRouter chat completions (OpenAI format): one place for the key, model and retries.
Key: OPENROUTER_API_KEY in the candidate's .env. Model: OPENROUTER_MODEL, else DEFAULT_MODEL."""
import json
import os
import time
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"
FALLBACK_MODELS = (
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.3-70b-instruct",
)
# Tried last, when the paid models fail (2026-11-11: account at $0 credits -> HTTP 402 on every real request).
# shortcut: free-tier models are rate-limited and may log prompts; add credits to go back to the paid ones.
# OPENROUTER_FREE_FALLBACK=0 turns this off.
FREE_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
    "baidu/ernie-5.5-flash-preview:free",
)


class OpenRouterError(Exception):
    pass


def available():
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("ANTHROPIC_API_KEY", "").strip())


def _anthropic_fallback(system, messages, max_tokens=600, temperature=0.3, timeout=20):
    ankey = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not ankey or ankey == "test-key-not-real":
        return None
    req_body = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [
            {"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")}
            for m in messages
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": ankey,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            adata = json.loads(resp.read().decode("utf-8"))
        blocks = adata.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if text:
            u = adata.get("usage") or {}
            return text, {
                "prompt_tokens": u.get("input_tokens", 0),
                "completion_tokens": u.get("output_tokens", 0),
                "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0),
            }
    except Exception:
        return None
    return None


def chat(system, messages, max_tokens=600, temperature=0.3, json_mode=False, timeout=20):
    """messages: [{"role": "user"|"assistant", "content": str}]. Returns (text, usage). Raises OpenRouterError."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        fb = _anthropic_fallback(system, messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        if fb:
            return fb
        raise OpenRouterError("no OPENROUTER_API_KEY")
    primary_model = os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL
    models_to_try = [primary_model]
    if key != "test-key-not-real":
        for m in FALLBACK_MODELS + (FREE_MODELS if os.getenv("OPENROUTER_FREE_FALLBACK", "1") != "0" else ()):
            if m not in models_to_try:
                models_to_try.append(m)

    data = {}
    last_err = None
    for model_name in models_to_try:
        payload = {"model": model_name,
                   "messages": [{"role": "system", "content": system}, *messages],
                   "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")
        for attempt in (1, 2):
            req = urllib.request.Request(URL, data=body, method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                last_err = None
                break
            except urllib.error.HTTPError as e:
                if attempt == 1 and (e.code == 429 or e.code >= 500):
                    time.sleep(2)
                    continue
                try:
                    detail = json.loads(e.read().decode("utf-8", "ignore")).get("error", {}).get("message", "")
                except Exception:
                    detail = ""
                last_err = OpenRouterError(f"OpenRouter HTTP {e.code}" + (f": {detail[:160]}" if detail else ""))
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = OpenRouterError(f"OpenRouter unreachable ({type(e).__name__})")
                break
        if data and data.get("choices"):
            break

    if last_err is not None and not data:
        if key != "test-key-not-real":
            fb = _anthropic_fallback(system, messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            if fb:
                return fb
        raise last_err from None

    choices = data.get("choices") or []
    if not choices:
        if key != "test-key-not-real":
            fb = _anthropic_fallback(system, messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
            if fb:
                return fb
        raise OpenRouterError(f"OpenRouter returned no answer ({str((data.get('error') or {}).get('message', 'no choices'))[:120]})")
    finish = choices[0].get("finish_reason") or ""
    text = ((choices[0].get("message") or {}).get("content") or "").strip()
    if finish.lower() != "stop" or not text:
        reason = f"{finish} / SAFETY" if finish == "content_filter" else (finish or "empty reply")
        raise OpenRouterError(f"OpenRouter stopped early ({reason})")
    return text, data.get("usage") or {}
