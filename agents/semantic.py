"""
Pretrained neural embeddings, run locally and free (sentence-transformers, all-MiniLM-L6-v2, ~90 MB).
Turns text into meaning-vectors so "LLM orchestration" can match "agentic workflow design" even with
no shared words. No training and no API: the model is downloaded once and cached by sentence-transformers.

Used by agents/local.py (job fit, bullet ranking) and fill.py (matching new question wordings to known
answers). Everything falls back to keyword matching if the package or model isn't available.
Turn off with strategy.json -> agents.semantic = false.
"""
import functools, json, pathlib, re

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
AUTOFILL = pathlib.Path(__file__).resolve().parent.parent
_model = None
_failed = False


def available():
    global _failed
    if _failed:
        return False
    try:
        cfg = json.loads((AUTOFILL / "strategy.json").read_text(encoding="utf-8")).get("agents", {})
        if cfg.get("semantic", True) is False:
            return False
        import importlib.util
        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:
        return False


import threading
_lock = threading.Lock()


def model():
    global _model, _failed
    with _lock:  # warm() may be loading it in the background already: wait for that instead of loading twice
        if _model is None and not _failed:
            try:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(MODEL_NAME)
            except Exception:
                _failed = True
    return _model


def warm():
    """Start loading the model in the background (~25s on this laptop) so it overlaps page loads and sign-in."""
    if available() and _model is None:
        threading.Thread(target=model, daemon=True).start()


@functools.lru_cache(maxsize=4096)
def _embed_one(text):
    m = model()
    if m is None:
        raise RuntimeError("SentenceTransformer model is not available")
    return m.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]


def embed(texts):
    import numpy as np
    return np.stack([_embed_one(t) for t in texts])


def chunks(jd, limit=120):
    """Job-description sentences/lines worth comparing (30-400 chars)."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", jd or "")
    return [p.strip() for p in parts if 30 <= len(p.strip()) <= 400][:limit]


def bullet_scores(jd, bullets):
    """For each bullet: cosine similarity to its best-matching job-description sentence (0..1)."""
    cs = chunks(jd)
    if not cs or not bullets or model() is None:
        return None
    sims = embed(bullets) @ embed(cs).T
    return [float(x) for x in sims.max(axis=1)]


def fit_signal(jd, texts, top=5):
    """Mean of the top-N bullet similarities: how strongly the resume's content matches the posting."""
    s = bullet_scores(jd, texts)
    if not s:
        return None
    s = sorted(s, reverse=True)[:top]
    return sum(s) / len(s)


def nearest(query, candidates):
    """(index, similarity) of the closest candidate string, or (None, 0)."""
    if not candidates or model() is None:
        return None, 0.0
    sims = embed(candidates) @ embed([query])[0]
    i = int(sims.argmax())
    return i, float(sims[i])


def known_answers():
    """(label, value) pairs answered by explicit profile.json rules on past applications (records/)."""
    import results_engine as RE
    seen = {}
    for p in sorted((AUTOFILL / "records").glob("*/*.json")):
        try:
            for a in json.loads(p.read_text(encoding="utf-8")).get("answers", []):
                lab = re.sub(r"[*:\s]+$", "", a.get("label", "")).strip()
                v = str(a.get("value") or "").strip()
                if re.match(r"^(select( one)?|choose( one)?|please select|--.*--|-+)\W*$", v, re.I):
                    continue  # a placeholder that got recorded as an answer must never be learned
                if a.get("source") == "rule" and v and lab and not RE.SENSITIVE_RE.search(lab):
                    seen.setdefault(lab.lower(), (lab, a["value"]))
        except Exception:
            continue
    return list(seen.values())


def _entities(text):
    """Names and numbers that change a question's meaning (e.g. 'Canada' vs 'United States')."""
    words = re.findall(r"[A-Za-z][A-Za-z.]+|\d+", text)
    return {w.lower() for i, w in enumerate(words) if (i > 0 and w[0].isupper()) or w.isdigit()}


def known_answer(label, threshold=0.72):
    """Answer a new wording of a question already answered by a rule. Never used for sensitive questions.
    Calibrated on MiniLM: paraphrases score ~0.70-0.80, but 'authorized in Canada' vs '...United States'
    also scores 0.71 - so every name/number in the new question must appear in the matched one."""
    bank = known_answers()
    if not bank:
        return None
    labels = [b[0] for b in bank]
    i, s = nearest(label, labels)
    try:  # long labels bury the question ("To be eligible ... Please indicate the state ...") - match the core too
        from .options import core_question
        core = core_question(label)
        if core and core.lower() != label.lower().rstrip("*: ?"):
            j, t = nearest(core, labels)
            if j is not None and t > s:
                i, s, label = j, t, core
    except Exception:
        pass
    if i is None or s < threshold:
        return None
    if not _entities(label) <= _entities(bank[i][0]) | {w.lower() for w in re.findall(r"[A-Za-z]+", bank[i][0])}:
        return None
    return bank[i][0], bank[i][1], round(s, 3)
