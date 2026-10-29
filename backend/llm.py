"""Optional LLM adapter (OpenAI-compatible, Anthropic, Gemini). Returns parsed JSON or None.

If no provider is configured the planner falls back to its transparent rule-based generator, so the
app works end-to-end with only a Qloo key.
"""
from __future__ import annotations

import json
import re

import requests

from . import config


def enabled() -> bool:
    return config.LLM_PROVIDER in {"openai", "anthropic", "gemini"} and bool(config.LLM_API_KEY or config.LLM_BASE_URL)


def describe() -> str:
    return f"{config.LLM_PROVIDER}:{config.LLM_MODEL or 'default'}" if enabled() else "rule-based (no LLM configured)"


def _extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        end = max(text.rfind("}"), text.rfind("]"))
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return None


def complete_json(system: str, user: str, max_tokens: int = 2500):
    if not enabled():
        return None
    p = config.LLM_PROVIDER
    try:
        if p == "openai":
            base = (config.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
            r = requests.post(f"{base}/chat/completions", timeout=90,
                              headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                              json={"model": config.LLM_MODEL or "gpt-4o-mini", "temperature": 0.5,
                                    "response_format": {"type": "json_object"},
                                    "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": user}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        elif p == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
                              headers={"x-api-key": config.LLM_API_KEY, "anthropic-version": "2023-06-01"},
                              json={"model": config.LLM_MODEL or "claude-sonnet-4-5", "max_tokens": max_tokens,
                                    "system": system, "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json()["content"])
        else:  # gemini
            model = config.LLM_MODEL or "gemini-2.0-flash"
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              params={"key": config.LLM_API_KEY}, timeout=90,
                              json={"systemInstruction": {"parts": [{"text": system}]},
                                    "contents": [{"parts": [{"text": user}]}],
                                    "generationConfig": {"responseMimeType": "application/json"}})
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
    return _extract_json(text)
