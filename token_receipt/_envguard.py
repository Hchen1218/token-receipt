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
