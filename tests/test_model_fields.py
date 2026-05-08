"""Snapshot and estimate carry the new accounting fields with safe defaults."""

from __future__ import annotations

import unittest

from token_receipt.models import PriceEstimate, UsageSnapshot


class UsageSnapshotFieldsTest(unittest.TestCase):
    def test_cache_write_ttl_fields_default_to_zero(self):
        snap = UsageSnapshot()
        self.assertEqual(snap.cache_write_5m_tokens, 0)
        self.assertEqual(snap.cache_write_1h_tokens, 0)

    def test_aggregation_diagnostics_default_safely(self):
        snap = UsageSnapshot()
        self.assertIsNone(snap.aggregation_source)
        self.assertEqual(snap.deduped_message_ids, 0)

    def test_existing_fields_still_default(self):
        snap = UsageSnapshot()
        self.assertEqual(snap.input_tokens, 0)
        self.assertEqual(snap.cache_write_tokens, 0)
        self.assertEqual(snap.scope, "latest-turn")
        self.assertFalse(snap.skip_price_estimate)

    def test_snapshot_accepts_all_new_fields_in_kwargs(self):
        snap = UsageSnapshot(
            cache_write_5m_tokens=100,
            cache_write_1h_tokens=50,
            aggregation_source="projects-jsonl",
            deduped_message_ids=7,
        )
        self.assertEqual(snap.cache_write_5m_tokens, 100)
        self.assertEqual(snap.cache_write_1h_tokens, 50)
        self.assertEqual(snap.aggregation_source, "projects-jsonl")
        self.assertEqual(snap.deduped_message_ids, 7)


class PriceEstimateFieldsTest(unittest.TestCase):
    def test_partial_reasons_defaults_to_empty_tuple(self):
        est = PriceEstimate(status="ESTIMATE", amount=1.23)
        self.assertEqual(est.partial_reasons, ())

    def test_partial_reasons_accepts_tuple(self):
        est = PriceEstimate(
            status="PARTIAL",
            amount=1.23,
            partial_reasons=("cache_write_1h_per_million",),
        )
        self.assertEqual(est.partial_reasons, ("cache_write_1h_per_million",))


if __name__ == "__main__":
    unittest.main()
