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
from typing import Any, Dict, Iterator, Optional, Tuple

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
