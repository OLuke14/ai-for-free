"""
Unified LLM client.

Tries Ollama Cloud first. If that fails (rate limit, timeout, error status),
automatically falls back to Groq. Both APIs are OpenAI-compatible-ish, so we
normalize the response shape here.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import requests

import config


class ProviderError(Exception):
    """Raised when a single provider fails (used internally for fallback logic)."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


def _call_ollama_cloud(messages: list[dict]) -> LLMResponse:
    if not config.OLLAMA_API_KEY:
        raise ProviderError("No OLLAMA_API_KEY configured")

    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/chat"
    headers = {
        "Authorization": f"Bearer {config.OLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise ProviderError(f"Ollama Cloud request failed: {e}") from e

    if resp.status_code == 429:
        raise ProviderError("Ollama Cloud rate limit hit")
    if not resp.ok:
        raise ProviderError(f"Ollama Cloud error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        text = data["message"]["content"]
    except (KeyError, TypeError) as e:
        raise ProviderError(f"Unexpected Ollama Cloud response shape: {data}") from e

    return LLMResponse(text=text, provider="ollama_cloud", model=config.OLLAMA_MODEL)


def _call_groq(messages: list[dict]) -> LLMResponse:
    if not config.GROQ_API_KEY:
        raise ProviderError("No GROQ_API_KEY configured")

    url = f"{config.GROQ_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "messages": messages,
    }

    candidate_models = [config.GROQ_MODEL, *config.GROQ_MODEL_FALLBACKS]
    tried_models: list[str] = []
    last_error: ProviderError | None = None

    for model in candidate_models:
        if not model or model in tried_models:
            continue

        tried_models.append(model)
        payload["model"] = model

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            last_error = ProviderError(f"Groq request failed: {e}")
            continue

        if resp.status_code == 429:
            last_error = ProviderError("Groq rate limit hit")
            continue

        if not resp.ok:
            body = resp.text[:200]
            if resp.status_code == 404 and "model_not_found" in resp.text:
                last_error = ProviderError(f"Groq model '{model}' not found")
                continue
            last_error = ProviderError(f"Groq error {resp.status_code}: {body}")
            continue

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"Unexpected Groq response shape: {data}") from e

        return LLMResponse(text=text, provider="groq", model=model)

    if last_error is None:
        last_error = ProviderError("Groq request failed for unknown reasons")

    raise last_error


def chat(messages: list[dict], verbose: bool = True) -> LLMResponse:
    """
    Send a chat completion request. Tries Ollama Cloud first, falls back to Groq.
    Raises ProviderError if both fail.
    """
    try:
        return _call_ollama_cloud(messages)
    except ProviderError as e:
        if verbose:
            print(f"[warn] Ollama Cloud unavailable ({e}), falling back to Groq...", file=sys.stderr)

    try:
        return _call_groq(messages)
    except ProviderError as e:
        raise ProviderError(f"Both providers failed. Last error (Groq): {e}") from e
