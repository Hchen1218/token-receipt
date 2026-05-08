"""AWS Bedrock provider + model normalization.

Claude Code on Bedrock surfaces models as `<region>.anthropic.claude-opus-4-7[1m]`.
This module rewrites the pair to (`aws bedrock`, `claude-opus-4.7`) so the receipt
labels it correctly and find_price() resolves it against the existing anthropic
entries without any extra pricing rows.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional, Tuple

BEDROCK_MODEL_PREFIXES: Tuple[str, ...] = (
    "global.anthropic.",
    "us.anthropic.",
    "eu.anthropic.",
    "apac.anthropic.",
)

_VERSION_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")
_MAJOR_MINOR_DASH_RE = re.compile(r"^(claude-[a-z]+-\d+)-(\d+)$")


def is_bedrock_env(env: Optional[Mapping[str, str]] = None) -> bool:
    env = env if env is not None else os.environ
    return env.get("CLAUDE_CODE_USE_BEDROCK", "").strip() in ("1", "true", "TRUE")


def looks_like_bedrock_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in BEDROCK_MODEL_PREFIXES)


def normalize_bedrock_model(model: str) -> str:
    for prefix in BEDROCK_MODEL_PREFIXES:
        if model.startswith(prefix):
            model = model[len(prefix):]
            break
    model = _VERSION_SUFFIX_RE.sub("", model)
    match = _MAJOR_MINOR_DASH_RE.match(model)
    if match:
        model = f"{match.group(1)}.{match.group(2)}"
    return model


def resolve_provider_and_model(
    raw_provider: str,
    raw_model: str,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str]:
    """Return (provider, model) — rewritten to ('aws bedrock', normalized) when Bedrock is detected."""
    if is_bedrock_env(env) or looks_like_bedrock_model(raw_model):
        return ("aws bedrock", normalize_bedrock_model(raw_model))
    return (raw_provider, raw_model)
