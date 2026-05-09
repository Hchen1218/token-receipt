"""compute_total covers all four buckets plus reasoning output."""

from __future__ import annotations

import unittest

from token_receipt.models import UsageSnapshot
from token_receipt.pricing import compute_total


class ComputeTotalTest(unittest.TestCase):
    def test_sums_all_buckets(self):
        snap = UsageSnapshot(
            input_tokens=100,
            cached_input_tokens=200,
            cache_write_tokens=300,
            output_tokens=400,
            reasoning_output_tokens=50,
        )
        self.assertEqual(compute_total(snap), 1050)

    def test_empty_snapshot_is_zero(self):
        self.assertEqual(compute_total(UsageSnapshot()), 0)

    def test_matches_reported_session(self):
        # From spec §"Sanity check against the reported session".
        snap = UsageSnapshot(
            input_tokens=16_897,
            cached_input_tokens=22_000_000,
            cache_write_tokens=8_180_000,
            output_tokens=434_360,
        )
        self.assertEqual(compute_total(snap), 30_631_257)


if __name__ == "__main__":
    unittest.main()
