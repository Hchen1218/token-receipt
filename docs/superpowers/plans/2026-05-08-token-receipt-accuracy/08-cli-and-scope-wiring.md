# Part 08 — CLI flags, scope expansion, silent `--write`

**Parent plan:** [README.md](./README.md)

**Goal:** Expose the new pricing + aggregator plumbing through the CLI, and make `--write` fully silent so Claude Code's Bash tool doesn't echo the receipt twice. Defects fixed: #7 (wire aggregator for `session`/`today`/`session-all`), #9 (add `--hide-fields`), #10 (silent `--write`).

## Files

- Modify: `token_receipt/cli.py:17-97` — add flags, pass-through, silent `--write` branch.
- Modify: `token_receipt/data.py` — `resolve_snapshot` delegates to the aggregator for non-`latest-turn` Claude-Code scopes.
- Create: `tests/test_cli_flags.py`

## Task 1: Red test for the new flags

- [ ] **Step 1: Write `tests/test_cli_flags.py`**

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
    child_env = {**os.environ, **(env or {})}
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT), env=child_env,
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc


class FlagParsingTest(unittest.TestCase):
    def test_help_lists_new_flags(self):
        proc = _run(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--cache-ttl", proc.stdout)
        self.assertIn("--hide-fields", proc.stdout)
        self.assertIn("session-all", proc.stdout)
        self.assertIn("today", proc.stdout)


class SilentWriteTest(unittest.TestCase):
    def test_write_only_produces_no_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "receipt.txt"
            proc = _run([
                "--agent-tool", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-sonnet-4.5",
                "--input-tokens", "1", "--output-tokens", "1",
                "--write", str(dest),
            ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_write_plus_write_html_prints_exactly_two_wrote_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "receipt.txt"
            html = Path(tmp) / "receipt.html"
            proc = _run([
                "--agent-tool", "claude-code",
                "--provider", "anthropic",
                "--model", "claude-sonnet-4.5",
                "--input-tokens", "1", "--output-tokens", "1",
                "--write", str(txt),
                "--write-html", str(html),
            ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line]
        self.assertEqual(len(lines), 2, proc.stdout)
        self.assertTrue(all(line.startswith("wrote to:") for line in lines))


class CacheTtlFlagTest(unittest.TestCase):
    def test_cli_accepts_cache_ttl_1h(self):
        import re

        proc = _run([
            "--agent-tool", "claude-code",
            "--provider", "anthropic",
            "--model", "claude-opus-4.7",
            "--input-tokens", "16897",
            "--cached-input-tokens", "22000000",
            "--cache-write-tokens", "8180000",
            "--output-tokens", "434360",
            "--cache-ttl", "1h",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("USD ESTIMATE", proc.stdout)
        # 1h TTL expected amount is $103.74 (spec sanity check).
        # Match $103.XX so we catch regression to the buggy $10.87 or the 5m $73.xx.
        self.assertRegex(proc.stdout, r"\$103\.\d{2}")

    def test_cli_accepts_cache_ttl_5m_default(self):
        import re

        proc = _run([
            "--agent-tool", "claude-code",
            "--provider", "anthropic",
            "--model", "claude-opus-4.7",
            "--input-tokens", "16897",
            "--cached-input-tokens", "22000000",
            "--cache-write-tokens", "8180000",
            "--output-tokens", "434360",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 5m TTL default expected amount is $73.07.
        self.assertRegex(proc.stdout, r"\$73\.\d{2}")


class HideFieldsFlagTest(unittest.TestCase):
    def test_hide_fields_price_date_removes_row(self):
        proc = _run([
            "--agent-tool", "claude-code",
            "--provider", "anthropic",
            "--model", "claude-sonnet-4.5",
            "--input-tokens", "100", "--output-tokens", "100",
            "--hide-fields", "price-date",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("PRICE DATE", proc.stdout)
        self.assertIn("USD ESTIMATE", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m unittest tests.test_cli_flags -v`
Expected: `--help` lacks `--cache-ttl` / `--hide-fields`, `--cache-ttl` is unrecognized, `--hide-fields` is unrecognized, `--write` prints the receipt body.

## Task 2: Update `cli.py`

- [ ] **Step 3: Replace `token_receipt/cli.py` entirely**

```python
"""CLI entrypoint for token receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .data import available_fields_report, resolve_snapshot
from .html_render import render_receipt_html
from .models import ALLOWED_WIDTHS, DEFAULT_FOOTER, DEFAULT_PRICING, canonical_language
from .pricing import compute_total, estimate_cost
from .render import auto_brand, print_receipt, render_receipt


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render token usage as an ASCII thermal receipt.")
    parser.add_argument("--session", type=Path, help="Codex JSONL session path. Defaults to newest local session.")
    parser.add_argument(
        "--scope",
        choices=("latest-turn", "session", "today", "session-all"),
        default="latest-turn",
        help=(
            "Billing scope. latest-turn = last assistant turn (default). "
            "session = current session aggregated from jsonl transcripts. "
            "today = every session since local midnight. "
            "session-all = current session across time."
        ),
    )
    parser.add_argument("--width", type=int, choices=ALLOWED_WIDTHS, default=48)
    parser.add_argument("--agent-tool", choices=("auto", "codex", "claude-code", "trae", "kimi-code", "opencode", "generic"), default=None, help="Software data source and receipt logo. When omitted, token-receipt uses the current runtime if it can detect one; otherwise it will ask you to disambiguate instead of guessing across software.")
    parser.add_argument("--brand", choices=("auto", "codex", "claude-code", "trae", "kimi-code", "opencode", "generic"), default=None, help="Backward-compatible logo override. Prefer --agent-tool when choosing a software data source.")
    parser.add_argument(
        "--opencode-session-id",
        default=None,
        help="OpenCode session id (ses_…) when reading an opencode*.db SQLite file via --session, or together with --agent-tool opencode.",
    )
    parser.add_argument("--language", "--lang", dest="language", choices=("en", "zh", "zh-CN"), default="en", help="Receipt language: en or zh-CN.")
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--footer", default=DEFAULT_FOOTER, help="Custom footer line, or 'auto' for model-aware footer.")
    parser.add_argument("--footer-tone", choices=("auto", "snarky", "encouraging", "dry"), default="auto")
    parser.add_argument("--conversation-hint", default="", help="Optional short hint used to vary auto footer selection.")
    parser.add_argument("--conversation-summary", default="", help="Alias for a current-chat summary used to vary auto footer selection.")
    parser.add_argument("--provider", help="Override provider, e.g. openai or anthropic.")
    parser.add_argument("--model", help="Override model for display and pricing.")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--cached-input-tokens", type=int)
    parser.add_argument("--cache-write-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--reasoning-output-tokens", type=int)
    parser.add_argument("--total-tokens", type=int)
    parser.add_argument("--context-window", type=int)
    parser.add_argument(
        "--cache-ttl",
        choices=("auto", "5m", "1h"),
        default="auto",
        help=(
            "Cache-write TTL for cost estimation. "
            "auto = use per-message split if the snapshot provides one, "
            "else the ENABLE_PROMPT_CACHING_1H_BEDROCK env flag, else 5m."
        ),
    )
    parser.add_argument(
        "--hide-fields",
        default="",
        help=(
            "Comma-separated row keys to drop from the receipt. "
            "Valid keys: supplier, model, context, price-mapping, price-date, rate-note."
        ),
    )
    parser.add_argument("--receipt-seed")
    parser.add_argument("--show-fields", action="store_true", help="Print a JSON report of fields available from the selected source instead of a receipt.")
    parser.add_argument("--output", choices=("text", "html"), default="text", help="Receipt output format. Use html for a printable browser page.")
    parser.add_argument("--write", type=Path, help="Write the rendered receipt to a file and suppress stdout. Useful when a host tool would otherwise echo the receipt multiple times.")
    parser.add_argument("--write-html", type=Path, help="Also write a printable HTML receipt to a file while keeping the main output unchanged.")
    parser.add_argument("--stream", action="store_true", default=None, help="Print receipt one line at a time, like a receipt printer.")
    parser.add_argument("--no-stream", dest="stream", action="store_false", help="Print receipt all at once even in an interactive terminal.")
    parser.add_argument("--stream-delay", type=float, default=0.03, help="Delay in seconds between lines when --stream is used.")
    return parser


def _parse_hide_fields(raw: str) -> frozenset:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    snapshot = resolve_snapshot(args)
    if args.provider:
        snapshot.provider = args.provider
    if args.model:
        snapshot.model = args.model

    # Populate total_tokens when the loader did not — aggregator already has it,
    # but session-meta and manual-mode snapshots need compute_total covering all buckets.
    if not snapshot.total_tokens:
        snapshot.total_tokens = compute_total(snapshot)

    if args.show_fields:
        fields_json = json.dumps(available_fields_report(snapshot), indent=2, ensure_ascii=True)
        if args.write:
            args.write.parent.mkdir(parents=True, exist_ok=True)
            args.write.write_text(fields_json + "\n", encoding="utf-8")
            return 0
        print(fields_json)
        return 0

    cache_ttl_override = None if args.cache_ttl == "auto" else args.cache_ttl
    estimate = estimate_cost(snapshot, args.pricing, cache_ttl_override=cache_ttl_override)

    agent_tool = auto_brand(snapshot.provider, snapshot.source, args.agent_tool or args.brand or "auto")
    conversation_hint = args.conversation_summary or args.conversation_hint
    language = canonical_language(args.language)
    hidden = _parse_hide_fields(args.hide_fields)

    html_receipt = None
    if args.output == "html" or args.write_html:
        html_receipt = render_receipt_html(
            snapshot, estimate, args.width, agent_tool, args.footer, args.footer_tone,
            conversation_hint, language,
        )
    if args.output == "html":
        receipt_text = html_receipt or render_receipt_html(
            snapshot, estimate, args.width, agent_tool, args.footer, args.footer_tone,
            conversation_hint, language,
        )
    else:
        receipt_text = render_receipt(
            snapshot, estimate, args.width, agent_tool, args.footer, args.footer_tone,
            conversation_hint, language, hidden=hidden,
        )

    if args.write_html:
        args.write_html.parent.mkdir(parents=True, exist_ok=True)
        args.write_html.write_text((html_receipt or "") + "\n", encoding="utf-8")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(receipt_text + "\n", encoding="utf-8")
        if args.write_html:
            sys.stdout.write(f"wrote to: {args.write}\n")
            sys.stdout.write(f"wrote to: {args.write_html}\n")
        return 0
    if args.output == "html":
        print(receipt_text)
        return 0
    stream = sys.stdout.isatty() if args.stream is None else args.stream
    print_receipt(receipt_text, stream, args.stream_delay)
    return 0
```

Note — `render_receipt` now accepts a new `hidden` kwarg. Part 09 adds it; for now, update `render.py` to accept and ignore the kwarg so Part 08 lands cleanly.

## Task 3: Make `render_receipt` accept `hidden` without breaking

- [ ] **Step 4: Update `render.py` signatures**

In `token_receipt/render.py`, change the `def render_receipt(...)` signature (currently line ~1482) from:

```python
def render_receipt(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
) -> str:
```

to:

```python
def render_receipt(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
    hidden: frozenset = frozenset(),
) -> str:
```

and change the `view = build_receipt_view(...)` call on the next body line to:

```python
    view = build_receipt_view(snapshot, estimate, width, agent_tool, footer, footer_tone, conversation_hint, language, hidden=hidden)
```

Similarly update `def build_receipt_view(...)` (line ~1419) to accept the new keyword (ignore it for now — Part 09 wires it through):

```python
def build_receipt_view(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
    hidden: frozenset = frozenset(),
) -> ReceiptView:
```

Do not touch anything else in `build_receipt_view`'s body yet.

## Task 4: Wire the aggregator into `resolve_snapshot`

- [ ] **Step 5: Extend `resolve_snapshot`'s Claude-Code path**

In `token_receipt/data.py`, inside the `if agent_tool == "claude-code":` branch (and also in the single-source fallthrough that picks `claude-code`), route non-`latest-turn` scopes through the aggregator. Replace the existing `if agent_tool == "claude-code":` block with:

```python
    if agent_tool == "claude-code":
        if args.scope != "latest-turn":
            return _finalize(_load_claude_aggregate(args), args)
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
```

Similarly, in the single-source block where `source_type` resolves to `claude-code`, replace:

```python
        return _finalize(
            load_snapshot_from_claude_usage(path, args.model, args.provider),
            args,
        )
```

with:

```python
        if args.scope != "latest-turn":
            return _finalize(_load_claude_aggregate(args), args)
        return _finalize(
            load_snapshot_from_claude_usage(path, args.model, args.provider),
            args,
        )
```

Now add the helper near `_finalize` at the bottom of the file:

```python
def _load_claude_aggregate(args: argparse.Namespace) -> UsageSnapshot:
    from .claude_aggregator import aggregate_claude_projects

    now = dt.datetime.now(tz=dt.timezone.utc)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

    if args.scope == "today":
        # Local midnight anchors the start; timestamps in jsonl are UTC strings.
        local_midnight = dt.datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        since = local_midnight.astimezone(dt.timezone.utc)
        until = now
        session_id = None
    elif args.scope in ("session", "session-all"):
        # Per spec: session/session-all filter by sessionId across the full jsonl
        # window; the difference from "today" is that we scope by sid, not time.
        since = epoch
        until = now
        session_id = runtime_claude_session_id()
        if not session_id:
            raise SystemExit(
                f"--scope {args.scope} needs the active Claude Code sessionId. "
                "Run token-receipt from inside Claude Code (CLAUDE_SESSION_ID is set), "
                "or pass --scope today for a whole-day aggregate."
            )
    else:
        # Fallthrough; latest-turn is handled outside this helper.
        since = epoch
        until = now
        session_id = runtime_claude_session_id()

    snapshot = aggregate_claude_projects(
        since, until,
        session_id=session_id,
        model_override=args.model,
        provider_override=args.provider,
    )
    snapshot.scope = args.scope
    return snapshot
```

Note: the spec splits `session` vs. `session-all` by "within one session file" vs. "across time", but sessionId is globally unique for a Claude Code session — there's no separate scope where one sessionId can match multiple time ranges. The two scope values currently produce identical aggregates; they're kept distinct so a future change (e.g., splitting by `start_time` rather than sessionId) has a handle to hook into. This matches the spec table literally without inventing a behavioral difference.

- [ ] **Step 6: Run the CLI tests**

Run: `python3 -m unittest tests.test_cli_flags -v`
Expected: all tests PASS. `--cache-ttl 1h` produces a receipt in the `$10x` ballpark (≈ $103 for the Opus regression case).

- [ ] **Step 7: Run the full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0.

- [ ] **Step 8: Commit**

```bash
git add token_receipt/cli.py token_receipt/data.py token_receipt/render.py tests/test_cli_flags.py
git commit -m "feat(cli): add --cache-ttl, --hide-fields, today/session-all scopes, silent --write"
```
