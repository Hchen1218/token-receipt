"""Runtime detection and manual snapshot tests."""

from __future__ import annotations

import argparse
import unittest

from token_receipt.data import load_manual_snapshot, runtime_claude_session_id


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_tokens": 100,
        "cached_input_tokens": 2000,
        "cache_write_tokens": 500,
        "output_tokens": 40,
        "reasoning_output_tokens": 12,
        "total_tokens": None,
        "context_window": None,
        "provider": "anthropic",
        "model": "claude-opus-4.7",
        "receipt_seed": None,
        "scope": "latest-turn",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class ClaudeSessionIdTest(unittest.TestCase):
    def test_prefers_claude_code_session_id(self) -> None:
        env = {
            "CLAUDE_CODE_SESSION_ID": " code-session ",
            "CLAUDE_SESSION_ID": " legacy-session ",
        }
        self.assertEqual(runtime_claude_session_id(env), "code-session")

    def test_falls_back_to_legacy_session_id(self) -> None:
        self.assertEqual(runtime_claude_session_id({"CLAUDE_SESSION_ID": " legacy-session "}), "legacy-session")


class ManualSnapshotTest(unittest.TestCase):
    def test_omits_total_field_when_user_did_not_pass_total(self) -> None:
        snapshot = load_manual_snapshot(make_args())
        self.assertEqual(snapshot.total_tokens, 0)
        self.assertNotIn("total_tokens", snapshot.available_fields)

    def test_keeps_total_field_when_user_passes_total(self) -> None:
        snapshot = load_manual_snapshot(make_args(total_tokens=9999))
        self.assertEqual(snapshot.total_tokens, 9999)
        self.assertIn("total_tokens", snapshot.available_fields)


if __name__ == "__main__":
    unittest.main()
