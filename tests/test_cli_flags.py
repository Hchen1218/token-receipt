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
