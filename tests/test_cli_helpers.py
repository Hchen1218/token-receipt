"""CLI formatting and total-fallback tests."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from token_receipt.cli import format_chat_reply, main


class ChatReplyFormatTest(unittest.TestCase):
    def test_uses_file_uri_for_html_link(self) -> None:
        reply = format_chat_reply("receipt text", Path("/tmp/token-receipt.html"))
        self.assertIn(f"[Printable HTML]({Path('/tmp/token-receipt.html').resolve().as_uri()})", reply)

    def test_resolves_relative_paths_before_linking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            path = Path(tmp) / "receipt.html"
            relative = path.relative_to(Path(tmp))
            os.chdir(tmp)
            try:
                reply = format_chat_reply("receipt text", relative)
            finally:
                os.chdir(cwd)
            self.assertIn(path.resolve().as_uri(), reply)


class CliTotalFallbackTest(unittest.TestCase):
    def test_manual_mode_computes_total_from_all_buckets_when_not_provided(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--provider",
                    "anthropic",
                    "--agent-tool",
                    "claude-code",
                    "--model",
                    "claude-opus-4.7",
                    "--input-tokens",
                    "100",
                    "--cached-input-tokens",
                    "2000",
                    "--cache-write-tokens",
                    "500",
                    "--output-tokens",
                    "40",
                    "--reasoning-output-tokens",
                    "12",
                    "--no-stream",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("2,652 TOKENS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
