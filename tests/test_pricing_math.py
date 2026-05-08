"""estimate_cost bills all four buckets; PARTIAL status when rates are missing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from token_receipt.models import DEFAULT_PRICING, UsageSnapshot
from token_receipt.pricing import estimate_cost


def _write_pricing(entries):
    fd = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"currency": "USD", "models": entries}, fd)
    fd.close()
    return Path(fd.name)


class EstimateCostTest(unittest.TestCase):
    def test_reported_session_5m_ttl(self):
        """Spec §\"Sanity check\" — expect $73.07 for 5m TTL."""
        snap = UsageSnapshot(
            input_tokens=16_897,
            cached_input_tokens=22_000_000,
            cache_write_tokens=8_180_000,          # all 5m (default)
            output_tokens=434_360,
            provider="anthropic",
            model="claude-opus-4.7",
        )
        est = estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(est.status, "ESTIMATE")
        # input 16897 * 5/1M + cache-read 22M * 0.5/1M + write-5m 8.18M * 6.25/1M
        # + output 434360 * 25/1M
        expected = (16_897 * 5.0 + 22_000_000 * 0.5
                    + 8_180_000 * 6.25 + 434_360 * 25.0) / 1_000_000
        self.assertAlmostEqual(est.amount, expected, places=2)
        self.assertAlmostEqual(est.amount, 73.07, places=1)

    def test_reported_session_1h_ttl_via_cli_override(self):
        snap = UsageSnapshot(
            input_tokens=16_897,
            cached_input_tokens=22_000_000,
            cache_write_tokens=8_180_000,
            output_tokens=434_360,
            provider="anthropic",
            model="claude-opus-4.7",
        )
        est = estimate_cost(snap, DEFAULT_PRICING, cache_ttl_override="1h")
        self.assertEqual(est.status, "ESTIMATE")
        self.assertAlmostEqual(est.amount, 103.74, places=1)

    def test_unmapped_model(self):
        snap = UsageSnapshot(
            input_tokens=1000, output_tokens=1000,
            provider="acme", model="does-not-exist",
        )
        est = estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(est.status, "UNMAPPED")
        self.assertIsNone(est.amount)

    def test_skip_price_estimate_returns_unmapped(self):
        snap = UsageSnapshot(skip_price_estimate=True, provider="anthropic", model="claude-opus-4.7")
        est = estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(est.status, "UNMAPPED")

    def test_partial_when_output_rate_missing(self):
        path = _write_pricing([{
            "provider": "acme",
            "model": "bare",
            "aliases": ["bare"],
            "input_per_million": 1.0,
            # output_per_million intentionally missing
        }])
        try:
            snap = UsageSnapshot(
                input_tokens=1000, output_tokens=1000,
                provider="acme", model="bare",
            )
            est = estimate_cost(snap, path)
            self.assertEqual(est.status, "PARTIAL")
            self.assertIn("output_per_million", est.partial_reasons)
        finally:
            path.unlink()

    def test_partial_when_1h_rate_missing_falls_back_to_twice_input(self):
        path = _write_pricing([{
            "provider": "acme",
            "model": "no-1h",
            "aliases": ["no-1h"],
            "input_per_million": 5.0,
            "cached_input_per_million": 0.5,
            "cache_write_5m_per_million": 6.25,
            "output_per_million": 25.0,
            # cache_write_1h_per_million intentionally missing
        }])
        try:
            snap = UsageSnapshot(
                cache_write_tokens=1_000_000,
                provider="acme", model="no-1h",
            )
            est = estimate_cost(snap, path, cache_ttl_override="1h")
            self.assertEqual(est.status, "PARTIAL")
            self.assertIn("cache_write_1h_per_million", est.partial_reasons)
            # Documented 1h fallback = 2 * input_rate = 10.0/M.
            self.assertAlmostEqual(est.amount, 10.0, places=4)
        finally:
            path.unlink()

    def test_no_clamp_cached_read_is_independent_of_input(self):
        """Regression for spec §\"the key change vs current\"."""
        snap = UsageSnapshot(
            input_tokens=100,                 # small
            cached_input_tokens=1_000_000,    # huge
            cache_write_tokens=0,
            output_tokens=0,
            provider="anthropic",
            model="claude-opus-4.7",
        )
        est = estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(est.status, "ESTIMATE")
        # input: 100 * 5/1M ; cached: 1,000,000 * 0.5/1M = 0.5
        expected = (100 * 5.0 + 1_000_000 * 0.5) / 1_000_000
        self.assertAlmostEqual(est.amount, expected, places=6)


if __name__ == "__main__":
    unittest.main()
