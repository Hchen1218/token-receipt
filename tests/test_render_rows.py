"""Render-layer gating: CONTEXT USED, --hide-fields, PARTIAL pricing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from token_receipt.models import DEFAULT_PRICING, PriceEstimate, UsageSnapshot
from token_receipt.pricing import estimate_cost
from token_receipt.render import (
    build_receipt_view,
    context_used,
    render_receipt,
)


def _make_snapshot(**overrides):
    base = dict(
        input_tokens=100,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=100,
        total_tokens=200,
        context_window=200_000,
        provider="anthropic",
        model="claude-opus-4.7",
        scope="latest-turn",
    )
    base.update(overrides)
    return UsageSnapshot(**base)


class ContextUsedTest(unittest.TestCase):
    def test_returns_value_on_latest_turn(self):
        snap = _make_snapshot(scope="latest-turn", input_tokens=100)
        self.assertIsNotNone(context_used(snap))
        self.assertIn("100", context_used(snap))

    def test_returns_none_off_latest_turn(self):
        for scope in ("session", "today", "session-all"):
            with self.subTest(scope=scope):
                snap = _make_snapshot(scope=scope)
                self.assertIsNone(context_used(snap))


class SummaryRowsHidingTest(unittest.TestCase):
    def _view(self, snapshot, hidden=frozenset()):
        estimate = PriceEstimate(status="ESTIMATE", amount=0.01, model="claude-opus-4.7",
                                 source_checked_at="2026-04-25")
        return build_receipt_view(
            snapshot, estimate, width=48, agent_tool="claude-code",
            footer="auto", footer_tone="auto", conversation_hint="",
            language="en", hidden=hidden,
        )

    def test_default_includes_supplier_model_context(self):
        labels = [row.label for row in self._view(_make_snapshot()).summary_rows]
        self.assertEqual(labels, ["PROVIDER", "MODEL", "CONTEXT USED"])

    def test_hide_supplier_and_model(self):
        view = self._view(_make_snapshot(), hidden=frozenset({"supplier", "model"}))
        labels = [row.label for row in view.summary_rows]
        self.assertEqual(labels, ["CONTEXT USED"])

    def test_hide_context_strips_row_even_when_latest_turn(self):
        view = self._view(_make_snapshot(), hidden=frozenset({"context"}))
        labels = [row.label for row in view.summary_rows]
        self.assertEqual(labels, ["PROVIDER", "MODEL"])

    def test_non_latest_turn_drops_context_automatically(self):
        view = self._view(_make_snapshot(scope="today"))
        labels = [row.label for row in view.summary_rows]
        self.assertEqual(labels, ["PROVIDER", "MODEL"])


class PartialPricingRenderTest(unittest.TestCase):
    def _estimate_partial(self):
        # Craft a PARTIAL by using a pricing entry missing output_per_million.
        fd = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"models": [{
            "provider": "acme", "model": "bare", "aliases": ["bare"],
            "input_per_million": 1.0,
        }]}, fd)
        fd.close()
        path = Path(fd.name)
        try:
            snap = UsageSnapshot(input_tokens=1000, output_tokens=1000,
                                 provider="acme", model="bare")
            return snap, estimate_cost(snap, path)
        finally:
            path.unlink()

    def test_partial_status_renders_price_partial_with_asterisk(self):
        snap, estimate = self._estimate_partial()
        self.assertEqual(estimate.status, "PARTIAL")
        text = render_receipt(
            snap, estimate, 48, "generic", "auto", "auto", "", "en",
        )
        self.assertIn("PRICE", text)
        self.assertIn("PARTIAL", text)
        self.assertNotIn("PRICE DATE", text)
        # The USD line carries a trailing * to signal PARTIAL.
        self.assertRegex(text, r"USD ESTIMATE\*")

    def test_unmapped_status_unchanged(self):
        snap = UsageSnapshot(provider="acme", model="nope", input_tokens=1, output_tokens=1)
        estimate = PriceEstimate(status="UNMAPPED", amount=None)
        text = render_receipt(
            snap, estimate, 48, "generic", "auto", "auto", "", "en",
        )
        self.assertIn("UNMAPPED", text)
        self.assertNotIn("PRICE DATE", text)

    def test_hide_price_date_on_estimate(self):
        snap = UsageSnapshot(provider="anthropic", model="claude-opus-4.7",
                             input_tokens=100, output_tokens=100, total_tokens=200)
        estimate = estimate_cost(snap, DEFAULT_PRICING)
        self.assertEqual(estimate.status, "ESTIMATE")
        text = render_receipt(
            snap, estimate, 48, "claude-code", "auto", "auto", "", "en",
            hidden=frozenset({"price-date"}),
        )
        self.assertNotIn("PRICE DATE", text)


if __name__ == "__main__":
    unittest.main()
