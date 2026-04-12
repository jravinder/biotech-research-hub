"""Biotech Research Hub — LLM Interface

Supports multiple providers via config:
  - ollama (local, default)
  - openai (GPT-4o, etc.)
  - anthropic (Claude)
  - nim (NVIDIA NIM)

No litellm dependency (supply chain risk). Direct API calls only.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import config

PROVIDER = config["llm"]["provider"]
BASE_URL = config["llm"]["base_url"]
MODEL = os.environ.get("AGENT_MODEL", config["llm"]["model"])
API_KEY = config["llm"]["api_key"] or os.environ.get("LLM_API_KEY", "")
TEMPERATURE = config["llm"]["temperature"]
NUM_CTX = config["llm"]["num_ctx"]


def ask(prompt, system="", model=None, temperature=None):
    """Send prompt to LLM, return response text."""
    model = model or MODEL
    temperature = temperature if temperature is not None else TEMPERATURE
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if PROVIDER == "ollama":
        return _ask_ollama(messages, model, temperature)
    elif PROVIDER == "openai":
        return _ask_openai(messages, model, temperature)
    elif PROVIDER == "anthropic":
        return _ask_anthropic(messages, model, temperature)
    elif PROVIDER == "nim":
        return _ask_nim(messages, model, temperature)
    else:
        raise ValueError(f"Unknown LLM provider: {PROVIDER}")


def ask_json(prompt, system="", model=None):
    """Send prompt and parse response as JSON."""
    full_system = (system or "") + "\nRespond with valid JSON only. No markdown fences, no explanation outside the JSON."
    text = ask(prompt, system=full_system, model=model, temperature=0.1)
    # Strip markdown code fences
    if "```" in text:
        lines = text.split("\n")
        cleaned = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(cleaned)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', text)
        text = re.sub(r'[\x00-\x1f]', ' ', text)
        return json.loads(text)


# Provider implementations

def _ask_ollama(messages, model, temperature):
    resp = requests.post(
        f"{BASE_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": NUM_CTX},
        },
        timeout=1800,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def _ask_openai(messages, model, temperature):
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _ask_anthropic(messages, model, temperature):
    # Convert system message to Anthropic format
    system_text = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            user_messages.append(m)

    body = {
        "model": model,
        "max_tokens": 8192,
        "messages": user_messages,
        "temperature": temperature,
    }
    if system_text:
        body["system"] = system_text

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _ask_nim(messages, model, temperature):
    nim_url = config["api"]["nim_url"]
    nim_key = os.environ.get("NIM_API_KEY", API_KEY)
    resp = requests.post(
        nim_url,
        headers={"Authorization": f"Bearer {nim_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
