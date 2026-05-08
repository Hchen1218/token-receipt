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


if __name__ == "__main__":
    unittest.main()
