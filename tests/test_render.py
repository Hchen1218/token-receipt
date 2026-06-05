"""Render behavior tests for context display."""

from __future__ import annotations

import unittest

from token_receipt.models import PriceEstimate, UsageSnapshot
from token_receipt.render import build_receipt_view, context_used


def make_snapshot(scope: str) -> UsageSnapshot:
    return UsageSnapshot(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        context_window=258400,
        provider="openai",
        model="gpt-5.5",
        scope=scope,
        available_fields=("input_tokens", "output_tokens", "total_tokens"),
    )


class ContextUsedTest(unittest.TestCase):
    def test_latest_turn_keeps_context_line(self) -> None:
        self.assertEqual(context_used(make_snapshot("latest-turn")), "100/258,400")

    def test_session_scope_omits_context_line(self) -> None:
        self.assertIsNone(context_used(make_snapshot("session")))

    def test_summary_rows_drop_context_for_session_scope(self) -> None:
        view = build_receipt_view(
            make_snapshot("session"),
            PriceEstimate(status="UNMAPPED", amount=None),
            48,
            "codex",
            "auto",
            "auto",
            "",
            "en",
        )
        labels = [row.label for row in view.summary_rows]
        self.assertNotIn("CONTEXT USED", labels)


if __name__ == "__main__":
    unittest.main()
