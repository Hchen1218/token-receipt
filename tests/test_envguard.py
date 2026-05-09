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
