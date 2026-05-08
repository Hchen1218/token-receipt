"""Ensure every anthropic entry in pricing.json carries cache_write_1h_per_million.

Part 05 needs this field to compute 1h TTL cache-write cost without PARTIAL.
"""

from __future__ import annotations

import json
import unittest

from token_receipt.models import DEFAULT_PRICING


class PricingJsonTest(unittest.TestCase):
    def setUp(self):
        with DEFAULT_PRICING.open("r", encoding="utf-8") as handle:
            self.data = json.load(handle)
        self.anthropic = [
            entry for entry in self.data["models"]
            if entry.get("provider") == "anthropic"
        ]

    def test_has_anthropic_entries(self):
        self.assertGreaterEqual(len(self.anthropic), 10)

    def test_every_anthropic_entry_has_cache_write_1h_per_million(self):
        missing = [
            entry["model"]
            for entry in self.anthropic
            if "cache_write_1h_per_million" not in entry
        ]
        self.assertEqual(missing, [], f"missing cache_write_1h_per_million: {missing}")

    def test_cache_write_1h_is_twice_input_rate(self):
        for entry in self.anthropic:
            with self.subTest(model=entry["model"]):
                input_rate = entry["input_per_million"]
                write_1h = entry["cache_write_1h_per_million"]
                self.assertAlmostEqual(
                    write_1h, input_rate * 2.0, places=4,
                    msg=f"{entry['model']}: expected {input_rate*2.0}, got {write_1h}",
                )


if __name__ == "__main__":
    unittest.main()
