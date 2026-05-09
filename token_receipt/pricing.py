"""Pricing lookup and cost estimation.

Responsibility: given a UsageSnapshot and a pricing.json path, return the
total cost as a PriceEstimate. Owns cache-write TTL resolution and total-tokens
math. No I/O besides reading pricing.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .models import PriceEstimate, UsageSnapshot, normalize


def load_pricing(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_price(pricing: Dict[str, Any], provider: str, model: str) -> Optional[Dict[str, Any]]:
    if not model or model == "UNRECORDED":
        return None
    provider_key = normalize(provider)
    model_key = normalize(model)
    for entry in pricing.get("models", []):
        entry_provider = normalize(str(entry.get("provider", "")))
        aliases = [entry.get("model", "")] + list(entry.get("aliases", []))
        alias_keys = {normalize(str(alias)) for alias in aliases}
        provider_matches = not provider_key or provider_key == "unknown" or provider_key == entry_provider
        if provider_matches and model_key in alias_keys:
            return entry
    for entry in pricing.get("models", []):
        aliases = [entry.get("model", "")] + list(entry.get("aliases", []))
        if model_key in {normalize(str(alias)) for alias in aliases}:
            return entry
    return None


def compute_total(snapshot: UsageSnapshot) -> int:
    """Sum of every billable bucket — used when the source did not supply its own total."""
    return (
        snapshot.input_tokens
        + snapshot.output_tokens
        + snapshot.cached_input_tokens
        + snapshot.cache_write_tokens
        + snapshot.reasoning_output_tokens
    )


def resolve_cache_write_split(
    snapshot: UsageSnapshot,
    cli_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[int, int]:
    """Return (cache_write_5m_tokens, cache_write_1h_tokens).

    Resolution order:
    1. Explicit CLI override (--cache-ttl 5m | 1h).
    2. Per-message split carried by the snapshot (5m/1h fields both nonzero or either nonzero).
    3. Claude Code on Bedrock 1h env flag.
    4. Default to 5m.
    """
    env = env if env is not None else os.environ

    if cli_override == "5m":
        return (snapshot.cache_write_tokens, 0)
    if cli_override == "1h":
        return (0, snapshot.cache_write_tokens)

    if snapshot.cache_write_5m_tokens or snapshot.cache_write_1h_tokens:
        return (snapshot.cache_write_5m_tokens, snapshot.cache_write_1h_tokens)

    flag = env.get("ENABLE_PROMPT_CACHING_1H_BEDROCK", "").strip()
    if flag in ("1", "true", "TRUE"):
        return (0, snapshot.cache_write_tokens)

    return (snapshot.cache_write_tokens, 0)


def estimate_cost(
    snapshot: UsageSnapshot,
    pricing_path: Path,
    cache_ttl_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> PriceEstimate:
    """Bill every bucket at its own rate. Returns PARTIAL when required rates are missing."""
    if snapshot.skip_price_estimate:
        return PriceEstimate(status="UNMAPPED", amount=None)

    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    missing: list[str] = []

    input_rate = entry.get("input_per_million")
    output_rate = entry.get("output_per_million")
    cached_rate = entry.get("cached_input_per_million", input_rate)
    write_5m = entry.get("cache_write_5m_per_million", input_rate)
    write_1h = entry.get("cache_write_1h_per_million")

    split_5m, split_1h = resolve_cache_write_split(snapshot, cache_ttl_override, env)

    if split_1h > 0 and write_1h is None:
        missing.append("cache_write_1h_per_million")
        # Documented Anthropic 1h fallback: 2 * input rate.
        write_1h = (input_rate or 0) * 2.0

    if input_rate is None:
        missing.append("input_per_million")
    if output_rate is None:
        missing.append("output_per_million")

    amount = (
        snapshot.input_tokens * (input_rate or 0)
        + snapshot.cached_input_tokens * (cached_rate or 0)
        + split_5m * (write_5m or 0)
        + split_1h * (write_1h or 0)
        + (snapshot.output_tokens + snapshot.reasoning_output_tokens) * (output_rate or 0)
    ) / 1_000_000

    status = "PARTIAL" if missing else "ESTIMATE"
    return PriceEstimate(
        status=status,
        amount=amount,
        model=str(entry.get("model", snapshot.model)),
        currency=str(entry.get("currency", pricing.get("currency", "USD"))).upper(),
        source_url=str(entry.get("source_url", "")),
        source_checked_at=str(entry.get("source_checked_at", "")),
        rate_note=str(entry.get("rate_note", "")),
        partial_reasons=tuple(missing),
    )
