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
