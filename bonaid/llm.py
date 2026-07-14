"""
bonaid/llm.py
Thin client around Ollama's REST API (free, fully local, no API key, no
per-token cost - runs DeepSeek-R1, Qwen, Llama, etc. on your own machine/GPU).
Phase 4 (multi-agent reasoning) builds directly on `generate()` /
`chat()` below. Kept dependency-light (just `requests`) rather than pulling
in the full ollama-python package, since all we need is one HTTP call.
"""
import requests
from bonaid.config import settings


def generate(prompt: str, model: str | None = None, system: str | None = None) -> str:
    """One-shot completion. Returns plain text."""
    payload = {
        "model": model or settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system

    resp = requests.post(f"{settings.ollama_host}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")


def is_available() -> bool:
    try:
        r = requests.get(f"{settings.ollama_host}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list:
    try:
        r = requests.get(f"{settings.ollama_host}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
