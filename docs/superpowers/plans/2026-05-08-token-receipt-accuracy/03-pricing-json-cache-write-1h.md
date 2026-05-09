# Part 03 — Add `cache_write_1h_per_million` to anthropic entries

**Parent plan:** [README.md](./README.md)

**Goal:** Populate the 1h cache-write rate for every anthropic entry in `references/pricing.json`. Without this, Part 05 would render `PARTIAL` for any 1h TTL request even though we know the rates.

Anthropic's published 1h cache-write rate is `2 × input_per_million` (the 5m rate is `1.25 × input_per_million`). The 1h fallback used in `pricing.py` for missing entries uses the same `2 ×` ratio, so these explicit values only remove the `PARTIAL` status — the dollar amount is the same.

## Files

- Modify: `references/pricing.json` — add `cache_write_1h_per_million` to each anthropic entry (10 entries, lines ~244–353).
- Create: `tests/test_pricing_json.py`

## Rate table (reference)

All anthropic entries are listed on [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing). The mapping is mechanical: `cache_write_1h_per_million = 2 × input_per_million`.

| Model | input | cache_write_5m | cache_write_1h (new) |
|---|---:|---:|---:|
| claude-opus-4.7 | 5.00 | 6.25 | **10.00** |
| claude-opus-4.6 | 5.00 | 6.25 | **10.00** |
| claude-opus-4.5 | 5.00 | 6.25 | **10.00** |
| claude-opus-4.1 | 15.00 | 18.75 | **30.00** |
| claude-sonnet-4.6 | 3.00 | 3.75 | **6.00** |
| claude-sonnet-4.5 | 3.00 | 3.75 | **6.00** |
| claude-sonnet-4 | 3.00 | 3.75 | **6.00** |
| claude-3.7-sonnet | 3.00 | 3.75 | **6.00** |
| claude-haiku-4.5 | 1.00 | 1.25 | **2.00** |
| claude-3.5-haiku | 0.80 | 1.00 | **1.60** |

## Task 1: Write a schema test that fails on every missing entry

- [ ] **Step 1: Write the failing test**

`tests/test_pricing_json.py`:

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_pricing_json -v`
Expected: `test_every_anthropic_entry_has_cache_write_1h_per_million` fails listing all 10 models.

## Task 2: Add the field to every anthropic entry

For each anthropic entry, insert `cache_write_1h_per_million` immediately after the existing `cache_write_5m_per_million` line. Keep the existing key order otherwise untouched.

- [ ] **Step 3: Update `claude-opus-4.7`** (currently `references/pricing.json:244-254`)

Replace:
```json
      "cache_write_5m_per_million": 6.25,
      "cached_input_per_million": 0.5,
```
with:
```json
      "cache_write_5m_per_million": 6.25,
      "cache_write_1h_per_million": 10.0,
      "cached_input_per_million": 0.5,
```

For Opus 4.7, this substring is unique at that input rate (5.0). For other entries below, use `replace_all` only when the (input_rate, cache_write_5m_rate) tuple is shared across models — the test in Step 2 will catch misses.

- [ ] **Step 4: Update `claude-opus-4.6`** (lines ~255-265)

Same patch as Step 3. Since Opus 4.6 shares `"cache_write_5m_per_million": 6.25,\n      "cached_input_per_million": 0.5,` with 4.7 and 4.5, identify the right entry by the surrounding `"model": "claude-opus-4.6"` line and edit with a larger unique context.

- [ ] **Step 5: Update `claude-opus-4.5`** (lines ~266-276)

Same patch; same note about unique context.

- [ ] **Step 6: Update `claude-opus-4.1`** (lines ~277-287)

Replace:
```json
      "cache_write_5m_per_million": 18.75,
      "cached_input_per_million": 1.5,
```
with:
```json
      "cache_write_5m_per_million": 18.75,
      "cache_write_1h_per_million": 30.0,
      "cached_input_per_million": 1.5,
```

- [ ] **Step 7: Update `claude-sonnet-4.6`** (lines ~288-298)

Replace:
```json
      "cache_write_5m_per_million": 3.75,
      "cached_input_per_million": 0.3,
```
with:
```json
      "cache_write_5m_per_million": 3.75,
      "cache_write_1h_per_million": 6.0,
      "cached_input_per_million": 0.3,
```

- [ ] **Step 8: Update `claude-sonnet-4.5`** (lines ~299-309)

Same patch as Step 7. Use surrounding `"model": "claude-sonnet-4.5"` context to disambiguate.

- [ ] **Step 9: Update `claude-sonnet-4`** (lines ~310-320)

Same patch as Step 7. Disambiguate by `"model": "claude-sonnet-4"`.

- [ ] **Step 10: Update `claude-3.7-sonnet`** (lines ~321-331)

Same patch as Step 7. Disambiguate by `"model": "claude-3.7-sonnet"`.

- [ ] **Step 11: Update `claude-haiku-4.5`** (lines ~332-342)

Replace:
```json
      "cache_write_5m_per_million": 1.25,
      "cached_input_per_million": 0.1,
```
with:
```json
      "cache_write_5m_per_million": 1.25,
      "cache_write_1h_per_million": 2.0,
      "cached_input_per_million": 0.1,
```

- [ ] **Step 12: Update `claude-3.5-haiku`** (lines ~343-353)

Replace:
```json
      "cache_write_5m_per_million": 1.0,
      "cached_input_per_million": 0.08,
```
with:
```json
      "cache_write_5m_per_million": 1.0,
      "cache_write_1h_per_million": 1.6,
      "cached_input_per_million": 0.08,
```

- [ ] **Step 13: Run schema test**

Run: `python3 -m unittest tests.test_pricing_json -v`
Expected: all 3 tests PASS.

- [ ] **Step 14: Run full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0.

- [ ] **Step 15: Commit**

```bash
git add references/pricing.json tests/test_pricing_json.py
git commit -m "feat(pricing): add 1h cache-write rate to anthropic entries"
```
