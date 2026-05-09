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
