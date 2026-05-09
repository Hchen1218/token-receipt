# Part 09 — Render: gate CONTEXT USED, dynamic summary rows, PARTIAL rendering

**Parent plan:** [README.md](./README.md)

**Goal:** Make the render layer honest about what it shows. Drop `CONTEXT USED` for non-`latest-turn` scopes where it's meaningless; honor `--hide-fields`; render `PARTIAL` pricing with a visible `*` marker and drop `PRICE DATE` so the receipt doesn't advertise "vetted". Defects fixed: #5, #6 (render half), #9 (render half).

## Files

- Modify: `token_receipt/render.py` — `context_used`, `build_receipt_view`, add PARTIAL branch.
- Create: `tests/test_render_rows.py`

## Task 1: Red test

- [ ] **Step 1: Write `tests/test_render_rows.py`**

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_render_rows -v`
Expected: several failures — `context_used` still returns a string for non-latest-turn, `hidden` is silently ignored, `PARTIAL` renders the same as `ESTIMATE`.

## Task 2: Update the render layer

- [ ] **Step 3: Replace `context_used` in `token_receipt/render.py` (line 325)**

Replace:

```python
def context_used(snapshot: UsageSnapshot) -> str:
    if snapshot.context_tokens is not None:
        used_src = snapshot.context_tokens
    else:
        used_src = snapshot.input_tokens
    used = fmt_int(used_src)
    if snapshot.context_window:
        return f"{used}/{fmt_int(snapshot.context_window)}"
    return used
```

with:

```python
def context_used(snapshot: UsageSnapshot) -> Optional[str]:
    """Return the CONTEXT USED row value, or None when the row should be omitted.

    CONTEXT USED only makes sense for the latest turn. Session, today, and
    session-all aggregate multiple turns; showing one total-vs-window there
    misleads the reader.
    """
    if snapshot.scope != "latest-turn":
        return None
    if snapshot.context_tokens is not None:
        used_src = snapshot.context_tokens
    else:
        used_src = snapshot.input_tokens
    used = fmt_int(used_src)
    if snapshot.context_window:
        return f"{used}/{fmt_int(snapshot.context_window)}"
    return used
```

At the top of the file, add `Optional` to the `typing` import:

```python
from typing import List, Optional, Tuple
```

(The file currently imports `List, Tuple` — change to `List, Optional, Tuple`.)

- [ ] **Step 4: Replace the `summary_rows` construction and pricing rows inside `build_receipt_view`**

In `token_receipt/render.py`, inside `build_receipt_view` (line ~1419), replace the body from the `summary_rows = (` tuple down to the end of the `pricing_rows` construction (lines ~1435–1461) with:

```python
    # --- Summary rows, honoring --hide-fields and auto-dropping CONTEXT USED off latest-turn ---
    summary: list[ReceiptRow] = []
    if "supplier" not in hidden:
        summary.append(ReceiptRow(labels["provider"], provider))
    if "model" not in hidden:
        summary.append(ReceiptRow(labels["model"], snapshot.model))
    ctx_value = context_used(snapshot)
    if ctx_value is not None and "context" not in hidden:
        summary.append(ReceiptRow(labels["context"], ctx_value))
    summary_rows = tuple(summary)

    # --- Token rows (unchanged) ---
    token_rows: list[ReceiptRow] = []
    if source_has(snapshot, "input_tokens"):
        token_rows.append(ReceiptRow(labels["input"], fmt_int(snapshot.input_tokens)))
    if source_has(snapshot, "output_tokens"):
        token_rows.append(ReceiptRow(labels["output"], fmt_int(snapshot.output_tokens)))
    if source_has(snapshot, "cached_input_tokens"):
        token_rows.append(ReceiptRow(labels["cached"], fmt_int(snapshot.cached_input_tokens)))
    if source_has(snapshot, "reasoning_output_tokens"):
        token_rows.append(ReceiptRow(labels["reasoning"], fmt_int(snapshot.reasoning_output_tokens)))
    if source_has(snapshot, "cache_write_tokens"):
        token_rows.append(ReceiptRow(labels["cache_write"], fmt_int(snapshot.cache_write_tokens)))

    # --- Pricing rows, with PARTIAL rendered as estimate* + PRICE: PARTIAL and no PRICE DATE ---
    if estimate.status == "UNMAPPED":
        pricing_rows_list = [
            ReceiptRow(labels["estimate"].format(currency=estimate.currency),
                       money(estimate.amount, estimate.currency)),
            ReceiptRow(labels["price"], labels["unmapped"]),
        ]
    elif estimate.status == "PARTIAL":
        pricing_rows_list = [
            ReceiptRow(labels["estimate"].format(currency=estimate.currency) + "*",
                       money(estimate.amount, estimate.currency)),
            ReceiptRow(labels["price"], "PARTIAL"),
        ]
        # Intentionally no PRICE DATE — PARTIAL means the rate table was incomplete.
    else:  # ESTIMATE
        pricing_rows_list = [
            ReceiptRow(labels["estimate"].format(currency=estimate.currency),
                       money(estimate.amount, estimate.currency)),
            ReceiptRow(labels["price"] if "price-mapping" not in hidden else "",
                       estimate.model),
        ]
        if estimate.source_checked_at and "price-date" not in hidden:
            pricing_rows_list.append(ReceiptRow(labels["price_date"], estimate.source_checked_at))
        if estimate.rate_note and "rate-note" not in hidden:
            pricing_rows_list.append(ReceiptRow(labels["rate_note"], estimate.rate_note))
        if "price-mapping" in hidden:
            # Drop the (now empty-label) PRICE row entirely.
            pricing_rows_list = [row for row in pricing_rows_list if row.label]
    pricing_rows = pricing_rows_list
```

Leave the rest of `build_receipt_view` (the `logo_lines, logo_label, _ = logo_block(...)` block and the `return ReceiptView(...)`) untouched. The return statement already references `summary_rows`, `token_rows`, and `pricing_rows` — those names still exist.

- [ ] **Step 5: Run the render tests**

Run: `python3 -m unittest tests.test_render_rows -v`
Expected: all tests PASS.

## Task 3: Confirm existing validation still works

- [ ] **Step 6: Run the full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0. If `validate_receipt.py` fails because it asserts `CONTEXT USED` is present with `--scope session`, that's exactly the behavior this part removes — fix the assertion by confining it to `latest-turn` cases.

- [ ] **Step 7: Commit**

```bash
git add token_receipt/render.py tests/test_render_rows.py scripts/validate_receipt.py
git commit -m "feat(render): gate CONTEXT USED, honor --hide-fields, render PARTIAL"
```

(Drop `scripts/validate_receipt.py` from the `git add` line if you did not need to edit it.)
