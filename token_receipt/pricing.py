"""Pricing lookup and cost estimation for token receipt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

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
    return (
        snapshot.input_tokens
        + snapshot.cached_input_tokens
        + snapshot.cache_write_tokens
        + snapshot.output_tokens
        + snapshot.reasoning_output_tokens
    )


def estimate_cost(snapshot: UsageSnapshot, pricing_path: Path) -> PriceEstimate:
    # Kimi context.jsonl 只有上下文累计 token_count，不能直接套 API 分项单价
    if snapshot.skip_price_estimate:
        return PriceEstimate(status="UNMAPPED", amount=None)

    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    input_rate = float(entry.get("input_per_million", 0.0))
    cached_rate = float(entry.get("cached_input_per_million", input_rate))
    cache_write_rate = float(entry.get("cache_write_5m_per_million", input_rate))
    output_rate = float(entry.get("output_per_million", 0.0))

    amount = (
        snapshot.input_tokens * input_rate
        + snapshot.cached_input_tokens * cached_rate
        + snapshot.cache_write_tokens * cache_write_rate
        + (snapshot.output_tokens + snapshot.reasoning_output_tokens) * output_rate
    ) / 1_000_000

    return PriceEstimate(
        status="ESTIMATE",
        amount=amount,
        model=str(entry.get("model", snapshot.model)),
        currency=str(entry.get("currency", pricing.get("currency", "USD"))).upper(),
        source_url=str(entry.get("source_url", "")),
        source_checked_at=str(entry.get("source_checked_at", "")),
        rate_note=str(entry.get("rate_note", "")),
    )
