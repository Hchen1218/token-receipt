# Follow-ups after token-receipt accuracy rework

**Context:** the 11-part plan landed on 2026-05-08 as merge commit `fb69d20` (Merge branch 'worktree-feat-token-receipt-accuracy'). It corrected a 50-70× under-reporting bug and added Bedrock/aggregator/PARTIAL/scope/hide-fields/silent-write features. During per-part code reviews, three narrow gaps surfaced that were out of scope for any specific part. They are batched here as one follow-up PR.

**Relevant commits** (already on `main`, review with `git show <sha>`):
- `b4f1894` — feat(bedrock): normalize provider and model for Claude Code on Bedrock; also adds `tests/test_bedrock.py` (the in-process `ResolveSnapshotWiresInBedrockTest` leak FU-3 fixes).
- `fed0abb` — feat(cli): add --cache-ttl, --hide-fields, today/session-all scopes, silent --write.
- `ac3c88f` — fix(pricing): bill all 4 buckets, support 1h TTL, add PARTIAL status; also adds `tests/test_pricing_math.py` (the in-process `test_reported_session_5m_ttl` leak FU-3 fixes).

**Scope discipline:** keep each fix surgical. Don't bundle unrelated refactors. All three combined should fit in one PR of roughly 40-70 LOC across code + tests + a single `## 2026-05-09` CHANGELOG block with 3 bullets (one per follow-up).

**Test gate for every fix:**
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```
Must both exit 0. Additionally each in-process test added or fixed must also pass in the bare Claude Code on Bedrock dev shell (without `env -i`), since the whole point of follow-up #3 is that the dev shell should stop polluting the suite.

---

## Follow-up 1 — Normalize `claude-3-5-haiku` (and any future `claude-N-M-<slug>` Bedrock models)

**Problem.** `token_receipt/bedrock.py::normalize_bedrock_model("apac.anthropic.claude-3-5-haiku")` currently returns `"claude-3-5-haiku"`, not `"claude-3.5-haiku"`. The regex `_MAJOR_MINOR_DASH_RE = r"^(claude-[a-z]+-\d+)-(\d+)$"` only handles `claude-<word>-<digit>-<digit>` (e.g. `claude-opus-4-7` → `claude-opus-4.7`), not `claude-<digit>-<digit>-<word>`.

`references/pricing.json` lists the model as `claude-3.5-haiku` with aliases `["claude-3.5-haiku", "claude 3.5 haiku", "haiku 3.5"]`. With `claude-3-5-haiku` coming out of normalization, `find_price` in `token_receipt/pricing.py` misses — APAC Bedrock users of Haiku 3.5 see `PROVIDER: AWS BEDROCK` but `USD ESTIMATE: UNMAPPED`. Pricing data is already present (Part 03 added `cache_write_1h_per_million` for it); only the normalization path is missing.

**Existing test coverage.** `tests/test_bedrock.py::LooksLikeBedrockModelTest.test_matches_bedrock_prefixes` already uses the string `"apac.anthropic.claude-3-5-haiku"` to verify the prefix detector — it only asserts that `looks_like_bedrock_model` returns True. There is no assertion on the normalized output for this string, which is why the gap is silent today.

**Fix.** In `token_receipt/bedrock.py`, add a second branch to `normalize_bedrock_model` that handles the `claude-N-M-<slug>` shape. Prefer a second regex over extending the existing one — the current regex is well-tested for the `claude-<word>-N-M` shape and shouldn't be destabilized.

```python
_MAJOR_MINOR_SLUG_RE = re.compile(r"^claude-(\d+)-(\d+)-([a-z]+)$")
```

Inside `normalize_bedrock_model`, after the existing `_MAJOR_MINOR_DASH_RE` block, add:

```python
match = _MAJOR_MINOR_SLUG_RE.match(model)
if match:
    model = f"claude-{match.group(1)}.{match.group(2)}-{match.group(3)}"
```

**Tests to add** in `tests/test_bedrock.py::NormalizeBedrockModelTest`:
- `test_normalizes_claude_3_5_haiku_from_apac` → `"apac.anthropic.claude-3-5-haiku"` should return `"claude-3.5-haiku"`.
- `test_normalizes_claude_3_5_haiku_from_any_region` → also check `"global.anthropic.claude-3-5-haiku"`, `"us.anthropic.claude-3-5-haiku"`, `"eu.anthropic.claude-3-5-haiku"`.
- `test_resolve_provider_and_model_pricing_match` (integration in `ResolveProviderAndModelTest`) — `resolve_provider_and_model("anthropic", "apac.anthropic.claude-3-5-haiku", env={})` should return `("aws bedrock", "claude-3.5-haiku")`, then `find_price(...)` on that result should succeed.

**Non-goal.** Don't rewrite the existing `_MAJOR_MINOR_DASH_RE` or its callers. Two regexes side-by-side is fine; one each for `claude-<word>-N-M` and `claude-N-M-<slug>`.

**CHANGELOG.** Under 2026-05-09 `### Fixed`: `APAC Bedrock Haiku 3.5 (claude-3-5-haiku) now normalizes to claude-3.5-haiku so find_price hits the anthropic entry.`

**Estimated size:** ~5 LOC code + 3 short tests.

---

## Follow-up 2 — Widen Claude Code session-id env lookup

**Problem.** `token_receipt/data.py::runtime_claude_session_id` reads only the env var `CLAUDE_SESSION_ID`. The actual Claude Code runtime exports `CLAUDE_CODE_SESSION_ID` (confirmed: `env | grep SESSION` in a live Claude Code shell shows `CLAUDE_CODE_SESSION_ID=…`, no `CLAUDE_SESSION_ID`).

This is pre-existing, but Part 08 introduced a new `SystemExit` message in `_load_claude_aggregate` (`token_receipt/data.py`, inside `--scope session/session-all`) that tells the user: `"Run token-receipt from inside Claude Code (CLAUDE_SESSION_ID is set)..."` — which amplifies the confusion, since the variable named there isn't actually what Claude Code sets.

**Decision (2026-05-09 brainstorm):** Take **Option A**. Grep audit (`grep -rn "CLAUDE_SESSION_ID\|CLAUDE_CODE_SESSION_ID" token_receipt/ tests/ scripts/ docs/`) turned up only:
- `token_receipt/data.py:878` — the resolver itself.
- `token_receipt/data.py:1098` — the error message inside `_load_claude_aggregate`.
- `scripts/validate_receipt.py:703` — a test fixture that sets `CLAUDE_SESSION_ID` (leave as-is; it exercises the fallback).
- `docs/superpowers/plans/2026-05-08-token-receipt-accuracy/08-cli-and-scope-wiring.md:442` — historical plan doc (leave).

No other live caller uses the legacy name, so Option A is safe.

**Fix (Option A — widen the lookup).** Preserve the current `Optional[str]` signature — `_load_claude_aggregate` already guards with `if not session_id:` so `None` and `""` are equivalent here, and leaving the type alone avoids a drive-by API change:

```python
def runtime_claude_session_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = runtime.get(key)
        if value and value.strip():
            return value.strip()
    return None
```

Update the `SystemExit` message in `_load_claude_aggregate` (data.py ~line 1097) to mention both names: `"...Run token-receipt from inside Claude Code (CLAUDE_CODE_SESSION_ID or CLAUDE_SESSION_ID must be set), or pass --scope today..."`.

**Tests to add.** Create a new `tests/test_data.py` (no file exists today) with three cases:
- `test_runtime_claude_session_id_prefers_claude_code_variant` — patch with both vars set to different values; assert `CLAUDE_CODE_SESSION_ID` wins.
- `test_runtime_claude_session_id_falls_back_to_legacy` — patch with only `CLAUDE_SESSION_ID` set; assert it's returned.
- `test_runtime_claude_session_id_returns_none_when_unset` — patch with both absent; assert `is None` (matches the preserved `Optional[str]` contract).

Use `unittest.mock.patch.dict(os.environ, {...}, clear=True)` for all three. `clear=True` avoids leakage from the dev shell (see follow-up #3 — Option A resolves that footgun for these new tests inherently).

**Non-goal.** The existing fixture in `scripts/validate_receipt.py` that sets `CLAUDE_SESSION_ID` stays untouched — it becomes a de facto fallback-path test.

**CHANGELOG.** Under 2026-05-09 `### Fixed`: `runtime_claude_session_id now recognizes CLAUDE_CODE_SESSION_ID (the variable Claude Code actually exports), with CLAUDE_SESSION_ID retained as a fallback.`

**Estimated size:** ~8 LOC code + 3 tests (new tests/test_data.py) + one `SystemExit` message tweak.

---

## Follow-up 3 — Scrub leaky env vars in in-process unit tests

**Problem.** Two unit tests currently fail in the Claude Code on Bedrock dev shell (where `ENABLE_PROMPT_CACHING_1H_BEDROCK`, `CLAUDE_CODE_USE_BEDROCK`, `ANTHROPIC_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL` are all exported):

1. `tests/test_pricing_math.py::test_reported_session_5m_ttl` — fails with `103.74 != 73.07` because `ENABLE_PROMPT_CACHING_1H_BEDROCK=1` leaks into `token_receipt/pricing.py::resolve_cache_write_split` via `os.environ.get(...)` and flips the TTL resolver's default-5m branch to 1h.
2. `tests/test_bedrock.py::ResolveSnapshotWiresInBedrockTest::test_manual_snapshot_without_overrides_rewrites_both` — fails with `'aws bedrock' != 'unknown'` because `CLAUDE_CODE_USE_BEDROCK=1` and/or `ANTHROPIC_MODEL=global.anthropic.claude-opus-4-7[1m]` leak into `load_manual_snapshot` → `_finalize` → `resolve_provider_and_model`, forcing the Bedrock rewrite.

The branch already ships a matching scrub for subprocess-based tests in two places:
- `tests/test_cli_flags.py::_run` (lines ~16-37)
- `scripts/validate_receipt.py::run_script` (lines ~29-50)

Both of those scrub the same 4-var set before spawning a subprocess. The in-process tests above have no such protection — they call `estimate_cost` / `resolve_snapshot` directly inside the unittest process, inheriting whatever `os.environ` holds.

**Fix.** Two parts:

### Part A — extract the shared leaky-var list

**Decision (2026-05-09 brainstorm):** the constant lives in `token_receipt/_envguard.py` (a library module, not a tests-only helper). `scripts/validate_receipt.py` can't do a relative import from `tests/`, and a library home avoids a "keep in sync" duplicate. The leading underscore marks it internal — only tests and scripts/ import it; public surface is unchanged.

Create `token_receipt/_envguard.py`:

```python
"""Shared env-var scrub list for tests and validate_receipt.

Claude Code on AWS Bedrock exports env vars that silently change pricing/provider
resolution in the library under test. Tests that exercise those code paths must
scrub these vars to be deterministic across dev shells. Subprocess-based tests
use the list via explicit child-env construction; in-process tests use
patch.dict(os.environ, scrubbed, clear=True) in setUp.
"""

from __future__ import annotations

LEAKY_ENV_VARS: frozenset[str] = frozenset({
    "ENABLE_PROMPT_CACHING_1H_BEDROCK",
    "CLAUDE_CODE_USE_BEDROCK",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
})
```

Update the two existing scrub sites to import the constant and drop their inline sets:
- `tests/test_cli_flags.py` — in `_run`, replace the inline set literal (lines ~19-27) with `from token_receipt._envguard import LEAKY_ENV_VARS` and use the imported name.
- `scripts/validate_receipt.py` — replace the module-level `_LEAKY_ENV_VARS` set (lines 29-34) with `from token_receipt._envguard import LEAKY_ENV_VARS`, then update both internal references (lines 40 and 49) to the imported name.

### Part B — scrub in the two failing in-process tests

Add a `setUp` that removes each leaky var from the test process:

```python
# tests/test_pricing_math.py and tests/test_bedrock.py (integration class only)

import os
from unittest.mock import patch

from token_receipt._envguard import LEAKY_ENV_VARS


class EstimateCostTest(unittest.TestCase):
    def setUp(self):
        # Prevent dev-shell env leakage; addCleanup handles the teardown.
        # patch.dict can't delete keys, so rebuild os.environ with leakers stripped.
        scrubbed = {k: v for k, v in os.environ.items() if k not in LEAKY_ENV_VARS}
        patcher = patch.dict(os.environ, scrubbed, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
```

Apply the same `setUp` to `tests/test_bedrock.py::ResolveSnapshotWiresInBedrockTest` only — the other `test_bedrock.py` classes test pure functions with explicit `env=` kwargs and don't need it.

**Verification.** Two test matrices must pass:
1. Clean env: `env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v` → baseline + 3 (FU-2 session-id tests) + 1 (FU-3 guard) + FU-1 normalization tests; the run must report all OK, zero failures/errors.
2. Bare dev shell: `python3 -m unittest discover -s tests -v` (no `env -i`) in a shell that has `ENABLE_PROMPT_CACHING_1H_BEDROCK=1` `CLAUDE_CODE_USE_BEDROCK=1` `ANTHROPIC_MODEL=global.anthropic.claude-opus-4-7[1m]` exported → must produce the same count as matrix 1, all OK.

If both pass, the leakage footgun is closed for every test path.

**Guard test.** Add `tests/test_envguard.py::LeakyEnvVarsTest::test_includes_known_leakers` asserting the 4-var set contains the known leakers. Cheap insurance against someone truncating the list without noticing which unit test stops covering which leaker:
```python
import unittest
from token_receipt._envguard import LEAKY_ENV_VARS


class LeakyEnvVarsTest(unittest.TestCase):
    def test_includes_known_leakers(self):
        for key in ("ENABLE_PROMPT_CACHING_1H_BEDROCK", "CLAUDE_CODE_USE_BEDROCK",
                    "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"):
            self.assertIn(key, LEAKY_ENV_VARS, f"{key} must stay in the scrub list")
```

**CHANGELOG.** Under 2026-05-09 `### Changed`: `Test helpers share a single LEAKY_ENV_VARS list; in-process pricing and bedrock tests now scrub it in setUp so they pass in Claude Code on Bedrock dev shells.`

**Estimated size:** ~20 LOC (new `token_receipt/_envguard.py` + 2 setUp blocks + 1 guard test in `tests/test_envguard.py`) + import swaps in the two scrub sites + CHANGELOG line.

---

## Execution order

Decisions for this PR are already made (see Follow-up 2 and Part A above). Implementation order:

1. Follow-up 3 (the env-guard refactor) first — it adds `LEAKY_ENV_VARS` in `token_receipt/_envguard.py`, swaps the two existing scrub sites to import it, adds the two `setUp` blocks that fix the red tests, and adds the guard test.
2. Follow-up 2 next — widen `runtime_claude_session_id` and update the `SystemExit` message. The new tests in `tests/test_data.py` use `patch.dict(..., clear=True)`, so they're robust regardless of dev-shell env, but landing after FU-3 means the whole suite is green along the way.
3. Follow-up 1 last — add `_MAJOR_MINOR_SLUG_RE` and the three tests in `tests/test_bedrock.py::NormalizeBedrockModelTest` / `ResolveProviderAndModelTest`.

## Commit plan

One PR, three commits:

1. `refactor(tests): extract LEAKY_ENV_VARS and scrub in-process env leakage`
2. `fix(data): widen Claude Code session-id env lookup to CLAUDE_CODE_SESSION_ID`
3. `fix(bedrock): normalize claude-N-M-<slug> models (e.g. claude-3-5-haiku → claude-3.5-haiku)`

(Order chosen so tests are already deterministic when the pricing/bedrock fixes land.)

## Definition of done

- Clean-env test run: all tests OK, zero failures/errors, and the count is strictly greater than pre-PR baseline (at least +4 from FU-2 and FU-3 guard, plus the FU-1 normalization tests).
- Bare dev-shell test run: same count as clean-env, all OK (proves the scrub closed the leakage).
- `validate_receipt.py` exits 0 under both envs.
- Manual sanity (auto-detect path, since explicit `--model` is intentionally preserved verbatim — see `tests/test_bedrock.py::test_manual_snapshot_bedrock_model_normalized` and `scripts/validate_receipt.py:820`):
  ```bash
  env -i PATH="$PATH" HOME="$HOME" \
    CLAUDE_CODE_USE_BEDROCK=1 \
    ANTHROPIC_MODEL="apac.anthropic.claude-3-5-haiku" \
    python3 scripts/token_receipt.py --agent-tool claude-code \
    --input-tokens 1000 --output-tokens 1000 --width 48
  ```
  Must render `PROVIDER: AWS BEDROCK`, `MODEL: claude-3.5-haiku`, and a real `USD ESTIMATE` (e.g. `$0.004800`), not `UNMAPPED`.
- CHANGELOG has a `## 2026-05-09` block with 3 bullets.

## Non-goals for this PR

- Do **not** change the pricing math or add new pricing entries.
- Do **not** re-review or modify commits from the 2026-05-08 merge.
- Do **not** add a logging/telemetry layer for "Bedrock normalization missed" — if a model string falls through all regexes, the existing `UNMAPPED` behavior is acceptable diagnostic surface.
- Do **not** broaden `LEAKY_ENV_VARS` preemptively. Only add vars when a concrete test fails because of them.
