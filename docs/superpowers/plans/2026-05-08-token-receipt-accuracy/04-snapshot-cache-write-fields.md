# Part 04 — Extend `UsageSnapshot` and `PriceEstimate`

**Parent plan:** [README.md](./README.md)

**Goal:** Add the four new snapshot fields (`cache_write_5m_tokens`, `cache_write_1h_tokens`, `aggregation_source`, `deduped_message_ids`) and the `partial_reasons` field on `PriceEstimate`. No logic yet — just the data model. Parts 05–07 fill them in.

All new fields have safe defaults so every existing construction site (including tests) keeps working untouched.

## Files

- Modify: `token_receipt/models.py:37-67` (dataclasses)
- Create: `tests/test_model_fields.py`

## Task 1: Red test — missing fields today

- [ ] **Step 1: Write the failing test**

`tests/test_model_fields.py`:

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_model_fields -v`
Expected: `TypeError: UsageSnapshot.__init__() got an unexpected keyword argument 'cache_write_5m_tokens'` or `AttributeError`.

## Task 2: Add the fields to the dataclasses

- [ ] **Step 3: Update `UsageSnapshot` in `token_receipt/models.py`**

In `token_receipt/models.py`, replace the entire existing `@dataclass class UsageSnapshot:` block (lines 37–56 in the current file) with:

```python
@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    # Kimi Code：context.jsonl 里 `_usage.token_count` 是上下文占用累计，≠ API 分项账单
    context_tokens: Optional[int] = None
    context_window: Optional[int] = None
    provider: str = "unknown"
    model: str = "UNRECORDED"
    source: str = "manual"
    session_id: str = "manual"
    timestamp: Optional[str] = None
    scope: str = "latest-turn"
    available_fields: Tuple[str, ...] = ()
    # 为 True 时不做单价估算（避免把上下文累计误当成 prompt/completion）
    skip_price_estimate: bool = False
    # Per-TTL split of cache-write tokens, populated by claude_aggregator when the
    # source carries message.usage.cache_creation.ephemeral_{5m,1h}_input_tokens.
    # Loaders that cannot distinguish leave these at 0; cache_write_tokens is the aggregate.
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    # Diagnostics for the new aggregator path; None for single-file loaders.
    aggregation_source: Optional[str] = None
    deduped_message_ids: int = 0
```

- [ ] **Step 4: Update `PriceEstimate` in `token_receipt/models.py`**

Replace the existing `@dataclass class PriceEstimate:` block (lines 59–67 in the current file) with:

```python
@dataclass
class PriceEstimate:
    status: str
    amount: Optional[float]
    model: str = "UNMAPPED"
    currency: str = "USD"
    source_url: str = ""
    source_checked_at: str = ""
    rate_note: str = ""
    # Non-empty only when status == "PARTIAL" — lists the rates we substituted for.
    partial_reasons: Tuple[str, ...] = ()
```

- [ ] **Step 5: Run the new tests**

Run: `python3 -m unittest tests.test_model_fields -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Run the whole suite to confirm no consumer broke**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0. `data.py`, `render.py`, `html_render.py` and every caller continues to work because the new fields have defaults.

- [ ] **Step 7: Commit**

```bash
git add token_receipt/models.py tests/test_model_fields.py
git commit -m "feat(models): add cache-write TTL split and aggregator diagnostics"
```
