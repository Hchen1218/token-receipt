# Part 07 — Claude-projects aggregator with dedup + TTL split

**Parent plan:** [README.md](./README.md)

**Goal:** Build the module that walks `~/.claude/projects/**/*.jsonl`, filters by time window and/or session id, dedups sidechain/subagent branches and duplicate `message.id` lines, and extracts the `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` split. This module doesn't touch CLI yet — Part 08 wires it into `resolve_snapshot`.

Defects fixed: #7, #8.

## Files

- Create: `token_receipt/claude_aggregator.py`
- Create: `tests/test_aggregator.py`
- Create: `tests/fixtures/claude_projects/` — fixture jsonl files used by the tests.

## Shape of the input

Each `~/.claude/projects/<project>/<sessionId>.jsonl` line is a JSON object with at least these fields when `type == "assistant"`:

```json
{
  "type": "assistant",
  "sessionId": "7b...",
  "uuid": "msg-uuid",
  "timestamp": "2026-05-07T12:34:56.000Z",
  "isSidechain": false,
  "message": {
    "id": "msg_01ABC...",
    "model": "claude-opus-4-7",
    "usage": {
      "input_tokens": 100,
      "cache_read_input_tokens": 2000,
      "cache_creation_input_tokens": 500,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 500,
        "ephemeral_1h_input_tokens": 0
      },
      "output_tokens": 40
    }
  }
}
```

Non-`assistant` lines and `isSidechain == True` lines are ignored. Duplicate `message.id` → first wins.

## Task 1: Build fixture jsonl files

- [ ] **Step 1: Create fixture directory with three jsonl files**

Run: `mkdir -p tests/fixtures/claude_projects/proj-a tests/fixtures/claude_projects/proj-b`

Then write `tests/fixtures/claude_projects/proj-a/sess-1.jsonl` exactly as below (one JSON object per line, no trailing blank line). Use Write to create it.

```jsonl
{"type":"user","sessionId":"sess-1","uuid":"u1","timestamp":"2026-05-07T10:00:00.000Z","isSidechain":false,"message":{"role":"user","content":"hi"}}
{"type":"assistant","sessionId":"sess-1","uuid":"a1","timestamp":"2026-05-07T10:00:01.000Z","isSidechain":false,"message":{"id":"msg_A1","model":"claude-opus-4-7","usage":{"input_tokens":100,"cache_read_input_tokens":2000,"cache_creation_input_tokens":500,"cache_creation":{"ephemeral_5m_input_tokens":500,"ephemeral_1h_input_tokens":0},"output_tokens":40}}}
{"type":"assistant","sessionId":"sess-1","uuid":"a2","timestamp":"2026-05-07T10:00:02.000Z","isSidechain":false,"message":{"id":"msg_A2","model":"claude-opus-4-7","usage":{"input_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":1000,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":1000},"output_tokens":20}}}
{"type":"assistant","sessionId":"sess-1","uuid":"a2-dup","timestamp":"2026-05-07T10:00:03.000Z","isSidechain":false,"message":{"id":"msg_A2","model":"claude-opus-4-7","usage":{"input_tokens":999999,"output_tokens":999999}}}
{"type":"assistant","sessionId":"sess-1","uuid":"a3-side","timestamp":"2026-05-07T10:00:04.000Z","isSidechain":true,"message":{"id":"msg_SIDE","model":"claude-opus-4-7","usage":{"input_tokens":111,"output_tokens":222}}}
```

Then write `tests/fixtures/claude_projects/proj-b/sess-2.jsonl`:

```jsonl
{"type":"assistant","sessionId":"sess-2","uuid":"b1","timestamp":"2026-05-07T11:00:00.000Z","isSidechain":false,"message":{"id":"msg_B1","model":"claude-sonnet-4-6","usage":{"input_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":5}}}
{"type":"assistant","sessionId":"sess-2","uuid":"b2","timestamp":"2026-05-08T01:00:00.000Z","isSidechain":false,"message":{"id":"msg_B2","model":"claude-sonnet-4-6","usage":{"input_tokens":20,"output_tokens":10}}}
```

Then write `tests/fixtures/claude_projects/proj-b/sess-3.jsonl` (demonstrates missing `message.id` → falls back to `(sessionId, uuid)` key):

```jsonl
{"type":"assistant","sessionId":"sess-3","uuid":"c1","timestamp":"2026-05-07T12:00:00.000Z","isSidechain":false,"message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":7,"output_tokens":3}}}
{"type":"assistant","sessionId":"sess-3","uuid":"c1","timestamp":"2026-05-07T12:00:01.000Z","isSidechain":false,"message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":7,"output_tokens":3}}}
```

Also write one malformed-line fixture at `tests/fixtures/claude_projects/proj-b/sess-bad.jsonl`:

```jsonl
{"type":"assistant","sessionId":"sess-bad","uuid":"x1","timestamp":"2026-05-07T12:30:00.000Z","isSidechain":false,"message":{"id":"msg_X1","model":"claude-opus-4-7","usage":{"input_tokens":1,"output_tokens":1}}}
not valid json at all
{"type":"assistant","sessionId":"sess-bad","uuid":"x2","timestamp":"2026-05-07T12:30:02.000Z","isSidechain":false,"message":{"id":"msg_X2","model":"claude-opus-4-7","usage":{"input_tokens":2,"output_tokens":2}}}
```

Create `tests/fixtures/__init__.py` (empty) so subagent/IDE imports don't mis-treat it as not-a-package:

```python
```

## Task 2: Write failing unit tests for the aggregator

- [ ] **Step 2: Write `tests/test_aggregator.py`**

```python
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
        # msg_A1 + msg_A2. msg_A2-dup is deduped. msg_SIDE is sidechain → dropped.
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
        # Both lines share (sessionId, uuid)="sess-3","c1" → deduped.
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
```

- [ ] **Step 3: Run — expect failure**

Run: `python3 -m unittest tests.test_aggregator -v`
Expected: `ModuleNotFoundError: No module named 'token_receipt.claude_aggregator'`.

## Task 3: Implement the aggregator

- [ ] **Step 4: Create `token_receipt/claude_aggregator.py`**

```python
"""Aggregate Claude Code usage across ~/.claude/projects/**/*.jsonl.

Responsibility: given a time window and optional session id, walk every
project transcript, filter by sidechain + time + session, dedup on message.id,
and return one UsageSnapshot covering the whole window.

The aggregator is the authoritative source for scopes `session`, `today`,
and `session-all`. The `latest-turn` scope still uses session-meta elsewhere.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

from .models import UsageSnapshot, as_int, parse_iso
from .pricing import compute_total


def default_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def iter_transcripts(projects_root: Path) -> Iterator[Path]:
    if not projects_root.exists():
        return
    yield from projects_root.rglob("*.jsonl")


def iter_lines(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield parsed JSON objects from a jsonl file, skipping malformed lines silently."""
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                yield item


def extract_usage(line: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a flat usage dict for billable assistant lines, or None to skip."""
    if line.get("type") != "assistant":
        return None
    if line.get("isSidechain") is True:
        return None
    message = line.get("message") or {}
    if not isinstance(message, dict):
        return None
    usage = message.get("usage") or {}
    if not isinstance(usage, dict):
        return None
    ephemeral = usage.get("cache_creation") or {}
    if not isinstance(ephemeral, dict):
        ephemeral = {}
    return {
        "input_tokens": as_int(usage.get("input_tokens")),
        "cached_input_tokens": as_int(usage.get("cache_read_input_tokens")),
        "cache_write_tokens": as_int(usage.get("cache_creation_input_tokens")),
        "cache_write_5m_tokens": as_int(ephemeral.get("ephemeral_5m_input_tokens")),
        "cache_write_1h_tokens": as_int(ephemeral.get("ephemeral_1h_input_tokens")),
        "output_tokens": as_int(usage.get("output_tokens")),
        "model": message.get("model"),
        "message_id": message.get("id"),
        "timestamp": line.get("timestamp"),
        "session_id": line.get("sessionId"),
        "uuid": line.get("uuid"),
    }


def _dedup_key(record: Dict[str, Any]) -> Tuple[str, ...]:
    mid = record.get("message_id")
    if mid:
        return ("id", str(mid))
    return ("uuid", str(record.get("session_id") or ""), str(record.get("uuid") or ""))


def _within_window(
    record: Dict[str, Any],
    since: dt.datetime,
    until: dt.datetime,
) -> bool:
    stamp = parse_iso(record.get("timestamp"))
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return since <= stamp < until


def aggregate_claude_projects(
    since: dt.datetime,
    until: dt.datetime,
    *,
    session_id: Optional[str] = None,
    projects_root: Optional[Path] = None,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> UsageSnapshot:
    """Walk the projects tree and return one UsageSnapshot for the window."""
    root = projects_root or default_projects_root()

    kept: list[Dict[str, Any]] = []
    seen: set[Tuple[str, ...]] = set()
    duplicate_hits = 0

    for path in iter_transcripts(root):
        for line in iter_lines(path):
            record = extract_usage(line)
            if record is None:
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            if not _within_window(record, since, until):
                continue
            key = _dedup_key(record)
            if key in seen:
                duplicate_hits += 1
                continue
            seen.add(key)
            kept.append(record)

    # Sum all buckets.
    input_tokens = sum(r["input_tokens"] for r in kept)
    cached_input_tokens = sum(r["cached_input_tokens"] for r in kept)
    cache_write_tokens = sum(r["cache_write_tokens"] for r in kept)
    cache_write_5m = sum(r["cache_write_5m_tokens"] for r in kept)
    cache_write_1h = sum(r["cache_write_1h_tokens"] for r in kept)
    output_tokens = sum(r["output_tokens"] for r in kept)

    # Pick the most-common model name across kept records as the display value.
    model = model_override
    if not model:
        model_counts: Dict[str, int] = {}
        for r in kept:
            name = r.get("model") or ""
            if name:
                model_counts[name] = model_counts.get(name, 0) + 1
        if model_counts:
            model = max(model_counts.items(), key=lambda kv: kv[1])[0]
    model = model or "UNRECORDED"

    provider = provider_override or "anthropic"

    # Window-resolved timestamp: newest kept record's timestamp, or None.
    timestamp: Optional[str] = None
    if kept:
        timestamp = max((r.get("timestamp") or "" for r in kept))

    snapshot = UsageSnapshot(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_write_5m_tokens=cache_write_5m,
        cache_write_1h_tokens=cache_write_1h,
        output_tokens=output_tokens,
        provider=str(provider),
        model=str(model),
        source=str(root),
        session_id=session_id or "projects",
        timestamp=timestamp,
        scope="session",  # caller may overwrite with "today" or "session-all".
        available_fields=(
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "total_tokens",
        ),
        aggregation_source="projects-jsonl",
        deduped_message_ids=duplicate_hits,
    )
    snapshot.total_tokens = compute_total(snapshot)
    return snapshot
```

- [ ] **Step 5: Run the aggregator tests**

Run: `python3 -m unittest tests.test_aggregator -v`
Expected: all tests PASS.

- [ ] **Step 6: Run the full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0. The aggregator is not yet wired into `resolve_snapshot`, so validation behavior is unchanged.

- [ ] **Step 7: Commit**

```bash
git add token_receipt/claude_aggregator.py tests/fixtures tests/test_aggregator.py
git commit -m "feat(claude): add projects-jsonl aggregator with dedup and TTL split"
```
