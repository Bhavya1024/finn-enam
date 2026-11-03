"""
Provider-agnostic LLM wrapper with model routing + disk caching.

`route` picks a tier from config.MODELS. Swap `_call_anthropic` for whatever
provider you like — the rest of the pipeline only relies on (prompt) -> str.
Every successful call is cached by a hash of (route, model, prompt), so re-runs
during a build cost nothing. Failures are never cached.

Smoke test against the real API (needs ANTHROPIC_API_KEY or an `ant auth login` profile):
    python backend/llm.py --smoke
"""
from __future__ import annotations
import os, sys, json, hashlib, pathlib
import config

_CACHE = pathlib.Path(config.CACHE_DIR) / "llm"
_CACHE.mkdir(parents=True, exist_ok=True)


class LLMError(RuntimeError):
    """Raised for any failure the caller should treat as 'no model output'."""


def _key(route: str, prompt: str) -> pathlib.Path:
    h = hashlib.sha256(f"{route}|{config.MODELS[route]['model']}|{prompt}".encode()).hexdigest()[:24]
    return _CACHE / f"{route}_{h}.txt"


def complete(prompt: str, route: str = "extract", max_tokens: int = 2048) -> str:
    cached = _key(route, prompt)
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    cfg = config.MODELS[route]
    text = _call_anthropic(cfg["model"], prompt, max_tokens, cfg.get("effort"))  # swap provider here
    cached.write_text(text, encoding="utf-8")
    return text


def complete_json(prompt: str, route: str = "extract", **kw):
    raw = complete(prompt + "\n\nReturn ONLY valid JSON, no prose, no code fences.", route=route, **kw)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _key(route, prompt + "\n\nReturn ONLY valid JSON, no prose, no code fences.").unlink(missing_ok=True)
        raise LLMError(f"model returned invalid JSON on route {route!r}: {e}") from e


def _call_anthropic(model: str, prompt: str, max_tokens: int, effort: str | None) -> str:
    """One Messages API call. No sampling parameters: current models reject
    `temperature`/`top_p`/`top_k`; depth is controlled with `effort` instead.
    Thinking runs adaptively and counts against max_tokens, so keep a floor."""
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("anthropic SDK not installed — pip install -r requirements.txt") from e

    client = anthropic.Anthropic()   # resolves ANTHROPIC_API_KEY / auth profile
    kwargs = dict(model=model, max_tokens=max(max_tokens, 1024),
                  messages=[{"role": "user", "content": prompt}])
    if effort:
        kwargs["output_config"] = {"effort": effort}
    try:
        msg = client.messages.create(**kwargs)
    except anthropic.NotFoundError as e:
        raise LLMError(f"model {model!r} not found — check FINN_*_MODEL env vars") from e
    except anthropic.AuthenticationError as e:
        raise LLMError("no valid Anthropic credentials (set ANTHROPIC_API_KEY)") from e
    except anthropic.RateLimitError as e:
        raise LLMError("rate limited by the Anthropic API") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("could not reach the Anthropic API") from e

    if msg.stop_reason == "refusal":
        raise LLMError("model declined the request")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if msg.stop_reason == "max_tokens" and not text:
        raise LLMError("output truncated before any text — raise max_tokens")
    return text


def smoke() -> int:
    """Call every configured route once, bypassing the cache. Exit code 0 = all OK."""
    ok = True
    for route, cfg in config.MODELS.items():
        try:
            out = _call_anthropic(cfg["model"], "Reply with the single word: ok", 1024, cfg.get("effort"))
            print(f"  ✓ {route:9} {cfg['model']:22} -> {out.strip()[:40]!r}")
        except LLMError as e:
            ok = False
            print(f"  ✗ {route:9} {cfg['model']:22} -> {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    print(__doc__)
