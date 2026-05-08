"""Part 02 regression: extracting pricing.py must not change behavior.

This file will be rewritten in Part 05 when the math is intentionally changed.
For now, it pins the current (buggy) behavior so the move is a pure refactor.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from token_receipt import pricing
from token_receipt.models import DEFAULT_PRICING, PriceEstimate, UsageSnapshot


class PricingExtractionTest(unittest.TestCase):
    def test_estimate_cost_matches_legacy_claude_opus_session(self):
        # These are the ORIGINAL buggy numbers from the reported session.
        # They are wrong (see spec), but they are what the code outputs today.
        snap = UsageSnapshot(
            input_tokens=16897,
            cached_input_tokens=22_000_000,    # note: today's code will clamp this
            cache_write_tokens=8_180_000,
            output_tokens=434_360,
            provider="anthropic",
            model="claude-opus-4.7",
        )
        estimate = pricing.estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(estimate.status, "ESTIMATE")
        # Legacy math: cached clamped to input_tokens, cache_write clamped to 0.
        # input cost ~= 0, cached = 16897 * 0.5 / 1M, output = 434360 * 25 / 1M.
        expected = (
            0 * 5.0
            + 16897 * 0.5
            + 0 * 6.25
            + 434360 * 25.0
        ) / 1_000_000
        self.assertAlmostEqual(estimate.amount, expected, places=4)

    def test_load_pricing_returns_dict_with_models(self):
        data = pricing.load_pricing(DEFAULT_PRICING)
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)
        self.assertTrue(any(entry.get("provider") == "anthropic" for entry in data["models"]))

    def test_find_price_resolves_opus_by_provider_and_alias(self):
        data = pricing.load_pricing(DEFAULT_PRICING)
        entry = pricing.find_price(data, "anthropic", "claude-opus-4.7")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["model"], "claude-opus-4.7")

    def test_find_price_returns_none_for_unmapped(self):
        data = pricing.load_pricing(DEFAULT_PRICING)
        self.assertIsNone(pricing.find_price(data, "acme", "definitely-not-a-real-model"))

    def test_data_module_reexports_for_back_compat(self):
        from token_receipt import data
        self.assertIs(data.load_pricing, pricing.load_pricing)
        self.assertIs(data.find_price, pricing.find_price)
        self.assertIs(data.estimate_cost, pricing.estimate_cost)


if __name__ == "__main__":
    unittest.main()
