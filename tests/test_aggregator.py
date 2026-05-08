"""Claude projects aggregator: time/session filtering, sidechain dedup, ephemeral split."""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from token_receipt.claude_aggregator import (
    aggregate_claude_projects,
    extract_usage,
    iter_lines,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude_projects"


class ExtractUsageTest(unittest.TestCase):
    def test_assistant_line_extracted(self):
        line = {
            "type": "assistant",
            "sessionId": "sess-1",
            "uuid": "a1",
            "timestamp": "2026-05-07T10:00:01.000Z",
            "isSidechain": False,
            "message": {
                "id": "msg_A1",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 2000,
                    "cache_creation_input_tokens": 500,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 500,
                        "ephemeral_1h_input_tokens": 0,
                    },
                    "output_tokens": 40,
                },
            },
        }
        record = extract_usage(line)
        self.assertEqual(record["input_tokens"], 100)
        self.assertEqual(record["cached_input_tokens"], 2000)
        self.assertEqual(record["cache_write_tokens"], 500)
        self.assertEqual(record["cache_write_5m_tokens"], 500)
        self.assertEqual(record["cache_write_1h_tokens"], 0)
        self.assertEqual(record["output_tokens"], 40)
        self.assertEqual(record["model"], "claude-opus-4-7")
        self.assertEqual(record["message_id"], "msg_A1")

    def test_non_assistant_returns_none(self):
        self.assertIsNone(extract_usage({"type": "user", "message": {"content": "hi"}}))

    def test_sidechain_returns_none(self):
        self.assertIsNone(extract_usage({"type": "assistant", "isSidechain": True, "message": {}}))


class IterLinesTest(unittest.TestCase):
    def test_skips_malformed_json_silently(self):
        path = FIXTURES / "proj-b" / "sess-bad.jsonl"
        lines = list(iter_lines(path))
        # 2 valid lines, 1 malformed line skipped.
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["message"]["id"], "msg_X1")
        self.assertEqual(lines[1]["message"]["id"], "msg_X2")


class AggregateClaudeProjectsTest(unittest.TestCase):
    def test_session_filter_dedupes_and_splits_ttl(self):
        since = dt.datetime(2026, 5, 7, 0, 0, tzinfo=dt.timezone.utc)
        until = dt.datetime(2026, 5, 7, 23, 59, tzinfo=dt.timezone.utc)
        snap = aggregate_claude_projects(
            since, until,
            session_id="sess-1",
            projects_root=FIXTURES,
        )
        # msg_A1 + msg_A2. msg_A2-dup is deduped. msg_SIDE is sidechain -> dropped.
        self.assertEqual(snap.input_tokens, 150)
        self.assertEqual(snap.cached_input_tokens, 2000)
        self.assertEqual(snap.cache_write_tokens, 1500)
        self.assertEqual(snap.cache_write_5m_tokens, 500)
        self.assertEqual(snap.cache_write_1h_tokens, 1000)
        self.assertEqual(snap.output_tokens, 60)
        self.assertEqual(snap.aggregation_source, "projects-jsonl")
        self.assertEqual(snap.deduped_message_ids, 1)  # msg_A2-dup
        self.assertEqual(snap.model, "claude-opus-4-7")

    def test_time_filter_only_today(self):
        # "today" style window: only include 2026-05-08 lines.
        since = dt.datetime(2026, 5, 8, 0, 0, tzinfo=dt.timezone.utc)
        until = dt.datetime(2026, 5, 8, 23, 59, tzinfo=dt.timezone.utc)
        snap = aggregate_claude_projects(since, until, projects_root=FIXTURES)
        # Only msg_B2 qualifies.
        self.assertEqual(snap.input_tokens, 20)
        self.assertEqual(snap.output_tokens, 10)
        self.assertEqual(snap.deduped_message_ids, 0)
        self.assertEqual(snap.model, "claude-sonnet-4-6")

    def test_fallback_key_when_message_id_missing(self):
        since = dt.datetime(2026, 5, 7, 0, 0, tzinfo=dt.timezone.utc)
        until = dt.datetime(2026, 5, 7, 23, 59, tzinfo=dt.timezone.utc)
        snap = aggregate_claude_projects(
            since, until,
            session_id="sess-3",
            projects_root=FIXTURES,
        )
        # Both lines share (sessionId, uuid)="sess-3","c1" -> deduped.
        self.assertEqual(snap.input_tokens, 7)
        self.assertEqual(snap.output_tokens, 3)
        self.assertEqual(snap.deduped_message_ids, 1)

    def test_session_id_with_no_matches_returns_empty_snapshot(self):
        since = dt.datetime(2026, 5, 7, 0, 0, tzinfo=dt.timezone.utc)
        until = dt.datetime(2026, 5, 7, 23, 59, tzinfo=dt.timezone.utc)
        snap = aggregate_claude_projects(
            since, until,
            session_id="does-not-exist",
            projects_root=FIXTURES,
        )
        self.assertEqual(snap.input_tokens, 0)
        self.assertEqual(snap.output_tokens, 0)
        self.assertEqual(snap.total_tokens, 0)
        self.assertEqual(snap.aggregation_source, "projects-jsonl")


if __name__ == "__main__":
    unittest.main()
