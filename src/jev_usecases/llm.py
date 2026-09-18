"""Generative LLM client. Prefers Claude; falls back to OpenAI."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from jev_usecases.client import _REPO_ROOT  # noqa: PLC2701 — shared dotenv root
from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
OPENAI_MODEL_FALLBACKS = ("gpt-4.1-mini", "gpt-4o-mini", "gpt-4o")


class MissingLLMKeyError(RuntimeError):
    """Raised when neither a Claude nor an OpenAI key is configured."""


class LLMError(RuntimeError):
    """Raised when the selected provider returns an unusable response."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    model: str
    key_env: str
    base_url: str | None = None


@dataclass(frozen=True)
class LLMCompletion:
    provider: str
    model: str
    text: str
    usage: dict
    key_env: str


def resolve_llm() -> LLMConfig:
    """Pick Claude when a Claude/Anthropic key exists, otherwise OpenAI.

    Checked names, in order:
    ``ANTHROPIC_API_KEY``, ``CLAUDE_API_KEY``, then ``OPENAI_API_KEY``.
    """
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        key = os.getenv(name, "").strip()
        if key:
            return LLMConfig(
                provider="anthropic",
                api_key=key,
                model=os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL).strip() or DEFAULT_ANTHROPIC_MODEL,
                key_env=name,
            )
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        return LLMConfig(
            provider="openai",
            api_key=key,
            model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL,
            key_env="OPENAI_API_KEY",
            base_url=base or "https://api.openai.com/v1",
        )
    raise MissingLLMKeyError(
        "No generative model key found. Set ANTHROPIC_API_KEY or CLAUDE_API_KEY, "
        "or OPENAI_API_KEY as a fallback."
    )


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 800,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> LLMCompletion:
    """Call the resolved provider and return the assistant text."""
    cfg = resolve_llm()
    if cfg.provider == "anthropic":
        return _complete_anthropic(cfg, system, user, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
    return _complete_openai(cfg, system, user, max_tokens=max_tokens, temperature=temperature, timeout=timeout)


def _complete_anthropic(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> LLMCompletion:
    response = httpx.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": cfg.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": cfg.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise LLMError(f"Anthropic {response.status_code}: {_safe_body(response)}")
    body = response.json()
    parts = []
    for block in body.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise LLMError("Anthropic returned an empty completion")
    usage = body.get("usage") or {}
    return LLMCompletion(
        provider="anthropic",
        model=body.get("model") or cfg.model,
        text=text,
        usage={
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        },
        key_env=cfg.key_env,
    )


def _complete_openai(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> LLMCompletion:
    models = [cfg.model]
    for fallback in OPENAI_MODEL_FALLBACKS:
        if fallback not in models:
            models.append(fallback)

    last_error = "OpenAI request failed"
    url = f"{cfg.base_url}/chat/completions"
    for model in models:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=timeout,
        )
        if response.status_code in {400, 404} and "model" in response.text.lower():
            last_error = f"OpenAI {response.status_code} for model {model}: {_safe_body(response)}"
            continue
        if response.status_code >= 400:
            raise LLMError(f"OpenAI {response.status_code}: {_safe_body(response)}")
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("OpenAI returned no choices")
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMError("OpenAI returned an empty completion")
        usage = body.get("usage") or {}
        return LLMCompletion(
            provider="openai",
            model=body.get("model") or model,
            text=text,
            usage={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
            key_env=cfg.key_env,
        )
    raise LLMError(last_error)


def _safe_body(response: httpx.Response) -> str:
    text = response.text[:500]
    # Never echo bearer tokens if a proxy reflected the request.
    for secret_name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY"):
        secret = os.getenv(secret_name, "")
        if secret:
            text = text.replace(secret, "[redacted]")
    return text
