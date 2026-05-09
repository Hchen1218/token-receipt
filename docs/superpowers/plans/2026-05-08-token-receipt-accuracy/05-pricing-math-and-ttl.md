# Part 05 — Rewrite pricing math, add TTL resolver, introduce PARTIAL

**Parent plan:** [README.md](./README.md)

**Goal:** Fix the under-reporting (defects #1, #2, #3, #6). Remove the broken `min(cached, input)` clamp, bill all four buckets (input / cache-read / cache-write / output) at their own rates, resolve 5m-vs-1h TTL from explicit split → CLI override → env flag → default, and render `PARTIAL` when the pricing table is incomplete.

This is the math-only change. Snapshot data still comes from today's loaders; Parts 06–07 add Bedrock normalization and the projects aggregator.

## Files

- Modify: `token_receipt/pricing.py` — rewrite `estimate_cost`, add `compute_total`, add `resolve_cache_write_split`.
- Replace: `tests/test_pricing_extraction.py` with `tests/test_pricing_math.py`, `tests/test_ttl_resolver.py`, `tests/test_compute_total.py` (split for focus).

## Task 1: Replace the "legacy-pin" test with the new behavior test

- [ ] **Step 1: Delete `tests/test_pricing_extraction.py`**

From the repo root, run: `rm tests/test_pricing_extraction.py`

Then verify: `ls tests/test_pricing_extraction.py` — expected: `No such file or directory`.

The test pinned the legacy clamp behavior so Part 02's refactor was safe; now that Part 05 deletes the clamp, the pinned numbers are no longer correct, and three focused test files replace it.

- [ ] **Step 2: Write `tests/test_compute_total.py`**

```python
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
```

- [ ] **Step 3: Write `tests/test_ttl_resolver.py`**

```python
"""resolve_cache_write_split covers all four resolution branches."""

from __future__ import annotations

import unittest

from token_receipt.models import UsageSnapshot
from token_receipt.pricing import resolve_cache_write_split


class ResolveCacheWriteSplitTest(unittest.TestCase):
    def snap(self, total=1000, five=0, one=0):
        return UsageSnapshot(
            cache_write_tokens=total,
            cache_write_5m_tokens=five,
            cache_write_1h_tokens=one,
        )

    def test_cli_override_5m_wins(self):
        snap = self.snap(total=1000, one=300)  # snapshot says 300 at 1h
        self.assertEqual(resolve_cache_write_split(snap, cli_override="5m", env={}),
                         (1000, 0))

    def test_cli_override_1h_wins(self):
        snap = self.snap(total=1000, five=400)
        self.assertEqual(resolve_cache_write_split(snap, cli_override="1h", env={}),
                         (0, 1000))

    def test_per_message_split_used_when_present(self):
        snap = self.snap(total=1000, five=700, one=300)
        self.assertEqual(resolve_cache_write_split(snap, cli_override=None, env={}),
                         (700, 300))

    def test_env_flag_routes_everything_to_1h(self):
        snap = self.snap(total=1000)
        env = {"ENABLE_PROMPT_CACHING_1H_BEDROCK": "1"}
        self.assertEqual(resolve_cache_write_split(snap, cli_override=None, env=env),
                         (0, 1000))

    def test_env_flag_accepts_true_uppercase(self):
        snap = self.snap(total=1000)
        self.assertEqual(
            resolve_cache_write_split(snap, cli_override=None,
                                      env={"ENABLE_PROMPT_CACHING_1H_BEDROCK": "TRUE"}),
            (0, 1000),
        )

    def test_default_is_5m(self):
        snap = self.snap(total=1000)
        self.assertEqual(resolve_cache_write_split(snap, cli_override=None, env={}),
                         (1000, 0))

    def test_cli_override_auto_falls_through(self):
        # CLI layer maps --cache-ttl=auto to cli_override=None.
        snap = self.snap(total=1000, five=700, one=300)
        self.assertEqual(resolve_cache_write_split(snap, cli_override=None, env={}),
                         (700, 300))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Write `tests/test_pricing_math.py`**

```python
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
        """Spec §"Sanity check" — expect $73.07 for 5m TTL."""
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
        """Regression for spec §"the key change vs current"."""
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
```

- [ ] **Step 5: Run — expect failure**

Run: `python3 -m unittest tests.test_compute_total tests.test_ttl_resolver tests.test_pricing_math -v`
Expected: `ImportError: cannot import name 'compute_total'` and `resolve_cache_write_split`, plus failing math for `estimate_cost` (legacy clamp gives wrong number).

## Task 2: Rewrite `token_receipt/pricing.py`

- [ ] **Step 6: Replace `token_receipt/pricing.py` with the new implementation**

Replace the entire file with:

```python
"""Pricing lookup and cost estimation.

Responsibility: given a UsageSnapshot and a pricing.json path, return the
total cost as a PriceEstimate. Owns cache-write TTL resolution and total-tokens
math. No I/O besides reading pricing.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

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


def compute_total(snapshot: UsageSnapshot) -> int:
    """Sum of every billable bucket — used when the source did not supply its own total."""
    return (
        snapshot.input_tokens
        + snapshot.output_tokens
        + snapshot.cached_input_tokens
        + snapshot.cache_write_tokens
        + snapshot.reasoning_output_tokens
    )


def resolve_cache_write_split(
    snapshot: UsageSnapshot,
    cli_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[int, int]:
    """Return (cache_write_5m_tokens, cache_write_1h_tokens).

    Resolution order:
    1. Explicit CLI override (--cache-ttl 5m | 1h).
    2. Per-message split carried by the snapshot (5m/1h fields both nonzero or either nonzero).
    3. Claude Code on Bedrock 1h env flag.
    4. Default to 5m.
    """
    env = env if env is not None else os.environ

    if cli_override == "5m":
        return (snapshot.cache_write_tokens, 0)
    if cli_override == "1h":
        return (0, snapshot.cache_write_tokens)

    if snapshot.cache_write_5m_tokens or snapshot.cache_write_1h_tokens:
        return (snapshot.cache_write_5m_tokens, snapshot.cache_write_1h_tokens)

    flag = env.get("ENABLE_PROMPT_CACHING_1H_BEDROCK", "").strip()
    if flag in ("1", "true", "TRUE"):
        return (0, snapshot.cache_write_tokens)

    return (snapshot.cache_write_tokens, 0)


def estimate_cost(
    snapshot: UsageSnapshot,
    pricing_path: Path,
    cache_ttl_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> PriceEstimate:
    """Bill every bucket at its own rate. Returns PARTIAL when required rates are missing."""
    if snapshot.skip_price_estimate:
        return PriceEstimate(status="UNMAPPED", amount=None)

    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    missing: list[str] = []

    input_rate = entry.get("input_per_million")
    output_rate = entry.get("output_per_million")
    cached_rate = entry.get("cached_input_per_million", input_rate)
    write_5m = entry.get("cache_write_5m_per_million", input_rate)
    write_1h = entry.get("cache_write_1h_per_million")

    split_5m, split_1h = resolve_cache_write_split(snapshot, cache_ttl_override, env)

    if split_1h > 0 and write_1h is None:
        missing.append("cache_write_1h_per_million")
        # Documented Anthropic 1h fallback: 2 * input rate.
        write_1h = (input_rate or 0) * 2.0

    if input_rate is None:
        missing.append("input_per_million")
    if output_rate is None:
        missing.append("output_per_million")

    amount = (
        snapshot.input_tokens * (input_rate or 0)
        + snapshot.cached_input_tokens * (cached_rate or 0)
        + split_5m * (write_5m or 0)
        + split_1h * (write_1h or 0)
        + (snapshot.output_tokens + snapshot.reasoning_output_tokens) * (output_rate or 0)
    ) / 1_000_000

    status = "PARTIAL" if missing else "ESTIMATE"
    return PriceEstimate(
        status=status,
        amount=amount,
        model=str(entry.get("model", snapshot.model)),
        currency=str(entry.get("currency", pricing.get("currency", "USD"))).upper(),
        source_url=str(entry.get("source_url", "")),
        source_checked_at=str(entry.get("source_checked_at", "")),
        rate_note=str(entry.get("rate_note", "")),
        partial_reasons=tuple(missing),
    )
```

- [ ] **Step 7: Run the three new unit tests**

Run: `python3 -m unittest tests.test_compute_total tests.test_ttl_resolver tests.test_pricing_math -v`
Expected: every test PASSES, including `test_reported_session_5m_ttl` (≈$73.07) and `test_reported_session_1h_ttl_via_cli_override` (≈$103.74).

## Task 3: Update the validation script's existing assertions

The original `estimate_cost` clamped `cached` to `input`, so `scripts/validate_receipt.py` may have assertions on exact dollar strings that change now. Look for any hardcoded `$` values in the script and fix the ones that break.

- [ ] **Step 8: Run validate_receipt.py and fix any broken golden values**

Run: `python3 scripts/validate_receipt.py`
If it fails, inspect the failing assertion. Two likely failure modes:
- A case that used a snapshot with `cached_input_tokens > input_tokens` and asserted on the clamped amount → update to the new (higher) amount.
- A case that relied on `cache_write_tokens` being clipped to `max(input - cached, 0)` → update to the unclipped amount.

Edit `scripts/validate_receipt.py` only where needed; keep all non-pricing assertions untouched. After each edit, re-run the script. Do not "assert $ESTIMATE in text" broadly — preserve the exact matching style the file already uses.

If no failures surface, skip the edit and continue.

- [ ] **Step 9: Run the full suite and the validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0.

- [ ] **Step 10: Commit**

```bash
git add token_receipt/pricing.py tests/test_compute_total.py tests/test_ttl_resolver.py tests/test_pricing_math.py scripts/validate_receipt.py
git commit -m "fix(pricing): bill all 4 buckets, support 1h TTL, add PARTIAL status"
```

(If `scripts/validate_receipt.py` did not need changes, drop it from the `git add` line.)
