# Follow-ups after token-receipt accuracy rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land three surgical follow-ups from the 2026-05-08 accuracy rework as one PR: fix Bedrock Haiku-3.5 normalization, widen the Claude Code session-id env lookup, and stop dev-shell env leakage from breaking in-process unit tests.

**Architecture:** Three narrow fixes in a single PR, three commits. A new internal module `token_receipt/_envguard.py` holds a shared `LEAKY_ENV_VARS` frozenset that both subprocess-based (`tests/test_cli_flags.py`, `scripts/validate_receipt.py`) and in-process (`tests/test_pricing_math.py`, `tests/test_bedrock.py`) test helpers import. `token_receipt/bedrock.py::normalize_bedrock_model` grows a second regex branch for `claude-N-M-<slug>`. `token_receipt/data.py::runtime_claude_session_id` checks `CLAUDE_CODE_SESSION_ID` first and falls back to `CLAUDE_SESSION_ID`.

**Tech Stack:** Python 3 stdlib only (`unittest`, `unittest.mock.patch.dict`, `re`). No new dependencies. TDD throughout — every behavioral change lands as a failing test first.

**Spec:** `docs/superpowers/specs/2026-05-09-followups-after-accuracy-rework.md`

---

## File Structure

**New files:**
- `token_receipt/_envguard.py` — holds `LEAKY_ENV_VARS: frozenset[str]`. Library-internal (leading underscore); imported by tests and `scripts/validate_receipt.py`.
- `tests/test_envguard.py` — one guard test that asserts the 4 known leakers stay in the set.
- `tests/test_data.py` — three tests for `runtime_claude_session_id` (priority, fallback, None-when-unset).

**Modified files:**
- `token_receipt/bedrock.py` — add `_MAJOR_MINOR_SLUG_RE` + second branch in `normalize_bedrock_model`.
- `token_receipt/data.py` — widen `runtime_claude_session_id` tuple; update `SystemExit` message in `_load_claude_aggregate`.
- `tests/test_bedrock.py` — add 3 normalization tests; add `setUp` to `ResolveSnapshotWiresInBedrockTest` only.
- `tests/test_pricing_math.py` — add `setUp` to `EstimateCostTest`.
- `tests/test_cli_flags.py` — swap inline scrub set for the new import.
- `scripts/validate_receipt.py` — swap `_LEAKY_ENV_VARS` literal set for the new import.
- `CHANGELOG.md` — add a `## 2026-05-09` block with 3 bullets.

**Execution order (from spec):** FU-3 (env guard) → FU-2 (session-id widen) → FU-1 (Bedrock normalize). One commit per follow-up, plus a final commit for the CHANGELOG block.

---

## Pre-flight

### Task 0: Baseline the test suite in both envs

Before changing anything, capture the current test count and which tests pass/fail clean vs. dev-shell. This is the yardstick every later step is checked against.

**Files:**
- Read-only.

- [ ] **Step 1: Run clean-env suite and capture totals**

Run:
```bash
cd /Users/kentpeng/projects/token-receipt
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: ends with a line like `Ran N tests in …s\n\nOK`. Record `N` as the pre-PR baseline.

- [ ] **Step 2: Run dev-shell suite to confirm the two expected failures**

Run (in a shell that has Bedrock-on-Claude-Code env set, i.e. without `env -i`):
```bash
cd /Users/kentpeng/projects/token-receipt
python3 -m unittest discover -s tests -v 2>&1 | tail -30
```

Expected: the summary reports `FAILED (failures=2)` (or ≥2) with these two named in the trace:
- `tests.test_pricing_math.EstimateCostTest.test_reported_session_5m_ttl` — `AssertionError: 103.74 != 73.07 within 1 places`
- `tests.test_bedrock.ResolveSnapshotWiresInBedrockTest.test_manual_snapshot_without_overrides_rewrites_both` — `AssertionError: 'aws bedrock' != 'unknown'`

If either of those is *not* failing in your dev shell, either (a) the dev-shell env isn't set the way the spec assumes (check `env | grep -E 'BEDROCK|ANTHROPIC_MODEL'`), or (b) a prior fix already landed — stop and re-read the spec before proceeding.

- [ ] **Step 3: Run validate_receipt.py clean-env to confirm the fixture baseline**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```

Expected: `token-receipt validation passed` on the last line; exit code 0.

No commit; this task just establishes the baseline numbers for later verification steps.

---

## Follow-up 3 — Scrub leaky env vars (lands first)

### Task 1: Create `token_receipt/_envguard.py`

**Files:**
- Create: `token_receipt/_envguard.py`

- [ ] **Step 1: Write the module**

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

- [ ] **Step 2: Verify the module imports cleanly**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -c "from token_receipt._envguard import LEAKY_ENV_VARS; print(sorted(LEAKY_ENV_VARS))"
```

Expected output:
```
['ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'CLAUDE_CODE_USE_BEDROCK', 'ENABLE_PROMPT_CACHING_1H_BEDROCK']
```

No commit yet — this lands together with the guard test in Task 2 so the first commit ships a self-verifying constant.

---

### Task 2: Add the guard test

**Files:**
- Create: `tests/test_envguard.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_envguard.py`:

```python
"""Guard that the scrub list retains the known Claude Code on Bedrock leakers.

If a future refactor trims any of these four, the matching in-process test
(tests/test_pricing_math.py or tests/test_bedrock.py) would start failing in
dev shells *silently* relative to the clean-env suite — which is the exact
footgun this PR closes. Keep this test narrow: it only guards the four known
leakers; adding a new leaker to LEAKY_ENV_VARS does not require updating this
test.
"""

from __future__ import annotations

import unittest

from token_receipt._envguard import LEAKY_ENV_VARS


class LeakyEnvVarsTest(unittest.TestCase):
    def test_includes_known_leakers(self):
        for key in (
            "ENABLE_PROMPT_CACHING_1H_BEDROCK",
            "CLAUDE_CODE_USE_BEDROCK",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
        ):
            with self.subTest(key=key):
                self.assertIn(key, LEAKY_ENV_VARS, f"{key} must stay in the scrub list")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test file alone**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_envguard -v
```

Expected:
```
test_includes_known_leakers (tests.test_envguard.LeakyEnvVarsTest) ... ok

----------------------------------------------------------------------
Ran 1 test in …s

OK
```

No commit yet; the module + its guard ship together in Task 5.

---

### Task 3: Swap the inline scrub set in `tests/test_cli_flags.py`

**Files:**
- Modify: `tests/test_cli_flags.py:8-37`

- [ ] **Step 1: Add the import and delete the inline literal**

In `tests/test_cli_flags.py`, edit the top of the file and the `_run` function. The current code (lines 1-37):

```python
"""CLI surfaces --cache-ttl, --hide-fields, expanded --scope, and silent --write."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "token_receipt.py"


def _run(args, env=None):
    # Start from parent env, then scrub vars that would leak Bedrock/TTL preferences
    # into subprocess behavior, and finally apply any caller-supplied override.
    child_env = {
        k: v for k, v in os.environ.items()
        if k not in {
            "ENABLE_PROMPT_CACHING_1H_BEDROCK",
            "CLAUDE_CODE_USE_BEDROCK",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
        }
    }
    if env:
        child_env.update(env)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
```

becomes:

```python
"""CLI surfaces --cache-ttl, --hide-fields, expanded --scope, and silent --write."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from token_receipt._envguard import LEAKY_ENV_VARS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "token_receipt.py"


def _run(args, env=None):
    # Start from parent env, scrub LEAKY_ENV_VARS to keep subprocess behavior
    # deterministic across dev shells, and finally apply any caller-supplied override.
    child_env = {k: v for k, v in os.environ.items() if k not in LEAKY_ENV_VARS}
    if env:
        child_env.update(env)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
```

Do not touch anything below the `subprocess.run(` line. The rest of `_run` (lines 32-37) stays as-is.

- [ ] **Step 2: Run the CLI-flags tests**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_cli_flags -v
```

Expected: all tests in the file pass (`ok` lines for `FlagParsingTest`, `SilentWriteTest`, `CacheTtlFlagTest`, `HideFieldsFlagTest`). Final line: `OK`.

No commit yet.

---

### Task 4: Swap the `_LEAKY_ENV_VARS` literal in `scripts/validate_receipt.py`

**Files:**
- Modify: `scripts/validate_receipt.py:19-52`

- [ ] **Step 1: Remove the module-level literal and rewire the two references**

In `scripts/validate_receipt.py`:

Replace the current block (lines 19-34):

```python
from token_receipt.data import newest_claude_usage_file, requested_agent_tool, runtime_agent_tool, runtime_claude_session_id, runtime_opencode_session_id  # noqa: E402
from token_receipt.models import printable_receipt_char, visual_display_width  # noqa: E402
from token_receipt.render import zh_tip_footer_candidates  # noqa: E402

SCRIPT = ROOT / "scripts" / "token_receipt.py"
HOOK_SCRIPT = ROOT / "scripts" / "claude_session_end_hook.py"
INSTALLER = ROOT / "scripts" / "install_claude_auto_trigger.py"
UNINSTALLER = ROOT / "scripts" / "uninstall_claude_auto_trigger.py"


_LEAKY_ENV_VARS = {
    "ENABLE_PROMPT_CACHING_1H_BEDROCK",
    "CLAUDE_CODE_USE_BEDROCK",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
}
```

with:

```python
from token_receipt._envguard import LEAKY_ENV_VARS  # noqa: E402
from token_receipt.data import newest_claude_usage_file, requested_agent_tool, runtime_agent_tool, runtime_claude_session_id, runtime_opencode_session_id  # noqa: E402
from token_receipt.models import printable_receipt_char, visual_display_width  # noqa: E402
from token_receipt.render import zh_tip_footer_candidates  # noqa: E402

SCRIPT = ROOT / "scripts" / "token_receipt.py"
HOOK_SCRIPT = ROOT / "scripts" / "claude_session_end_hook.py"
INSTALLER = ROOT / "scripts" / "install_claude_auto_trigger.py"
UNINSTALLER = ROOT / "scripts" / "uninstall_claude_auto_trigger.py"
```

Then inside `run_script` (was lines 40 and 49), the current code reads:

```python
    child_env = {k: v for k, v in os.environ.items() if k not in _LEAKY_ENV_VARS}
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        child_env.update(env)
    # Re-scrub after merge: some callers intentionally spread os.environ (e.g.
    # to keep PATH/HOME) and would otherwise reintroduce the leaky vars. Cases
    # that explicitly want these set (e.g. "CLAUDE_CODE_USE_BEDROCK": "1") are
    # preserved by checking the caller-supplied env first.
    caller_env_keys = set(env or {})
    for leaky in _LEAKY_ENV_VARS:
        if leaky not in caller_env_keys:
            child_env.pop(leaky, None)
```

Change both `_LEAKY_ENV_VARS` to `LEAKY_ENV_VARS`:

```python
    child_env = {k: v for k, v in os.environ.items() if k not in LEAKY_ENV_VARS}
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        child_env.update(env)
    # Re-scrub after merge: some callers intentionally spread os.environ (e.g.
    # to keep PATH/HOME) and would otherwise reintroduce the leaky vars. Cases
    # that explicitly want these set (e.g. "CLAUDE_CODE_USE_BEDROCK": "1") are
    # preserved by checking the caller-supplied env first.
    caller_env_keys = set(env or {})
    for leaky in LEAKY_ENV_VARS:
        if leaky not in caller_env_keys:
            child_env.pop(leaky, None)
```

Note: the comment and behavior of `run_script` is unchanged. Nothing else in the file should change.

- [ ] **Step 2: Run validate_receipt end-to-end**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```

Expected: `token-receipt validation passed`, exit 0.

- [ ] **Step 3: Also run in the bare dev shell**

Run (no `env -i`):
```bash
python3 scripts/validate_receipt.py
```

Expected: same — `token-receipt validation passed`, exit 0. Run_script's explicit caller-env override for the Bedrock fixture (line ~815) still works because `LEAKY_ENV_VARS` is the same set of names.

No commit yet.

---

### Task 5: Add `setUp` to the two failing in-process tests

**Files:**
- Modify: `tests/test_pricing_math.py:1-23`
- Modify: `tests/test_bedrock.py:1-90`

First, fix `tests/test_pricing_math.py::EstimateCostTest`.

- [ ] **Step 1: Confirm the failing test fails in the dev shell (TDD red)**

Run (no `env -i`, so the dev-shell leakers are live):
```bash
python3 -m unittest tests.test_pricing_math.EstimateCostTest.test_reported_session_5m_ttl -v
```

Expected: `FAIL: test_reported_session_5m_ttl … AssertionError: 103.74 != 73.07 within 1 places`. This is the proof the leak exists.

If the test passes here, your dev shell is not actually setting `ENABLE_PROMPT_CACHING_1H_BEDROCK=1`. Either set it (`export ENABLE_PROMPT_CACHING_1H_BEDROCK=1`) or skip to Task 6 since the fix is still correct but you can't observe the regression locally.

- [ ] **Step 2: Add imports and `setUp` to EstimateCostTest**

Edit `tests/test_pricing_math.py`. The current top of file (lines 1-23) reads:

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
```

becomes:

```python
"""estimate_cost bills all four buckets; PARTIAL status when rates are missing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_receipt._envguard import LEAKY_ENV_VARS
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
    def setUp(self):
        # Dev shells (Claude Code on Bedrock) export env vars that silently
        # re-route pricing resolution — scrub them so every test in this class
        # runs against a deterministic os.environ. patch.dict can't delete
        # keys, so rebuild the dict with leakers stripped and patch wholesale.
        scrubbed = {k: v for k, v in os.environ.items() if k not in LEAKY_ENV_VARS}
        patcher = patch.dict(os.environ, scrubbed, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reported_session_5m_ttl(self):
```

Everything below `def test_reported_session_5m_ttl(self):` stays unchanged.

- [ ] **Step 3: Verify the red test is now green in the dev shell (TDD green)**

Run (no `env -i`):
```bash
python3 -m unittest tests.test_pricing_math.EstimateCostTest -v
```

Expected: all 7 tests in the class pass. Final line `OK`. Crucially, `test_reported_session_5m_ttl` now reports `ok`, not `FAIL`.

- [ ] **Step 4: Confirm the clean-env run still passes**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_pricing_math -v
```

Expected: same `OK`, same 7 tests. No regression from the setUp.

Now fix `tests/test_bedrock.py::ResolveSnapshotWiresInBedrockTest`. Scope: only this class gets the setUp — the three `NormalizeBedrockModelTest`, `LooksLikeBedrockModelTest`, `IsBedrockEnvTest`, and `ResolveProviderAndModelTest` classes pass `env=` explicitly and must stay untouched.

- [ ] **Step 5: Confirm the red test fails in the dev shell (TDD red)**

Run (no `env -i`):
```bash
python3 -m unittest tests.test_bedrock.ResolveSnapshotWiresInBedrockTest.test_manual_snapshot_without_overrides_rewrites_both -v
```

Expected: `FAIL … AssertionError: 'aws bedrock' != 'unknown'`.

- [ ] **Step 6: Add imports and a setUp to ResolveSnapshotWiresInBedrockTest only**

Edit `tests/test_bedrock.py`. The current imports (lines 1-7) read:

```python
"""Bedrock model normalization and provider rewrite."""

from __future__ import annotations

import unittest

from token_receipt import bedrock
```

becomes:

```python
"""Bedrock model normalization and provider rewrite."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from token_receipt import bedrock
from token_receipt._envguard import LEAKY_ENV_VARS
```

Then the `ResolveSnapshotWiresInBedrockTest` class (line 90) currently opens:

```python
class ResolveSnapshotWiresInBedrockTest(unittest.TestCase):
    def test_manual_snapshot_bedrock_model_normalized(self):
```

becomes:

```python
class ResolveSnapshotWiresInBedrockTest(unittest.TestCase):
    def setUp(self):
        # resolve_snapshot → _finalize → resolve_provider_and_model reads
        # os.environ directly via is_bedrock_env(); dev shells with
        # CLAUDE_CODE_USE_BEDROCK=1 silently rewrite "unknown" to "aws bedrock".
        # Scrub the known leakers so this class is deterministic everywhere.
        scrubbed = {k: v for k, v in os.environ.items() if k not in LEAKY_ENV_VARS}
        patcher = patch.dict(os.environ, scrubbed, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_manual_snapshot_bedrock_model_normalized(self):
```

Do not add `setUp` to the other four test classes in this file. Do not change anything below this method header.

- [ ] **Step 7: Verify the red test is now green in the dev shell**

Run (no `env -i`):
```bash
python3 -m unittest tests.test_bedrock.ResolveSnapshotWiresInBedrockTest -v
```

Expected: both tests in the class pass (`test_manual_snapshot_bedrock_model_normalized` and `test_manual_snapshot_without_overrides_rewrites_both`). Final line `OK`.

- [ ] **Step 8: Full-suite verification — both environments**

Run (clean env):
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: `OK`; count is baseline + 1 (the new `test_envguard` test from Task 2 plus any that was already landing from the new module — verify the count equals baseline-from-Task-0 plus exactly 1).

Run (dev shell, no `env -i`):
```bash
python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: same count as the clean-env run, and `OK` (no failures). If you still see a failure, the setUp is missing from one of the two classes — go back and check.

- [ ] **Step 9: Commit FU-3**

```bash
git -C /Users/kentpeng/projects/token-receipt add \
  token_receipt/_envguard.py \
  tests/test_envguard.py \
  tests/test_cli_flags.py \
  tests/test_pricing_math.py \
  tests/test_bedrock.py \
  scripts/validate_receipt.py
git -C /Users/kentpeng/projects/token-receipt commit -m "$(cat <<'EOF'
refactor(tests): extract LEAKY_ENV_VARS and scrub in-process env leakage

Claude Code on Bedrock dev shells export ENABLE_PROMPT_CACHING_1H_BEDROCK,
CLAUDE_CODE_USE_BEDROCK, ANTHROPIC_MODEL, ANTHROPIC_SMALL_FAST_MODEL, which
leak into estimate_cost (1h TTL branch) and resolve_provider_and_model
(force-rewrite to aws bedrock). The subprocess scrubs in tests/test_cli_flags
and scripts/validate_receipt already handled this; the in-process unit tests
in tests/test_pricing_math and tests/test_bedrock did not.

Add token_receipt/_envguard.py holding LEAKY_ENV_VARS, import it from both
subprocess scrub sites (replacing two duplicated literals) and from setUp in
EstimateCostTest and ResolveSnapshotWiresInBedrockTest. Adds a guard test
that pins the four known leakers so a future trim can't silently regress
the dev-shell matrix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: `[main <sha>] refactor(tests): extract LEAKY_ENV_VARS …` with 6 files changed.

---

## Follow-up 2 — Widen Claude Code session-id env lookup (lands second)

### Task 6: Add failing tests for `runtime_claude_session_id` in a new `tests/test_data.py`

**Files:**
- Create: `tests/test_data.py`

- [ ] **Step 1: Write the three failing tests**

Create `tests/test_data.py`:

```python
"""Tests for token_receipt.data helpers that read os.environ at runtime."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from token_receipt.data import runtime_claude_session_id


class RuntimeClaudeSessionIdTest(unittest.TestCase):
    def test_prefers_claude_code_variant_over_legacy(self):
        """CLAUDE_CODE_SESSION_ID (the var Claude Code actually exports) wins."""
        env = {"CLAUDE_CODE_SESSION_ID": "new-sid", "CLAUDE_SESSION_ID": "legacy-sid"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(runtime_claude_session_id(), "new-sid")

    def test_falls_back_to_legacy_when_only_legacy_set(self):
        """CLAUDE_SESSION_ID keeps working so prior installs aren't broken."""
        env = {"CLAUDE_SESSION_ID": "legacy-only"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(runtime_claude_session_id(), "legacy-only")

    def test_returns_none_when_neither_is_set(self):
        """Preserve the existing Optional[str] contract — None, not ''."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(runtime_claude_session_id())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify the first two fail, the third passes**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_data -v
```

Expected:
- `test_falls_back_to_legacy_when_only_legacy_set` → `ok` (today's resolver already reads `CLAUDE_SESSION_ID`).
- `test_returns_none_when_neither_is_set` → `ok` (today's resolver already returns `None` when unset).
- `test_prefers_claude_code_variant_over_legacy` → `FAIL` — returns `'legacy-sid'`, expected `'new-sid'`. This is the red to-be-fixed state.

One failure out of three. Good — that's the TDD red bar.

No commit yet.

---

### Task 7: Widen `runtime_claude_session_id` to read `CLAUDE_CODE_SESSION_ID` first

**Files:**
- Modify: `token_receipt/data.py:876-882`

- [ ] **Step 1: Change the tuple of env keys**

In `token_receipt/data.py`, locate the function at line 876-882:

```python
def runtime_claude_session_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    for key in ("CLAUDE_SESSION_ID",):
        value = runtime.get(key)
        if value:
            return value.strip()
    return None
```

Replace with:

```python
def runtime_claude_session_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = runtime.get(key)
        if value and value.strip():
            return value.strip()
    return None
```

Two changes, both necessary:
1. The tuple now has both names, with `CLAUDE_CODE_SESSION_ID` first so it wins when both are set.
2. The guard is `if value and value.strip():` instead of `if value:` so that a whitespace-only value (e.g. `"CLAUDE_CODE_SESSION_ID=   "`) falls through to the legacy var instead of returning empty string. Without this, `runtime.get("CLAUDE_CODE_SESSION_ID") = "  "` would pass `if value:` (non-empty string is truthy) and return `.strip()` → `""`, which the caller's `if not session_id:` then treats as unset — but only after short-circuiting the fallback to the real legacy value. That would be a regression for anyone who exports `CLAUDE_SESSION_ID` and happens to also have an accidental empty `CLAUDE_CODE_SESSION_ID`.

- [ ] **Step 2: Run the three tests — all should pass now**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_data -v
```

Expected: all 3 tests pass, `OK`.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: `OK`, count = baseline-from-Task-0 + 1 (envguard) + 3 (test_data) = baseline + 4.

- [ ] **Step 4: Run validate_receipt.py to confirm the existing fixture still exercises the fallback**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```

Expected: `token-receipt validation passed`. The fixture at `scripts/validate_receipt.py:703` sets `CLAUDE_SESSION_ID` (legacy name), which now exercises the fallback branch — that's the point.

No commit yet — the error message update in Task 8 ships alongside.

---

### Task 8: Update the `SystemExit` message to mention both env var names

**Files:**
- Modify: `token_receipt/data.py:1095-1100`

- [ ] **Step 1: Edit the error message**

In `token_receipt/data.py`, locate the block at line 1091-1100 inside `_load_claude_aggregate`:

```python
    elif args.scope in ("session", "session-all"):
        since = epoch
        until = now
        session_id = runtime_claude_session_id()
        if not session_id:
            raise SystemExit(
                f"--scope {args.scope} needs the active Claude Code sessionId. "
                "Run token-receipt from inside Claude Code (CLAUDE_SESSION_ID is set), "
                "or pass --scope today for a whole-day aggregate."
            )
```

Update the middle string to name both env vars (so operators grep-find either):

```python
    elif args.scope in ("session", "session-all"):
        since = epoch
        until = now
        session_id = runtime_claude_session_id()
        if not session_id:
            raise SystemExit(
                f"--scope {args.scope} needs the active Claude Code sessionId. "
                "Run token-receipt from inside Claude Code (CLAUDE_CODE_SESSION_ID or "
                "CLAUDE_SESSION_ID must be set), or pass --scope today for a whole-day aggregate."
            )
```

- [ ] **Step 2: Manually verify the new message fires**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/token_receipt.py --agent-tool claude-code --scope session 2>&1 | head -3
```

Expected: a non-zero exit with stderr containing the string `CLAUDE_CODE_SESSION_ID or CLAUDE_SESSION_ID must be set`. The exact wording can vary depending on other state, but the substring must be present.

- [ ] **Step 3: Re-run the full suite**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: `OK`, same count (baseline + 4). The message change has no test assertion but must not break anything.

- [ ] **Step 4: Commit FU-2**

```bash
git -C /Users/kentpeng/projects/token-receipt add \
  token_receipt/data.py \
  tests/test_data.py
git -C /Users/kentpeng/projects/token-receipt commit -m "$(cat <<'EOF'
fix(data): widen Claude Code session-id env lookup to CLAUDE_CODE_SESSION_ID

Claude Code actually exports CLAUDE_CODE_SESSION_ID (confirmed with `env |
grep SESSION` in a live Claude Code shell); the resolver was reading
CLAUDE_SESSION_ID only, so --scope session/session-all raised
"sessionId not set" even when a real session was live.

runtime_claude_session_id now checks CLAUDE_CODE_SESSION_ID first and falls
back to CLAUDE_SESSION_ID (which scripts/validate_receipt.py continues to
exercise via its fixture). Optional[str] return type is preserved so
_load_claude_aggregate's `if not session_id:` guard stays valid.

Also updates the SystemExit message in _load_claude_aggregate to name both
env vars.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: `[main <sha>] fix(data): widen Claude Code session-id env lookup …` with 2 files changed.

---

## Follow-up 1 — Normalize `claude-3-5-haiku` Bedrock models (lands last)

### Task 9: Add three failing tests for `claude-N-M-<slug>` normalization

**Files:**
- Modify: `tests/test_bedrock.py` (append to existing test classes — no new file)

- [ ] **Step 1: Add the first two tests to `NormalizeBedrockModelTest`**

In `tests/test_bedrock.py`, append these two methods to the existing `NormalizeBedrockModelTest` class (after `test_haiku_dash_major_minor_kept`, before line 64's blank line separating classes):

```python
    def test_normalizes_claude_3_5_haiku_from_apac(self):
        # claude-N-M-<slug> shape: version numbers before the slug, not after.
        self.assertEqual(
            bedrock.normalize_bedrock_model("apac.anthropic.claude-3-5-haiku"),
            "claude-3.5-haiku",
        )

    def test_normalizes_claude_3_5_haiku_from_any_region(self):
        for prefix in ("global", "us", "eu", "apac"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    bedrock.normalize_bedrock_model(
                        f"{prefix}.anthropic.claude-3-5-haiku"
                    ),
                    "claude-3.5-haiku",
                )
```

- [ ] **Step 2: Add the integration test to `ResolveProviderAndModelTest`**

Also append a test to the existing `ResolveProviderAndModelTest` class (after `test_non_bedrock_passthrough`, before the blank line separating it from `ResolveSnapshotWiresInBedrockTest`). This test asserts the fix actually plumbs through to `find_price`, which is the user-visible bug:

```python
    def test_resolve_provider_and_model_pricing_match(self):
        """End-to-end: APAC Bedrock Haiku 3.5 must land in pricing.json."""
        from token_receipt.models import DEFAULT_PRICING
        from token_receipt.pricing import find_price

        provider, model = bedrock.resolve_provider_and_model(
            "anthropic", "apac.anthropic.claude-3-5-haiku", env={},
        )
        self.assertEqual((provider, model), ("aws bedrock", "claude-3.5-haiku"))
        entry = find_price(provider, model, DEFAULT_PRICING)
        self.assertIsNotNone(entry, "claude-3.5-haiku missing from DEFAULT_PRICING")
```

- [ ] **Step 3: Run the three new tests and confirm they fail**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest \
  tests.test_bedrock.NormalizeBedrockModelTest.test_normalizes_claude_3_5_haiku_from_apac \
  tests.test_bedrock.NormalizeBedrockModelTest.test_normalizes_claude_3_5_haiku_from_any_region \
  tests.test_bedrock.ResolveProviderAndModelTest.test_resolve_provider_and_model_pricing_match \
  -v
```

Expected: all three FAIL. The first two assert `'claude-3-5-haiku' != 'claude-3.5-haiku'`. The third asserts either on the tuple mismatch or on the `find_price` lookup returning `None`.

- [ ] **Step 4: Confirm find_price signature before implementing**

Quickly verify the test's assumed `find_price` signature is real — if it takes a `Path` instead of the `DEFAULT_PRICING` object, adjust the test to match. Run:

```bash
env -i PATH="$PATH" HOME="$HOME" python3 -c "import inspect; from token_receipt.pricing import find_price; print(inspect.signature(find_price))"
```

If the signature is not `(provider, model, <pricing>)` roughly, stop and adapt the test to the real signature before proceeding (keep the intent — that the resolved `(provider, model)` resolves in the current pricing table).

No commit yet.

---

### Task 10: Add `_MAJOR_MINOR_SLUG_RE` and the second normalization branch

**Files:**
- Modify: `token_receipt/bedrock.py:23-44`

- [ ] **Step 1: Add the regex and the branch**

In `token_receipt/bedrock.py`, the current lines 22-44 read:

```python
_VERSION_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")
_MAJOR_MINOR_DASH_RE = re.compile(r"^(claude-[a-z]+-\d+)-(\d+)$")


def is_bedrock_env(env: Optional[Mapping[str, str]] = None) -> bool:
    env = env if env is not None else os.environ
    return env.get("CLAUDE_CODE_USE_BEDROCK", "").strip() in ("1", "true", "TRUE")


def looks_like_bedrock_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in BEDROCK_MODEL_PREFIXES)


def normalize_bedrock_model(model: str) -> str:
    for prefix in BEDROCK_MODEL_PREFIXES:
        if model.startswith(prefix):
            model = model[len(prefix):]
            break
    model = _VERSION_SUFFIX_RE.sub("", model)
    match = _MAJOR_MINOR_DASH_RE.match(model)
    if match:
        model = f"{match.group(1)}.{match.group(2)}"
    return model
```

Add a second regex constant immediately after `_MAJOR_MINOR_DASH_RE`, and a second branch at the end of `normalize_bedrock_model`. The result is:

```python
_VERSION_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")
_MAJOR_MINOR_DASH_RE = re.compile(r"^(claude-[a-z]+-\d+)-(\d+)$")
_MAJOR_MINOR_SLUG_RE = re.compile(r"^claude-(\d+)-(\d+)-([a-z]+)$")


def is_bedrock_env(env: Optional[Mapping[str, str]] = None) -> bool:
    env = env if env is not None else os.environ
    return env.get("CLAUDE_CODE_USE_BEDROCK", "").strip() in ("1", "true", "TRUE")


def looks_like_bedrock_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in BEDROCK_MODEL_PREFIXES)


def normalize_bedrock_model(model: str) -> str:
    for prefix in BEDROCK_MODEL_PREFIXES:
        if model.startswith(prefix):
            model = model[len(prefix):]
            break
    model = _VERSION_SUFFIX_RE.sub("", model)
    match = _MAJOR_MINOR_DASH_RE.match(model)
    if match:
        model = f"{match.group(1)}.{match.group(2)}"
        return model
    match = _MAJOR_MINOR_SLUG_RE.match(model)
    if match:
        model = f"claude-{match.group(1)}.{match.group(2)}-{match.group(3)}"
    return model
```

Two subtleties:
1. I added an explicit `return model` after the first branch so the second regex only runs when the first didn't match. This is stricter than the original (which fell through), but avoids the theoretical case where a string could plausibly match both shapes (in practice none do — `[a-z]+` and `\d+` at the second position are mutually exclusive — but the early return makes the intent obvious).
2. The second branch reassigns `model` but does *not* early-return before the final `return model`; that final line is the single unified exit. Both branches reach it.

- [ ] **Step 2: Run the three previously-red tests — all should pass now**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest \
  tests.test_bedrock.NormalizeBedrockModelTest.test_normalizes_claude_3_5_haiku_from_apac \
  tests.test_bedrock.NormalizeBedrockModelTest.test_normalizes_claude_3_5_haiku_from_any_region \
  tests.test_bedrock.ResolveProviderAndModelTest.test_resolve_provider_and_model_pricing_match \
  -v
```

Expected: all 3 pass, `OK`.

- [ ] **Step 3: Run the entire test_bedrock file to catch regressions**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest tests.test_bedrock -v
```

Expected: all tests in the file pass, including the four existing `NormalizeBedrockModelTest` methods (`test_strips_region_prefix_and_version_bracket`, `test_strips_region_prefix_only`, `test_leaves_bare_model_alone`, `test_haiku_dash_major_minor_kept`). If any existing test regresses, the most likely culprit is the `return model` I added after the first branch — revert that one change and try again.

- [ ] **Step 4: Manual sanity check — the CLI now renders a real USD amount**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/token_receipt.py \
  --agent-tool claude-code \
  --model apac.anthropic.claude-3-5-haiku \
  --input-tokens 1000 --output-tokens 1000 --width 48
```

Expected output contains:
- A row with `SUPPLIER` and `AWS BEDROCK`.
- A row with `PRICE` and `claude-3.5-haiku` (not `claude-3-5-haiku`, not `UNMAPPED`).
- A `USD ESTIMATE` row with a real `$X.XXXXXX` value (not `UNMAPPED`).

This is the spec's Definition-of-done manual sanity check.

- [ ] **Step 5: Full-suite verification — both environments**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: `OK`, count = baseline + 4 + 3 = baseline + 7.

Run (no `env -i`):
```bash
python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: same count, `OK`.

- [ ] **Step 6: Full `validate_receipt.py` smoke in both environments**

Run:
```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```

Then:
```bash
python3 scripts/validate_receipt.py
```

Expected: both print `token-receipt validation passed` and exit 0.

- [ ] **Step 7: Commit FU-1**

```bash
git -C /Users/kentpeng/projects/token-receipt add \
  token_receipt/bedrock.py \
  tests/test_bedrock.py
git -C /Users/kentpeng/projects/token-receipt commit -m "$(cat <<'EOF'
fix(bedrock): normalize claude-N-M-<slug> models to find_price shape

_MAJOR_MINOR_DASH_RE only matched claude-<word>-N-M (e.g. claude-opus-4-7 →
claude-opus-4.7), not claude-N-M-<word>. APAC Bedrock Haiku 3.5 came out as
claude-3-5-haiku, which find_price missed — the receipt showed PROVIDER:
AWS BEDROCK but USD ESTIMATE: UNMAPPED even though the pricing row was
already present (Part 03 added cache_write_1h_per_million for it).

Adds _MAJOR_MINOR_SLUG_RE as a second branch after the existing dash-RE.
The first branch early-returns so the two shapes stay independent, keeping
the existing normalization tests untouched.

Tests cover the APAC-only case, all four region prefixes, and an end-to-end
check that find_price resolves the normalized model against DEFAULT_PRICING.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: `[main <sha>] fix(bedrock): normalize claude-N-M-<slug> …` with 2 files changed.

---

## Task 11: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md:1-3` (insert a new block above the current `## 2026-05-08` block)

- [ ] **Step 1: Insert the 2026-05-09 block at the top**

`CHANGELOG.md` currently opens:

```markdown
# Changelog

## 2026-05-08

### Added
```

Insert the new block so it opens:

```markdown
# Changelog

## 2026-05-09

### Fixed
- `APAC Bedrock Haiku 3.5` (`claude-3-5-haiku`) now normalizes to `claude-3.5-haiku` so `find_price` hits the anthropic pricing entry (was rendering `PROVIDER: AWS BEDROCK` with `USD ESTIMATE: UNMAPPED`).
- `runtime_claude_session_id` now recognizes `CLAUDE_CODE_SESSION_ID` (the variable Claude Code actually exports), with `CLAUDE_SESSION_ID` retained as a fallback. `--scope session`/`session-all` used to fail with "sessionId not set" inside real Claude Code sessions.

### Changed
- Test helpers now share a single `LEAKY_ENV_VARS` list (`token_receipt/_envguard.py`); in-process pricing and bedrock tests now scrub it in `setUp` so they pass in Claude Code on Bedrock dev shells.

## 2026-05-08
```

- [ ] **Step 2: Commit the CHANGELOG**

```bash
git -C /Users/kentpeng/projects/token-receipt add CHANGELOG.md
git -C /Users/kentpeng/projects/token-receipt commit -m "$(cat <<'EOF'
docs(changelog): add 2026-05-09 block for follow-up PR

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: `[main <sha>] docs(changelog): add 2026-05-09 block …` with 1 file changed.

---

## Final verification

### Task 12: Definition-of-done checklist

**Files:**
- Read-only.

- [ ] **Step 1: Clean-env test run**

```bash
env -i PATH="$PATH" HOME="$HOME" python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: `OK`, count = baseline + 7 (3 normalization + 3 session-id + 1 envguard guard). Zero failures, zero errors.

- [ ] **Step 2: Dev-shell test run**

```bash
python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Expected: same count, same `OK`. (Proves the env scrub closes the leakage.)

- [ ] **Step 3: Clean-env validate_receipt**

```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/validate_receipt.py
```

Expected: `token-receipt validation passed`, exit 0.

- [ ] **Step 4: Dev-shell validate_receipt**

```bash
python3 scripts/validate_receipt.py
```

Expected: same — `token-receipt validation passed`, exit 0.

- [ ] **Step 5: Manual Haiku 3.5 sanity check**

```bash
env -i PATH="$PATH" HOME="$HOME" python3 scripts/token_receipt.py \
  --agent-tool claude-code \
  --model apac.anthropic.claude-3-5-haiku \
  --input-tokens 1000 --output-tokens 1000 --width 48
```

Expected: `AWS BEDROCK`, `claude-3.5-haiku`, and a non-`UNMAPPED` `USD ESTIMATE`.

- [ ] **Step 6: CHANGELOG sanity**

```bash
head -20 CHANGELOG.md
```

Expected: the `## 2026-05-09` block at the top with 3 bullets (one Fixed/Fixed/Changed as specified above), followed by the pre-existing `## 2026-05-08` block.

- [ ] **Step 7: Commit log shape**

```bash
git -C /Users/kentpeng/projects/token-receipt log --oneline -5
```

Expected: four new commits on top of `fb69d20`:
1. `refactor(tests): extract LEAKY_ENV_VARS and scrub in-process env leakage`
2. `fix(data): widen Claude Code session-id env lookup to CLAUDE_CODE_SESSION_ID`
3. `fix(bedrock): normalize claude-N-M-<slug> models to find_price shape`
4. `docs(changelog): add 2026-05-09 block for follow-up PR`

Note: this is four commits, not the three mentioned in the spec's "Commit plan" — the CHANGELOG was pulled into its own commit because it touches work from all three follow-ups and reads more cleanly that way. The spec's three-commit intent (one per follow-up) is preserved for the code commits.

If all seven steps pass, the PR is ready to open. No further action in this plan.
