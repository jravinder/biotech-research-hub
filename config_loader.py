"""Biotech Research Hub — Config Loader

Singleton that loads config.yaml, validates required fields, applies defaults.
Import from any module: from config_loader import config
"""

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CONFIG_PATH = os.environ.get("BRH_CONFIG", ROOT / "config.yaml")

_config = None

REQUIRED_FIELDS = [
    ("disease", "name"),
    ("disease", "short_name"),
    ("disease", "mondo_id"),
    ("search", "pubmed_query"),
]

VALID_LLM_PROVIDERS = {"ollama", "openai", "anthropic", "nim"}

DEFAULTS = {
    "disease": {
        "mondo_id": "",
        "condition_search_term": "",
        "description": "",
        "gene": "",
        "protein": "",
    },
    "branding": {
        "app_name": "Research Hub",
        "tagline": "AI-Powered Research",
        "colors": {
            "primary": "#F59E0B",
            "primary_dark": "#D97706",
            "secondary": "#92400E",
            "accent": "#FB7185",
            "surface": "#FFFBEB",
            "background": "#fdf9e9",
            "text": "#1c1c13",
        },
        "support_orgs": [],
    },
    "search": {
        "pubmed_query": "",
        "include_terms": {},
        "priority_terms": {},
        "exclude_terms": {},
        "relevance_threshold": 6,
        "days": 30,
        "max_results": 20,
        "paper_scout_queries": [],
        "topic_tags": {},
    },
    "targets": [],
    "repurposing": {
        "known_candidates": [],
        "seed_hypotheses": [],
    },
    "community_news": {
        "rss_feeds": [],
    },
    "analytics": {
        "ga4_id": "",
    },
    "llm": {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "gemma4:latest",
        "api_key": "",
        "embed_model": "nomic-embed-text",
        "temperature": 0.2,
        "num_ctx": 65536,
    },
    "api": {
        "nim_enabled": False,
        "nim_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "nim_model": "nvidia/llama-3.1-nemotron-nano-8b-v1",
        "sarvam_enabled": False,
        "sarvam_url": "https://api.sarvam.ai/translate",
    },
    "i18n": {
        "supported_languages": "en,es,fr,de,ja,zh-CN,pt,ar,ko,it,ru",
    },
    "ci": {
        "bot_name": "Research Bot",
        "bot_email": "bot@researchhub.dev",
    },
    "deployment": {
        "repo_url": "",
        "site_url": "",
    },
}


def _deep_merge(base, override):
    """Merge override into base, returning new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate(cfg):
    """Check required fields exist and are non-empty."""
    missing = []
    for *path, field in REQUIRED_FIELDS:
        node = cfg
        for p in path:
            node = node.get(p, {})
        if not node.get(field):
            missing.append(".".join(path + [field]))
    if missing:
        print(f"\nConfig error: missing required fields in {CONFIG_PATH}:")
        for m in missing:
            print(f"  - {m}")
        print(f"\nSee examples/configs/ for reference configs.\n")
        sys.exit(1)

    if not cfg.get("targets"):
        print(f"\nConfig error: targets must include at least one entry in {CONFIG_PATH}.")
        print("Add at least one target under targets[].")
        print()
        sys.exit(1)

    provider = str(cfg["llm"].get("provider", "")).strip().lower()
    if provider not in VALID_LLM_PROVIDERS:
        print(f"\nConfig error: unsupported llm.provider '{provider}' in {CONFIG_PATH}.")
        print(f"Supported providers: {', '.join(sorted(VALID_LLM_PROVIDERS))}")
        print()
        sys.exit(1)

    model = str(cfg["llm"].get("model", "")).strip()
    if not model:
        print(f"\nConfig error: llm.model is required in {CONFIG_PATH}.")
        print()
        sys.exit(1)

    if provider == "ollama":
        if not str(cfg["llm"].get("base_url", "")).strip():
            print(f"\nConfig error: llm.base_url is required for ollama in {CONFIG_PATH}.")
            print()
            sys.exit(1)
        return

    api_key = (
        str(cfg["llm"].get("api_key", "")).strip()
        or str(os.environ.get("LLM_API_KEY", "")).strip()
    )

    if provider == "openai":
        if not api_key:
            print(f"\nConfig error: OpenAI provider requires llm.api_key or LLM_API_KEY.")
            print()
            sys.exit(1)
        return

    if provider == "anthropic":
        if not api_key:
            print(f"\nConfig error: Anthropic provider requires llm.api_key or LLM_API_KEY.")
            print()
            sys.exit(1)
        return

    if provider == "nim":
        nim_url = str(cfg["api"].get("nim_url", "")).strip()
        nim_key = str(os.environ.get("NIM_API_KEY", "")).strip() or api_key
        if not nim_url:
            print(f"\nConfig error: api.nim_url is required for nim provider.")
            print()
            sys.exit(1)
        if not nim_key:
            print(f"\nConfig error: NIM provider requires NIM_API_KEY or llm.api_key/LLM_API_KEY.")
            print()
            sys.exit(1)
        return


def load_config(path=None):
    """Load and return config, applying defaults."""
    global _config
    if _config is not None and path is None:
        return _config

    p = Path(path) if path else Path(CONFIG_PATH)
    if not p.exists():
        print(f"\nConfig file not found: {p}")
        print("Copy an example config to get started:")
        print("  cp examples/configs/huntington.yaml config.yaml")
        print()
        sys.exit(1)

    with open(p) as f:
        user_config = yaml.safe_load(f) or {}

    cfg = _deep_merge(DEFAULTS, user_config)

    # Auto-derive app_name if not explicitly set
    if cfg["branding"]["app_name"] == "Research Hub" and cfg["disease"]["short_name"]:
        cfg["branding"]["app_name"] = f"{cfg['disease']['short_name']} Research Hub"

    # Auto-derive condition_search_term from disease name
    if not cfg["disease"]["condition_search_term"] and cfg["disease"]["name"]:
        cfg["disease"]["condition_search_term"] = cfg["disease"]["name"]

    # LLM API key from env var fallback
    if not cfg["llm"]["api_key"]:
        cfg["llm"]["api_key"] = os.environ.get("LLM_API_KEY", "")

    _validate(cfg)

    if path is None:
        _config = cfg
    return cfg


# Module-level access: from config_loader import config
config = load_config()
