"""Pricing and model-support unit tests."""

from __future__ import annotations

import unittest

from token_receipt.models import DEFAULT_PRICING, UsageSnapshot
from token_receipt.pricing import compute_total, estimate_cost, find_price, load_pricing


class ComputeTotalTest(unittest.TestCase):
    def test_sums_every_billable_bucket(self) -> None:
        snapshot = UsageSnapshot(
            input_tokens=100,
            cached_input_tokens=2000,
            cache_write_tokens=500,
            output_tokens=40,
            reasoning_output_tokens=12,
        )
        self.assertEqual(compute_total(snapshot), 2652)


class EstimateCostTest(unittest.TestCase):
    def test_bills_each_bucket_without_clamping(self) -> None:
        snapshot = UsageSnapshot(
            input_tokens=16897,
            cached_input_tokens=22_000_000,
            cache_write_tokens=8_180_000,
            output_tokens=434_360,
            provider="anthropic",
            model="claude-opus-4.7",
        )
        estimate = estimate_cost(snapshot, DEFAULT_PRICING)
        expected = (
            16897 * 5.0
            + 22_000_000 * 0.5
            + 8_180_000 * 6.25
            + 434_360 * 25.0
        ) / 1_000_000
        self.assertEqual(estimate.status, "ESTIMATE")
        self.assertAlmostEqual(estimate.amount, expected, places=6)


class LatestModelSupportTest(unittest.TestCase):
    def test_newer_models_and_aliases_resolve(self) -> None:
        pricing = load_pricing(DEFAULT_PRICING)
        cases = [
            ("openai", "ChatGPT 5.5", "gpt-5.5"),
            ("openai", "chat-latest", "chat-latest"),
            ("anthropic", "opus 4.8", "claude-opus-4.8"),
            ("minimax", "MiniMax 3", "minimax-m3"),
            ("xiaomi", "MiMo V2.5 Pro", "xiaomi/mimo-v2.5-pro"),
        ]
        for provider, alias, expected_model in cases:
            with self.subTest(provider=provider, alias=alias):
                entry = find_price(pricing, provider, alias)
                self.assertIsNotNone(entry)
                self.assertEqual(entry["model"], expected_model)


if __name__ == "__main__":
    unittest.main()
