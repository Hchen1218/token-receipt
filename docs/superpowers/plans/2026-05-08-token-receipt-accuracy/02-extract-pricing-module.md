# Part 02 — Extract the pricing module (behavior-preserving)

**Parent plan:** [README.md](./README.md)

**Goal:** Move `load_pricing`, `find_price`, and `estimate_cost` out of `token_receipt/data.py` into a new `token_receipt/pricing.py` **without changing behavior**. `data.py` re-exports the names so every caller (including `cli.py` and `validate_receipt.py`) keeps working. Later parts rewrite the math — this part is pure refactor.

## Why separate this from the rewrite

Doing the file move first means Part 05's rewrite can be reviewed purely for the math change without being tangled in a 150-line "moved" diff. It also gives us a place to drop per-function tests.

## Files

- Create: `token_receipt/pricing.py`
- Modify: `token_receipt/data.py:1018-1076` (remove the three functions)
- Modify: `token_receipt/data.py:12-22` (adjust imports / re-exports)
- Create: `tests/test_pricing_extraction.py`

## Task 1: Write a regression test that pins current behavior

This test captures the current (buggy) math so the refactor cannot silently change anything. Part 05 will replace this test when the math is intentionally rewritten.

- [ ] **Step 1: Write the failing test**

`tests/test_pricing_extraction.py`:

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_pricing_extraction -v`
Expected: `ModuleNotFoundError: No module named 'token_receipt.pricing'`.

## Task 2: Create `pricing.py` by moving the three functions

- [ ] **Step 3: Create `token_receipt/pricing.py`**

`token_receipt/pricing.py`:

```python
"""Pricing lookup and cost estimation.

Extracted from token_receipt/data.py unchanged so the move is behavior-preserving.
Part 05 rewrites the math; this file currently contains the legacy logic.
"""

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


def estimate_cost(snapshot: UsageSnapshot, pricing_path: Path) -> PriceEstimate:
    # Kimi context.jsonl 只有上下文累计 token_count，不能直接套 API 分项单价
    if snapshot.skip_price_estimate:
        return PriceEstimate(status="UNMAPPED", amount=None)

    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    cached = min(snapshot.cached_input_tokens, snapshot.input_tokens)
    cache_write = min(snapshot.cache_write_tokens, max(snapshot.input_tokens - cached, 0))
    uncached = max(snapshot.input_tokens - cached - cache_write, 0)

    input_rate = float(entry.get("input_per_million", 0.0))
    cached_rate = float(entry.get("cached_input_per_million", input_rate))
    cache_write_rate = float(entry.get("cache_write_5m_per_million", input_rate))
    output_rate = float(entry.get("output_per_million", 0.0))

    amount = (
        uncached * input_rate
        + cached * cached_rate
        + cache_write * cache_write_rate
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
```

- [ ] **Step 4: Remove the three functions from `data.py`**

Delete lines 1018–1076 of `token_receipt/data.py` (the block starting at `def load_pricing(path: Path)` and ending at the `)` closing `estimate_cost`'s return). Verify by running: `grep -n "^def load_pricing\|^def find_price\|^def estimate_cost" token_receipt/data.py` — expected: no matches.

- [ ] **Step 5: Re-export from `data.py` so every existing import site keeps working**

At the top of `token_receipt/data.py`, directly under the existing `from .models import (...)` block (around line 22), add:

```python
from .pricing import estimate_cost, find_price, load_pricing  # re-export; moved in Part 02
```

The re-export line is intentionally a single line so a grep for `from .pricing` finds it immediately.

- [ ] **Step 6: Run the new tests**

Run: `python3 -m unittest tests.test_pricing_extraction -v`
Expected: `Ran 5 tests` + `OK`.

- [ ] **Step 7: Run the whole test suite and the validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0; no behavior change visible in generated receipts.

- [ ] **Step 8: Commit**

```bash
git add token_receipt/pricing.py token_receipt/data.py tests/test_pricing_extraction.py
git commit -m "refactor: extract pricing.py from data.py (behavior-preserving)"
```
