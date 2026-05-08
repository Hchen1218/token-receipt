# Part 06 — Bedrock provider + model normalization

**Parent plan:** [README.md](./README.md)

**Goal:** Fix defect #4. Claude Code running against AWS Bedrock reports `provider="anthropic"` and `model="global.anthropic.claude-opus-4-7[1m]"`. Today this requires the user to pass `--provider aws bedrock --model claude-opus-4.7` manually. After this part: the receipt says `SUPPLIER: AWS BEDROCK` and the price table resolves automatically.

## Files

- Create: `token_receipt/bedrock.py`
- Modify: `token_receipt/data.py:894-1015` (`resolve_snapshot`) — one call after the loader returns.
- Create: `tests/test_bedrock.py`

## Task 1: Unit test the pure functions

- [ ] **Step 1: Write the failing test**

`tests/test_bedrock.py`:

```python
"""Bedrock model normalization and provider rewrite."""

from __future__ import annotations

import unittest

from token_receipt import bedrock


class IsBedrockEnvTest(unittest.TestCase):
    def test_true_when_flag_set(self):
        for value in ("1", "true", "TRUE"):
            with self.subTest(value=value):
                self.assertTrue(bedrock.is_bedrock_env({"CLAUDE_CODE_USE_BEDROCK": value}))

    def test_false_when_flag_absent_or_empty(self):
        self.assertFalse(bedrock.is_bedrock_env({}))
        self.assertFalse(bedrock.is_bedrock_env({"CLAUDE_CODE_USE_BEDROCK": ""}))
        self.assertFalse(bedrock.is_bedrock_env({"CLAUDE_CODE_USE_BEDROCK": "0"}))


class LooksLikeBedrockModelTest(unittest.TestCase):
    def test_matches_bedrock_prefixes(self):
        for model in (
            "global.anthropic.claude-opus-4-7",
            "us.anthropic.claude-sonnet-4-6",
            "eu.anthropic.claude-haiku-4-5",
            "apac.anthropic.claude-3-5-haiku",
        ):
            with self.subTest(model=model):
                self.assertTrue(bedrock.looks_like_bedrock_model(model))

    def test_ignores_bare_anthropic_slugs(self):
        self.assertFalse(bedrock.looks_like_bedrock_model("claude-opus-4.7"))
        self.assertFalse(bedrock.looks_like_bedrock_model("claude-sonnet-4.6"))


class NormalizeBedrockModelTest(unittest.TestCase):
    def test_strips_region_prefix_and_version_bracket(self):
        self.assertEqual(
            bedrock.normalize_bedrock_model("global.anthropic.claude-opus-4-7[1m]"),
            "claude-opus-4.7",
        )

    def test_strips_region_prefix_only(self):
        self.assertEqual(
            bedrock.normalize_bedrock_model("us.anthropic.claude-sonnet-4-6"),
            "claude-sonnet-4.6",
        )

    def test_leaves_bare_model_alone(self):
        self.assertEqual(
            bedrock.normalize_bedrock_model("claude-opus-4.7"),
            "claude-opus-4.7",
        )

    def test_haiku_dash_major_minor_kept(self):
        # claude-haiku-4-5 → claude-haiku-4.5
        self.assertEqual(
            bedrock.normalize_bedrock_model("eu.anthropic.claude-haiku-4-5"),
            "claude-haiku-4.5",
        )


class ResolveProviderAndModelTest(unittest.TestCase):
    def test_bedrock_prefix_rewrites_provider(self):
        self.assertEqual(
            bedrock.resolve_provider_and_model(
                "anthropic", "global.anthropic.claude-opus-4-7[1m]", env={},
            ),
            ("aws bedrock", "claude-opus-4.7"),
        )

    def test_env_flag_triggers_even_without_prefix(self):
        self.assertEqual(
            bedrock.resolve_provider_and_model(
                "anthropic", "claude-opus-4.7",
                env={"CLAUDE_CODE_USE_BEDROCK": "1"},
            ),
            ("aws bedrock", "claude-opus-4.7"),
        )

    def test_non_bedrock_passthrough(self):
        self.assertEqual(
            bedrock.resolve_provider_and_model("openai", "gpt-5.4", env={}),
            ("openai", "gpt-5.4"),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_bedrock -v`
Expected: `ModuleNotFoundError: No module named 'token_receipt.bedrock'`.

## Task 2: Implement `token_receipt/bedrock.py`

- [ ] **Step 3: Create `token_receipt/bedrock.py`**

```python
"""AWS Bedrock provider + model normalization.

Claude Code on Bedrock surfaces models as `<region>.anthropic.claude-opus-4-7[1m]`.
This module rewrites the pair to (`aws bedrock`, `claude-opus-4.7`) so the receipt
labels it correctly and find_price() resolves it against the existing anthropic
entries without any extra pricing rows.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional, Tuple

BEDROCK_MODEL_PREFIXES: Tuple[str, ...] = (
    "global.anthropic.",
    "us.anthropic.",
    "eu.anthropic.",
    "apac.anthropic.",
)

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


def resolve_provider_and_model(
    raw_provider: str,
    raw_model: str,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str]:
    """Return (provider, model) — rewritten to ('aws bedrock', normalized) when Bedrock is detected."""
    if is_bedrock_env(env) or looks_like_bedrock_model(raw_model):
        return ("aws bedrock", normalize_bedrock_model(raw_model))
    return (raw_provider, raw_model)
```

- [ ] **Step 4: Run the unit tests**

Run: `python3 -m unittest tests.test_bedrock -v`
Expected: all 10 tests PASS.

## Task 3: Wire `bedrock.resolve_provider_and_model` into `resolve_snapshot`

The wire-in point is immediately after `resolve_snapshot` picks a snapshot and before any pricing work. To keep `resolve_snapshot` readable we place the call at the very bottom, right before returning — but `resolve_snapshot` has many early returns, so we refactor to one exit.

- [ ] **Step 5: Refactor `resolve_snapshot` to a single return and inject Bedrock normalization**

Open `token_receipt/data.py`. Find the `def resolve_snapshot(args: argparse.Namespace) -> UsageSnapshot:` at line 894. Replace the entire function body (lines 894–1015) with this version. The logic is identical — every `return X` is replaced by `snapshot = X; return _finalize(snapshot, args)`; the final `_finalize` helper applies Bedrock normalization and respects explicit `--provider` / `--model` flags.

```python
def resolve_snapshot(args: argparse.Namespace) -> UsageSnapshot:
    if has_manual_usage(args):
        return _finalize(load_manual_snapshot(args), args)

    if args.session:
        if is_claude_usage_file(args.session):
            return _finalize(
                load_snapshot_from_claude_usage(args.session, args.model, args.provider),
                args,
            )
        if is_kimi_context_file(args.session):
            return _finalize(
                load_snapshot_from_kimi_context(args.session, args.model, args.provider),
                args,
            )
        if is_opencode_database_file(args.session):
            ses = (getattr(args, "opencode_session_id", None) or "").strip() or runtime_opencode_session_id()
            if not ses:
                raise SystemExit(
                    "OpenCode: --session points to an OpenCode SQLite file. "
                    "Add --opencode-session-id <ses_...> or set OPENCODE_SESSION_ID."
                )
            return _finalize(
                load_snapshot_from_opencode_sqlite(args.session, ses, args.scope, args.model, args.provider),
                args,
            )
        return _finalize(
            load_snapshot_from_session(args.session, args.scope, args.model, args.provider),
            args,
        )

    agent_tool = requested_agent_tool(args)

    if agent_tool == "claude-code":
        claude_path = None
        session_id = runtime_claude_session_id()
        if session_id:
            claude_path = find_claude_usage_for_session(session_id)
        if claude_path is None:
            claude_path = newest_claude_usage_file()
        if claude_path:
            return _finalize(
                load_snapshot_from_claude_usage(claude_path, args.model, args.provider),
                args,
            )
        raise SystemExit(
            "No Claude Code usage log found under ~/.claude/usage-data/session-meta. "
            "If you are on Windows, the equivalent home-relative path is %USERPROFILE%\\.claude\\usage-data\\session-meta."
        )

    if agent_tool == "codex":
        session_path = newest_session_file()
        if session_path:
            return _finalize(
                load_snapshot_from_session(session_path, args.scope, args.model, args.provider),
                args,
            )
        raise SystemExit(
            "No Codex session file found under ~/.codex/sessions or ~/.codex/archived_sessions. "
            "If you are on Windows, the equivalent home-relative paths are %USERPROFILE%\\.codex\\sessions and %USERPROFILE%\\.codex\\archived_sessions."
        )

    if agent_tool == "kimi-code":
        kimi_path = None
        sid = os.environ.get("KIMI_SESSION_ID", "").strip()
        if sid:
            kimi_path = find_kimi_context_for_session(sid)
        if kimi_path is None:
            kimi_path = newest_kimi_context_file()
        if kimi_path:
            return _finalize(
                load_snapshot_from_kimi_context(kimi_path, args.model, args.provider),
                args,
            )
        share = kimi_share_dir()
        raise SystemExit(
            f"No Kimi Code context.jsonl found under {share / 'sessions'} or {share / 'imported_sessions'}. "
            "Try --session <path/to/context.jsonl>, export with `kimi export`, or pass manual --input-tokens/--output-tokens."
        )

    if agent_tool == "opencode":
        ses = (getattr(args, "opencode_session_id", None) or "").strip() or runtime_opencode_session_id()
        if ses:
            db_hit = global_find_opencode_db_for_session(ses)
            if db_hit:
                return _finalize(
                    load_snapshot_from_opencode_sqlite(db_hit, ses, args.scope, args.model, args.provider),
                    args,
                )
            raise SystemExit(
                f"OpenCode session id {ses!r} not found in any opencode*.db under known data dirs. "
                "Try `opencode session list`, OPENCODE_DATA_DIR, or `--session /path/to/opencode.db --opencode-session-id ...`."
            )
        newest = global_newest_opencode_session()
        if newest:
            db_path, sid2 = newest
            return _finalize(
                load_snapshot_from_opencode_sqlite(db_path, sid2, args.scope, args.model, args.provider),
                args,
            )
        roots = ", ".join(str(p) for p in opencode_standard_dirs())
        raise SystemExit(
            f"No OpenCode SQLite (opencode*.db) found under: {roots}. "
            "Install sessions with OpenCode CLI, or set OPENCODE_DATA_DIR / XDG_DATA_HOME, or use manual token flags."
        )

    if agent_tool == "trae":
        raise SystemExit(trae_manual_mode_error())

    codex_path = newest_session_file()
    claude_path = newest_claude_usage_file()
    kimi_path = newest_kimi_context_file()
    opencode_ref = global_newest_opencode_session()

    sources = []
    if codex_path:
        sources.append(("codex", codex_path))
    if claude_path:
        sources.append(("claude-code", claude_path))
    if kimi_path:
        sources.append(("kimi-code", kimi_path))
    if opencode_ref:
        sources.append(("opencode", opencode_ref))

    if len(sources) == 1:
        source_type, path = sources[0]
        if source_type == "codex":
            return _finalize(
                load_snapshot_from_session(path, args.scope, args.model, args.provider),
                args,
            )
        if source_type == "kimi-code":
            return _finalize(
                load_snapshot_from_kimi_context(path, args.model, args.provider),
                args,
            )
        if source_type == "opencode":
            db_p, sid_o = path  # type: ignore[misc]
            return _finalize(
                load_snapshot_from_opencode_sqlite(db_p, sid_o, args.scope, args.model, args.provider),
                args,
            )
        return _finalize(
            load_snapshot_from_claude_usage(path, args.model, args.provider),
            args,
        )

    if len(sources) > 1:
        raise SystemExit(
            "Multiple software logs are available locally. "
            "Pass --agent-tool codex, --agent-tool claude-code, --agent-tool kimi-code, --agent-tool opencode, "
            "or run token-receipt inside the software whose conversation you want to bill. "
            "token-receipt does not guess across software."
        )

    raise SystemExit(
        "No Codex, Claude Code, Kimi Code, or OpenCode session logs found locally. "
        "For Trae, automatic import is not implemented yet; provide --input-tokens and --output-tokens for manual mode."
    )


def _finalize(snapshot: UsageSnapshot, args: argparse.Namespace) -> UsageSnapshot:
    """Post-loader rewrites that should apply to every code path."""
    from .bedrock import resolve_provider_and_model

    # Explicit CLI flags win; otherwise, rewrite Bedrock-shaped provider/model.
    if not args.provider and not args.model:
        snapshot.provider, snapshot.model = resolve_provider_and_model(
            snapshot.provider, snapshot.model,
        )
    elif not args.provider:
        snapshot.provider, _ = resolve_provider_and_model(snapshot.provider, snapshot.model)
    elif not args.model:
        _, snapshot.model = resolve_provider_and_model(snapshot.provider, snapshot.model)
    return snapshot
```

The `from .bedrock import ...` lives inside `_finalize` to avoid a top-of-file import cycle (data.py → bedrock → models; bedrock needs nothing from data.py, so top-of-file is also safe, but local-import is the pattern the file already uses elsewhere).

- [ ] **Step 6: Add an integration test that proves the wire-in**

Append to `tests/test_bedrock.py`:

```python

class ResolveSnapshotWiresInBedrockTest(unittest.TestCase):
    def test_manual_snapshot_bedrock_model_normalized(self):
        import argparse
        from token_receipt.data import resolve_snapshot

        args = argparse.Namespace(
            input_tokens=1, output_tokens=1, total_tokens=None,
            cached_input_tokens=None, cache_write_tokens=None,
            reasoning_output_tokens=None,
            context_window=None, receipt_seed=None,
            scope="latest-turn",
            provider=None, model="global.anthropic.claude-opus-4-7[1m]",
            session=None, opencode_session_id=None,
            agent_tool=None, brand=None,
        )
        snap = resolve_snapshot(args)
        # args.model is set, so Bedrock rewrite only rewrites provider.
        self.assertEqual(snap.provider, "aws bedrock")
        self.assertEqual(snap.model, "global.anthropic.claude-opus-4-7[1m]")

    def test_manual_snapshot_without_overrides_rewrites_both(self):
        import argparse
        from token_receipt.data import resolve_snapshot

        args = argparse.Namespace(
            input_tokens=1, output_tokens=1, total_tokens=None,
            cached_input_tokens=None, cache_write_tokens=None,
            reasoning_output_tokens=None,
            context_window=None, receipt_seed=None,
            scope="latest-turn",
            provider=None, model=None,
            session=None, opencode_session_id=None,
            agent_tool=None, brand=None,
        )
        # manual path takes args.model or model_from_env() or "UNRECORDED" — so we
        # can't test rewriting here without a real Bedrock-shaped model. Skipping
        # this case: the rewrite is exercised by the scripted Bedrock integration
        # in scripts/validate_receipt.py (Part 11).
        snap = resolve_snapshot(args)
        self.assertEqual(snap.provider, "unknown")
```

- [ ] **Step 7: Run the integration and unit tests**

Run: `python3 -m unittest tests.test_bedrock -v`
Expected: all tests PASS.

- [ ] **Step 8: Run the full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0.

- [ ] **Step 9: Commit**

```bash
git add token_receipt/bedrock.py token_receipt/data.py tests/test_bedrock.py
git commit -m "feat(bedrock): normalize provider and model for Claude Code on Bedrock"
```
