"""Data loading and pricing for token receipt."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .models import (
    COMMON_TOKEN_FIELDS,
    OPTIONAL_TOKEN_FIELDS,
    RECEIPT_TOKEN_FIELDS,
    PriceEstimate,
    UsageSnapshot,
    as_int,
    normalize,
)
from .pricing import estimate_cost, find_price, load_pricing  # re-export; moved in Part 02


def iter_session_files() -> Iterable[Path]:
    home = Path.home()
    roots = [
        home / ".codex" / "sessions",
        home / ".codex" / "archived_sessions",
    ]
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("*.jsonl")


def newest_session_file() -> Optional[Path]:
    files = list(iter_session_files())
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def find_codex_session_for_thread(thread_id: str) -> Optional[Path]:
    if not thread_id:
        return None
    matches: list[Path] = []
    for root in (Path.home() / ".codex" / "sessions", Path.home() / ".codex" / "archived_sessions"):
        if not root.exists():
            continue
        matches.extend(root.rglob(f"*{thread_id}.jsonl"))
    if matches:
        return max(matches, key=lambda path: path.stat().st_mtime)
    for path in iter_session_files():
        try:
            with path.open("r", encoding="utf-8") as handle:
                first = handle.readline()
            item = json.loads(first)
        except (OSError, json.JSONDecodeError):
            continue
        payload = item.get("payload") or {}
        if item.get("type") == "session_meta" and str(payload.get("id") or "") == thread_id:
            return path
    return None


def iter_claude_usage_files() -> Iterable[Path]:
    home = Path.home()
    usage_dir = home / ".claude" / "usage-data" / "session-meta"
    if not usage_dir.exists():
        return
    yield from usage_dir.glob("*.json")


def _claude_usage_sort_key(path: Path) -> tuple:
    """Sort by mtime (1s granularity), then by start_time as tiebreaker.

    Files written in the same batch-sync often differ by sub-millisecond
    mtime but are semantically unordered.  Bucketing to whole seconds
    lets the start_time field break ties correctly.
    """
    mtime = int(path.stat().st_mtime)
    start_time = ""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        start_time = str(data.get("start_time", ""))
    except (json.JSONDecodeError, OSError):
        pass
    return (mtime, start_time)


def newest_claude_usage_file() -> Optional[Path]:
    files = list(iter_claude_usage_files())
    if not files:
        return None
    return max(files, key=_claude_usage_sort_key)


def find_claude_usage_for_session(session_id: str) -> Optional[Path]:
    usage_dir = Path.home() / ".claude" / "usage-data" / "session-meta"
    if not usage_dir.exists():
        return None
    exact = usage_dir / f"{session_id}.json"
    if exact.exists():
        return exact
    return None


def iter_claude_transcripts() -> Iterable[Path]:
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return
    yield from projects_dir.rglob("*.jsonl")


def find_claude_transcript_for_session(session_id: str) -> Optional[Path]:
    if not session_id:
        return None
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    matches = list(projects_dir.rglob(f"{session_id}.jsonl"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def maybe_model_from_claude_transcript(path: Optional[Path]) -> Optional[str]:
    if not path or not path.exists():
        return None
    model: Optional[str] = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = item.get("message") or {}
            if not isinstance(message, dict):
                continue
            value = message.get("model")
            if isinstance(value, str) and value.strip():
                model = value.strip()
    return model


def infer_provider_from_model(model: str) -> str:
    if not model or model == "UNRECORDED":
        return "unknown"
    model_lower = model.lower()
    if "claude" in model_lower:
        return "anthropic"
    if "gpt" in model_lower or model_lower.startswith("o"):
        return "openai"
    if "kimi" in model_lower:
        return "moonshot"
    if "gemini" in model_lower:
        return "google"
    if "deepseek" in model_lower:
        return "deepseek"
    if "minimax" in model_lower or model_lower.startswith("m"):
        return "minimax"
    if "glm" in model_lower:
        return "zhipu"
    if "qwen" in model_lower:
        return "alibaba"
    if "mimo" in model_lower:
        return "xiaomi"
    return "unknown"


def maybe_model_from_meta(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("model", "model_id", "model_name", "model_slug"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def maybe_model_from_turn_context(payload: Dict[str, Any]) -> Optional[str]:
    value = payload.get("model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def model_from_env() -> Optional[str]:
    for key in ("CODEX_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL", "KIMI_MODEL", "MOONSHOT_MODEL", "MODEL"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    return None


def kimi_share_dir(home: Optional[Path] = None) -> Path:
    explicit = (os.environ.get("KIMI_SHARE_DIR") or "").strip()
    if explicit:
        return Path(os.path.expandvars(os.path.expanduser(explicit)))
    return (home or Path.home()) / ".kimi"


def iter_kimi_context_files() -> Iterable[Path]:
    base = kimi_share_dir()
    sessions = base / "sessions"
    if sessions.is_dir():
        for work_hash in sessions.iterdir():
            if not work_hash.is_dir():
                continue
            for sess_dir in work_hash.iterdir():
                # 跳过 subagents/（子 Agent 会话单独存 context）
                if not sess_dir.is_dir() or sess_dir.name == "subagents":
                    continue
                cand = sess_dir / "context.jsonl"
                if cand.is_file():
                    yield cand
    imported = base / "imported_sessions"
    if imported.is_dir():
        for sess_dir in imported.iterdir():
            if not sess_dir.is_dir():
                continue
            cand = sess_dir / "context.jsonl"
            if cand.is_file():
                yield cand


def newest_kimi_context_file() -> Optional[Path]:
    files = [p for p in iter_kimi_context_files() if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def find_kimi_context_for_session(session_id: str) -> Optional[Path]:
    if not session_id.strip():
        return None
    base = kimi_share_dir()
    candidates: list[Path] = []
    for sub in ("sessions", "imported_sessions"):
        root = base / sub
        if not root.is_dir():
            continue
        if sub == "sessions":
            candidates.extend(root.rglob(f"{session_id}/context.jsonl"))
        else:
            exact = root / session_id / "context.jsonl"
            if exact.is_file():
                candidates.append(exact)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def kimi_config_default_model() -> Optional[str]:
    path = kimi_share_dir() / "config.toml"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line.lower().startswith("default_model"):
            continue
        if "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        mm = re.match(r'^"(.*)"$', value)
        if mm:
            return mm.group(1).strip() or None
        mm = re.match(r"^'(.*)'$", value)
        if mm:
            return mm.group(1).strip() or None
        return value.strip() or None
    return None


def scan_kimi_context_token_tally(path: Path) -> Optional[int]:
    last: Optional[int] = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict) or obj.get("role") != "_usage":
                    continue
                tc = obj.get("token_count")
                if isinstance(tc, int) and tc >= 0:
                    last = tc
    except OSError:
        return None
    return last


def load_snapshot_from_kimi_context(
    path: Path,
    model_override: Optional[str],
    provider_override: Optional[str],
) -> UsageSnapshot:
    tally = scan_kimi_context_token_tally(path)
    if tally is None:
        raise SystemExit(
            f"No valid Kimi `_usage` records (role `_usage` + integer `token_count`) found in {path}. "
            "If this file is not from Kimi Code CLI, pick a different --session."
        )

    session_id = path.parent.name
    model = model_override or model_from_env() or kimi_config_default_model() or "UNRECORDED"
    provider = provider_override or infer_provider_from_model(model)

    stamp = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat()

    return UsageSnapshot(
        input_tokens=0,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=tally,
        context_tokens=tally,
        context_window=None,
        provider=str(provider),
        model=str(model),
        source=str(path),
        session_id=session_id,
        timestamp=stamp,
        scope="session",
        available_fields=("total_tokens",),
        skip_price_estimate=True,
    )


def is_kimi_context_file(path: Path) -> bool:
    if path.name != "context.jsonl" or not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(400):
                line = handle.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                role = obj.get("role")
                if role == "_system_prompt":
                    return True
                if role == "_usage" and isinstance(obj.get("token_count"), int):
                    return True
    except OSError:
        return False
    return False


_OPENCODE_VENDOR_TO_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "moonshot": "moonshot",
    "deepseek": "deepseek",
    "zhipu": "zhipu",
    "glm": "zhipu",
    "bigmodel": "zhipu",
    "dashscope": "alibaba",
    "alibaba": "alibaba",
    "xiaomi": "xiaomi",
    "minimax": "minimax",
}


def billing_model_slug_from_opencode(model_id: str) -> str:
    mid = (model_id or "").strip()
    if not mid or mid.lower() == "unknown":
        return "UNRECORDED"
    if "/" in mid:
        tail = mid.split("/", 1)[1].strip()
        return tail or mid.replace("/", "_")
    return mid


def provider_and_slug_from_opencode_model(model_id_raw: str) -> tuple[str, str]:
    """Map OpenCode Models.dev ids (vendor/modelSlug) onto pricing lookup."""
    slug = billing_model_slug_from_opencode(model_id_raw)
    if "/" in model_id_raw:
        vendor = model_id_raw.split("/", 1)[0].strip().lower()
        prov = _OPENCODE_VENDOR_TO_PROVIDER.get(vendor)
        if prov:
            return prov, slug
    return infer_provider_from_model(slug), slug


def opencode_standard_dirs(home: Optional[Path] = None) -> list[Path]:
    """OpenCode SQLite 存放目录候选（对齐 CodeBurn opencode.ts getDataDir 思路 + Windows LOCALAPPDATA）。"""
    seen: Dict[str, Path] = {}

    def add(p: Path) -> None:
        key = str(p)
        if key not in seen:
            seen[key] = p

    root = home or Path.home()
    oe = os.environ.get("OPENCODE_DATA_DIR", "").strip()
    if oe:
        add(Path(os.path.expandvars(os.path.expanduser(oe))))
    xd = os.environ.get("XDG_DATA_HOME", "").strip()
    if xd:
        add(Path(os.path.expandvars(os.path.expanduser(xd))) / "opencode")
    add(root / ".local" / "share" / "opencode")
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA", "").strip()
        if la:
            add(Path(la) / "opencode")
    return list(seen.values())


def iter_opencode_db_files() -> Iterable[Path]:
    for d in opencode_standard_dirs():
        if not d.is_dir():
            continue
        try:
            for name in sorted(os.listdir(d)):
                if name.startswith("opencode") and name.endswith(".db"):
                    p = d / name
                    if p.is_file():
                        yield p
        except OSError:
            continue


def _opencode_db_has_session_message(conn: sqlite3.Connection) -> bool:
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('session', 'message')"
        ).fetchone()
        return bool(n and n[0] >= 2)
    except sqlite3.Error:
        return False


def _opencode_list_root_sessions(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """返回 (session_id, time_created) 根会话，优先跳过子会话与归档列（若不存在则降级查询）。"""
    queries = (
        "SELECT id, time_created FROM session WHERE time_archived IS NULL AND parent_id IS NULL ORDER BY time_created DESC",
        "SELECT id, time_created FROM session WHERE parent_id IS NULL ORDER BY time_created DESC",
        "SELECT id, time_created FROM session ORDER BY time_created DESC",
    )
    for sql in queries:
        try:
            rows = conn.execute(sql).fetchall()
            parsed: list[tuple[str, int]] = []
            for sid_raw, tc in rows:
                if isinstance(sid_raw, str) and sid_raw.strip():
                    parsed.append((sid_raw.strip(), as_int(tc)))
            return parsed
        except sqlite3.Error:
            continue
    return []


def find_opencode_session_in_db(db_path: Path, session_id: str) -> bool:
    if not db_path.is_file():
        return False
    try:
        conn = sqlite3.connect(str(db_path.resolve()), timeout=5.0)
    except sqlite3.Error:
        return False
    try:
        if not _opencode_db_has_session_message(conn):
            return False
        row = conn.execute(
            "SELECT 1 FROM session WHERE id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def global_newest_opencode_session() -> Optional[tuple[Path, str]]:
    best: Optional[tuple[Path, str, float]] = None
    for db_path in iter_opencode_db_files():
        try:
            conn = sqlite3.connect(str(db_path.resolve()), timeout=2.0)
        except sqlite3.Error:
            continue
        try:
            if not _opencode_db_has_session_message(conn):
                continue
            rows = _opencode_list_root_sessions(conn)
            if not rows:
                continue
            sid, tc = rows[0]
            # time_created：秒级或毫秒混用——与 CodeBurn 一致转成可排序 float
            tkey = float(tc) / 1000.0 if float(tc or 0) < 1e12 else float(tc)
            cand = (db_path, sid, tkey)
            if best is None or cand[2] > best[2]:
                best = cand
        finally:
            conn.close()
    if best is None:
        return None
    return best[0], best[1]


def global_find_opencode_db_for_session(session_id: str) -> Optional[Path]:
    for db_path in iter_opencode_db_files():
        if find_opencode_session_in_db(db_path, session_id):
            return db_path
    return None


def is_opencode_database_file(path: Path) -> bool:
    if not path.is_file():
        return False
    suf = path.suffix.lower()
    if suf != ".db":
        return False
    name_ok = path.name.startswith("opencode")
    low = path.name.lower()
    if not name_ok:
        path_slash = str(path.resolve()).replace("\\", "/").lower()
        name_ok = "opencode" in low and "/opencode/" in path_slash
    if not name_ok:
        return False
    try:
        conn = sqlite3.connect(str(path.resolve()), timeout=2.0)
    except sqlite3.Error:
        return False
    try:
        return _opencode_db_has_session_message(conn)
    finally:
        conn.close()


def _opencode_iso_from_tc(time_created_raw: Any) -> str:
    try:
        n = float(time_created_raw)
    except (TypeError, ValueError):
        return dt.datetime.now(dt.timezone.utc).isoformat()
    ms = n * 1000.0 if n < 1e12 else n
    return dt.datetime.fromtimestamp(ms / 1000.0, tz=dt.timezone.utc).isoformat()


def _assistant_tokens_from_payload(data: Dict[str, Any]) -> Optional[tuple[int, int, int, int, int]]:
    if data.get("role") != "assistant":
        return None
    raw_cost = data.get("cost")
    cost_ok = isinstance(raw_cost, (int, float)) and float(raw_cost) != 0.0
    t = data.get("tokens") or {}
    inp = as_int(t.get("input"))
    outp = as_int(t.get("output"))
    reasoning = as_int(t.get("reasoning"))
    cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
    cached_read = as_int(cache.get("read"))
    cache_write = as_int(cache.get("write"))
    if inp == outp == reasoning == cached_read == cache_write == 0 and not cost_ok:
        return None
    return (inp, cached_read, cache_write, outp, reasoning)


def load_snapshot_from_opencode_sqlite(
    db_path: Path,
    session_id: str,
    scope: str,
    model_override: Optional[str],
    provider_override: Optional[str],
) -> UsageSnapshot:
    try:
        conn = sqlite3.connect(str(db_path.resolve()), timeout=10.0)
    except sqlite3.Error as exc:
        raise SystemExit(f"Cannot open OpenCode database {db_path}: {exc}") from exc
    try:
        if not _opencode_db_has_session_message(conn):
            raise SystemExit(f"OpenCode DB schema mismatch (need session/message): {db_path}")
        try:
            rows = conn.execute(
                "SELECT time_created, data FROM message WHERE session_id = ? ORDER BY time_created ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SystemExit(f"OpenCode SQLite message read failed {db_path}: {exc}") from exc
    finally:
        conn.close()

    turns: list[tuple[Any, str, tuple[int, int, int, int, int]]] = []
    for time_created, raw in rows:
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        tup = _assistant_tokens_from_payload(payload)
        if tup is None:
            continue
        model_id_cell = payload.get("modelID")
        mid = model_id_cell.strip() if isinstance(model_id_cell, str) else ""
        turns.append((time_created, mid, tup))

    if not turns:
        raise SystemExit(
            f"No assistant rows with tokens/cost found in OpenCode DB for session={session_id!r}: {db_path}. "
            "Try `opencode session list`, set OPENCODE_SESSION_ID, or use --opencode-session-id."
        )

    if scope == "latest-turn":
        _, last_mid_raw, tup = turns[-1]
        last_mid = (last_mid_raw or "").strip()
        inp_s, cached_s, cw_s, outp_s, reas_s = tup
        last_ts_iso = _opencode_iso_from_tc(turns[-1][0])
        aggregated = tup
        model_pick_raw = model_override or last_mid
    else:
        sums = [0, 0, 0, 0, 0]
        for _, mid, tup in turns:
            for i, _v in enumerate(tup):
                sums[i] += tup[i]
        inp_s, cached_s, cw_s, outp_s, reas_s = sums[0], sums[1], sums[2], sums[3], sums[4]
        last_mid = (turns[-1][1] or "").strip()
        last_ts_iso = _opencode_iso_from_tc(turns[-1][0])
        aggregated = tuple(sums)
        model_pick_raw = model_override or last_mid

    raw_model_cell = ((model_pick_raw or "").strip()) or ""
    raw_model_final = raw_model_cell or model_from_env() or "UNRECORDED"
    vendor_provider, inferred_slug = provider_and_slug_from_opencode_model(raw_model_final)
    provider = provider_override or vendor_provider
    # 票面模型名优先用户覆盖；否则用 vendor/slug → 仅剩 slug（与定价表对齐）
    if model_override and model_override.strip():
        mo = model_override.strip()
        model_line = billing_model_slug_from_opencode(mo) if "/" in mo else mo
    elif raw_model_final == "UNRECORDED":
        model_line = "UNRECORDED"
    else:
        model_line = inferred_slug

    pricing_model = model_override.strip() if model_override and model_override.strip() else inferred_slug

    total_agg = aggregated[0] + aggregated[1] + aggregated[2] + aggregated[3] + aggregated[4]

    fields: list[str] = []
    if inp_s > 0:
        fields.append("input_tokens")
    if cached_s > 0:
        fields.append("cached_input_tokens")
    if cw_s > 0:
        fields.append("cache_write_tokens")
    if outp_s > 0:
        fields.append("output_tokens")
    if reas_s > 0:
        fields.append("reasoning_output_tokens")
    fields.append("total_tokens")
    avail = tuple(sorted(set(fields)))

    source_ref = f"{db_path}#{session_id}"
    return UsageSnapshot(
        input_tokens=inp_s,
        cached_input_tokens=cached_s,
        cache_write_tokens=cw_s,
        output_tokens=outp_s,
        reasoning_output_tokens=reas_s,
        total_tokens=total_agg,
        context_tokens=None,
        context_window=None,
        provider=str(provider),
        model=str(pricing_model if pricing_model and pricing_model != "UNRECORDED" else model_line),
        source=source_ref,
        session_id=session_id,
        timestamp=last_ts_iso,
        scope=scope,
        available_fields=avail,
        skip_price_estimate=False,
    )


def runtime_opencode_session_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    for key in ("OPENCODE_SESSION_ID",):
        val = runtime.get(key, "").strip()
        if val:
            return val
    return None


def load_snapshot_from_claude_usage(
    path: Path,
    model_override: Optional[str],
    provider_override: Optional[str],
    transcript_path: Optional[Path] = None,
) -> UsageSnapshot:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    session_id = str(data.get("session_id", path.stem))
    start_time = data.get("start_time")
    input_tokens = as_int(data.get("input_tokens"))
    output_tokens = as_int(data.get("output_tokens"))
    total_tokens = input_tokens + output_tokens
    available_fields = ["input_tokens", "output_tokens", "total_tokens"]

    transcript = transcript_path or find_claude_transcript_for_session(session_id)
    model = (
        model_override
        or maybe_model_from_claude_transcript(transcript)
        or model_from_env()
        or "UNRECORDED"
    )
    provider = provider_override or infer_provider_from_model(model)

    return UsageSnapshot(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=output_tokens,
        reasoning_output_tokens=0,
        total_tokens=total_tokens,
        context_window=None,
        provider=str(provider),
        model=str(model),
        source=str(path),
        session_id=session_id,
        timestamp=start_time,
        scope="session",
        available_fields=tuple(available_fields),
    )


def load_snapshot_from_session(path: Path, scope: str, model_override: Optional[str], provider_override: Optional[str]) -> UsageSnapshot:
    session_meta: Dict[str, Any] = {}
    token_event: Optional[Dict[str, Any]] = None
    token_timestamp: Optional[str] = None
    turn_context_model: Optional[str] = None

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_type = item.get("type")
            payload = item.get("payload") or {}
            if item_type == "session_meta" and isinstance(payload, dict):
                session_meta = payload
            if item_type == "turn_context" and isinstance(payload, dict):
                turn_context_model = maybe_model_from_turn_context(payload) or turn_context_model
            if item_type == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                token_event = payload
                token_timestamp = item.get("timestamp")

    if not token_event:
        raise SystemExit(f"No token_count event found in {path}")

    info = token_event.get("info") or {}
    usage_key = "total_token_usage" if scope == "session" else "last_token_usage"
    usage = info.get(usage_key) or {}
    available_fields = tuple(sorted(key for key in usage.keys() if isinstance(key, str)))
    provider = provider_override or session_meta.get("model_provider") or "unknown"
    model = (
        model_override
        or maybe_model_from_meta(session_meta)
        or turn_context_model
        or model_from_env()
        or "UNRECORDED"
    )
    session_id = str(session_meta.get("id") or path.stem)

    return UsageSnapshot(
        input_tokens=as_int(usage.get("input_tokens")),
        cached_input_tokens=as_int(usage.get("cached_input_tokens")),
        cache_write_tokens=as_int(usage.get("cache_write_tokens")),
        output_tokens=as_int(usage.get("output_tokens")),
        reasoning_output_tokens=as_int(usage.get("reasoning_output_tokens")),
        total_tokens=as_int(usage.get("total_tokens")),
        context_window=as_int(info.get("model_context_window")) or None,
        provider=str(provider),
        model=str(model),
        source=str(path),
        session_id=session_id,
        timestamp=token_timestamp or session_meta.get("timestamp"),
        scope=scope,
        available_fields=available_fields,
    )


def load_manual_snapshot(args: argparse.Namespace) -> UsageSnapshot:
    total = args.total_tokens
    if total is None:
        total = as_int(args.input_tokens) + as_int(args.output_tokens)
    available_fields = []
    if args.input_tokens is not None:
        available_fields.append("input_tokens")
    if args.output_tokens is not None:
        available_fields.append("output_tokens")
    if args.cached_input_tokens is not None:
        available_fields.append("cached_input_tokens")
    if args.cache_write_tokens is not None:
        available_fields.append("cache_write_tokens")
    if args.reasoning_output_tokens is not None:
        available_fields.append("reasoning_output_tokens")
    if total is not None:
        available_fields.append("total_tokens")

    return UsageSnapshot(
        input_tokens=as_int(args.input_tokens),
        cached_input_tokens=as_int(args.cached_input_tokens),
        cache_write_tokens=as_int(args.cache_write_tokens),
        output_tokens=as_int(args.output_tokens),
        reasoning_output_tokens=as_int(args.reasoning_output_tokens),
        total_tokens=as_int(total),
        context_window=as_int(args.context_window) or None,
        provider=args.provider or "unknown",
        model=args.model or model_from_env() or "UNRECORDED",
        source="manual",
        session_id=args.receipt_seed or "manual",
        timestamp=None,
        scope=args.scope,
        available_fields=tuple(sorted(set(available_fields))),
    )


def has_manual_usage(args: argparse.Namespace) -> bool:
    return args.input_tokens is not None or args.output_tokens is not None or args.total_tokens is not None


def is_claude_usage_file(path: Path) -> bool:
    if ".claude/usage-data/session-meta" in str(path):
        return True
    if path.suffix == ".json":
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if "session_id" in data and "input_tokens" in data and "output_tokens" in data:
                return True
        except (json.JSONDecodeError, OSError):
            pass
    return False


def trae_storage_hints() -> tuple[str, ...]:
    home = Path.home()
    return (
        str(home / "Library" / "Application Support" / "Trae" / "User" / "workspaceStorage"),
        str(home / "Library" / "Application Support" / "Trae" / "User" / "globalStorage"),
        str(home / "Library" / "Application Support" / "Trae CN" / "User" / "workspaceStorage"),
        str(home / "Library" / "Application Support" / "Trae CN" / "User" / "globalStorage"),
        r"%APPDATA%\Trae\User\workspaceStorage",
        r"%APPDATA%\Trae\User\globalStorage",
        r"%APPDATA%\Trae CN\User\workspaceStorage",
        r"%APPDATA%\Trae CN\User\globalStorage",
    )


def trae_manual_mode_error() -> str:
    hints = "\n".join(f"  - {path}" for path in trae_storage_hints())
    return (
        "Automatic Trae session import is not implemented yet.\n"
        "Trae stores chat state in app storage and workspace SQLite files rather than simple JSONL session logs.\n"
        "Known Trae storage locations include:\n"
        f"{hints}\n"
        "Use manual mode for now: provide --input-tokens and --output-tokens."
    )


def runtime_agent_tool(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    if runtime.get("CLAUDECODE"):
        return "claude-code"
    if any(runtime.get(key) for key in ("CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "CODEX_SHELL")):
        return "codex"
    if any(runtime.get(key) for key in ("TRAE_RUNTIME", "TRAE_IDE", "TRAE_SESSION_ID")):
        return "trae"
    # Kimi Code CLI / 宿主可注入，便于在非交互环境里自动选型
    if runtime.get("KIMI_SESSION_ID", "").strip() or runtime.get("KIMI_CODE", "").strip():
        return "kimi-code"
    if runtime_opencode_session_id(runtime):
        return "opencode"
    return None


def runtime_claude_session_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    for key in ("CLAUDE_SESSION_ID",):
        value = runtime.get(key)
        if value:
            return value.strip()
    return None


def runtime_codex_thread_id(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    runtime = env or os.environ
    value = runtime.get("CODEX_THREAD_ID")
    if value:
        return value.strip()
    return None


def requested_agent_tool(args: argparse.Namespace, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    explicit = getattr(args, "agent_tool", None)
    if explicit and explicit != "auto":
        return explicit

    brand = getattr(args, "brand", None)
    if brand in ("codex", "claude-code", "trae", "kimi-code", "opencode"):
        return brand

    return runtime_agent_tool(env)


def resolve_snapshot(args: argparse.Namespace) -> UsageSnapshot:
    if has_manual_usage(args):
        return _finalize(load_manual_snapshot(args), args)

    if args.session:
        if is_claude_usage_file(args.session):
            return _finalize(
                load_snapshot_from_claude_usage(args.session, args.model, args.provider),
                args,
            )
        if is_kimi_context_file(args.session):
            return _finalize(
                load_snapshot_from_kimi_context(args.session, args.model, args.provider),
                args,
            )
        if is_opencode_database_file(args.session):
            ses = (getattr(args, "opencode_session_id", None) or "").strip() or runtime_opencode_session_id()
            if not ses:
                raise SystemExit(
                    "OpenCode: --session points to an OpenCode SQLite file. "
                    "Add --opencode-session-id <ses_...> or set OPENCODE_SESSION_ID."
                )
            return _finalize(
                load_snapshot_from_opencode_sqlite(args.session, ses, args.scope, args.model, args.provider),
                args,
            )
        return _finalize(
            load_snapshot_from_session(args.session, args.scope, args.model, args.provider),
            args,
        )

    agent_tool = requested_agent_tool(args)

    if agent_tool == "claude-code":
        if args.scope != "latest-turn":
            return _finalize(_load_claude_aggregate(args), args)
        claude_path = None
        session_id = runtime_claude_session_id()
        if session_id:
            claude_path = find_claude_usage_for_session(session_id)
        if claude_path is None:
            claude_path = newest_claude_usage_file()
        if claude_path:
            return _finalize(
                load_snapshot_from_claude_usage(claude_path, args.model, args.provider),
                args,
            )
        raise SystemExit(
            "No Claude Code usage log found under ~/.claude/usage-data/session-meta. "
            "If you are on Windows, the equivalent home-relative path is %USERPROFILE%\\.claude\\usage-data\\session-meta."
        )

    if agent_tool == "codex":
        session_path = None
        thread_id = runtime_codex_thread_id()
        if thread_id:
            session_path = find_codex_session_for_thread(thread_id)
        if session_path is None:
            session_path = newest_session_file()
        if session_path:
            return _finalize(
                load_snapshot_from_session(session_path, args.scope, args.model, args.provider),
                args,
            )
        raise SystemExit(
            "No Codex session file found under ~/.codex/sessions or ~/.codex/archived_sessions. "
            "If you are on Windows, the equivalent home-relative paths are %USERPROFILE%\\.codex\\sessions and %USERPROFILE%\\.codex\\archived_sessions."
        )

    if agent_tool == "kimi-code":
        kimi_path = None
        sid = os.environ.get("KIMI_SESSION_ID", "").strip()
        if sid:
            kimi_path = find_kimi_context_for_session(sid)
        if kimi_path is None:
            kimi_path = newest_kimi_context_file()
        if kimi_path:
            return _finalize(
                load_snapshot_from_kimi_context(kimi_path, args.model, args.provider),
                args,
            )
        share = kimi_share_dir()
        raise SystemExit(
            f"No Kimi Code context.jsonl found under {share / 'sessions'} or {share / 'imported_sessions'}. "
            "Try --session <path/to/context.jsonl>, export with `kimi export`, or pass manual --input-tokens/--output-tokens."
        )

    if agent_tool == "opencode":
        ses = (getattr(args, "opencode_session_id", None) or "").strip() or runtime_opencode_session_id()
        if ses:
            db_hit = global_find_opencode_db_for_session(ses)
            if db_hit:
                return _finalize(
                    load_snapshot_from_opencode_sqlite(db_hit, ses, args.scope, args.model, args.provider),
                    args,
                )
            raise SystemExit(
                f"OpenCode session id {ses!r} not found in any opencode*.db under known data dirs. "
                "Try `opencode session list`, OPENCODE_DATA_DIR, or `--session /path/to/opencode.db --opencode-session-id ...`."
            )
        newest = global_newest_opencode_session()
        if newest:
            db_path, sid2 = newest
            return _finalize(
                load_snapshot_from_opencode_sqlite(db_path, sid2, args.scope, args.model, args.provider),
                args,
            )
        roots = ", ".join(str(p) for p in opencode_standard_dirs())
        raise SystemExit(
            f"No OpenCode SQLite (opencode*.db) found under: {roots}. "
            "Install sessions with OpenCode CLI, or set OPENCODE_DATA_DIR / XDG_DATA_HOME, or use manual token flags."
        )

    if agent_tool == "trae":
        raise SystemExit(trae_manual_mode_error())

    codex_path = newest_session_file()
    claude_path = newest_claude_usage_file()
    kimi_path = newest_kimi_context_file()
    opencode_ref = global_newest_opencode_session()

    sources = []
    if codex_path:
        sources.append(("codex", codex_path))
    if claude_path:
        sources.append(("claude-code", claude_path))
    if kimi_path:
        sources.append(("kimi-code", kimi_path))
    if opencode_ref:
        sources.append(("opencode", opencode_ref))

    if len(sources) == 1:
        source_type, path = sources[0]
        if source_type == "codex":
            return _finalize(
                load_snapshot_from_session(path, args.scope, args.model, args.provider),
                args,
            )
        if source_type == "kimi-code":
            return _finalize(
                load_snapshot_from_kimi_context(path, args.model, args.provider),
                args,
            )
        if source_type == "opencode":
            db_p, sid_o = path  # type: ignore[misc]
            return _finalize(
                load_snapshot_from_opencode_sqlite(db_p, sid_o, args.scope, args.model, args.provider),
                args,
            )
        if args.scope != "latest-turn":
            return _finalize(_load_claude_aggregate(args), args)
        return _finalize(
            load_snapshot_from_claude_usage(path, args.model, args.provider),
            args,
        )

    if len(sources) > 1:
        raise SystemExit(
            "Multiple software logs are available locally. "
            "Pass --agent-tool codex, --agent-tool claude-code, --agent-tool kimi-code, --agent-tool opencode, "
            "or run token-receipt inside the software whose conversation you want to bill. "
            "token-receipt does not guess across software."
        )

    raise SystemExit(
        "No Codex, Claude Code, Kimi Code, or OpenCode session logs found locally. "
        "For Trae, automatic import is not implemented yet; provide --input-tokens and --output-tokens for manual mode."
    )


def _finalize(snapshot: UsageSnapshot, args: argparse.Namespace) -> UsageSnapshot:
    """Post-loader rewrites that should apply to every code path."""
    from .bedrock import resolve_provider_and_model

    # Explicit CLI flags win; otherwise, rewrite Bedrock-shaped provider/model.
    if not args.provider and not args.model:
        snapshot.provider, snapshot.model = resolve_provider_and_model(
            snapshot.provider, snapshot.model,
        )
    elif not args.provider:
        snapshot.provider, _ = resolve_provider_and_model(snapshot.provider, snapshot.model)
    elif not args.model:
        _, snapshot.model = resolve_provider_and_model(snapshot.provider, snapshot.model)
    return snapshot


def _load_claude_aggregate(args: argparse.Namespace) -> UsageSnapshot:
    from .claude_aggregator import aggregate_claude_projects

    now = dt.datetime.now(tz=dt.timezone.utc)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

    if args.scope == "today":
        local_midnight = dt.datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        since = local_midnight.astimezone(dt.timezone.utc)
        until = now
        session_id = None
    elif args.scope in ("session", "session-all"):
        since = epoch
        until = now
        session_id = runtime_claude_session_id()
        if not session_id:
            raise SystemExit(
                f"--scope {args.scope} needs the active Claude Code sessionId. "
                "Run token-receipt from inside Claude Code (CLAUDE_SESSION_ID is set), "
                "or pass --scope today for a whole-day aggregate."
            )
    else:
        since = epoch
        until = now
        session_id = runtime_claude_session_id()

    snapshot = aggregate_claude_projects(
        since, until,
        session_id=session_id,
        model_override=args.model,
        provider_override=args.provider,
    )
    snapshot.scope = args.scope
    return snapshot



def available_fields_report(snapshot: UsageSnapshot) -> Dict[str, Any]:
    available = sorted(snapshot.available_fields)
    rendered = [field for field in RECEIPT_TOKEN_FIELDS if field in snapshot.available_fields]
    unavailable_common = [field for field in COMMON_TOKEN_FIELDS if field not in snapshot.available_fields]
    available_optional = [field for field in OPTIONAL_TOKEN_FIELDS if field in snapshot.available_fields]
    report: Dict[str, Any] = {
        "source": snapshot.source,
        "scope": snapshot.scope,
        "provider": snapshot.provider,
        "model": snapshot.model,
        "token_usage_fields_available": available,
        "receipt_fields_common": list(COMMON_TOKEN_FIELDS),
        "receipt_fields_optional_if_available": list(OPTIONAL_TOKEN_FIELDS),
        "receipt_fields_rendered_by_default": rendered,
        "receipt_common_fields_missing_from_source": unavailable_common,
        "receipt_optional_fields_available": available_optional,
        "context_fields_available": ["model_context_window"] if snapshot.context_window else [],
        "metadata_fields_supported": [
            "session_id",
            "timestamp",
            "model_provider",
            "session_meta.model",
            "session_meta.model_id",
            "session_meta.model_name",
            "session_meta.model_slug",
            "turn_context.model",
        ],
        "known_unavailable_in_codex_token_count": [
            "cache_write_tokens unless provided manually or present in another provider log",
            "tool_use_tokens",
            "system_tokens",
        ],
    }
    if snapshot.skip_price_estimate:
        report["usd_estimate_note"] = "skipped: kimi context.jsonl only stores cumulative context token tallies"
        report["kimi_context_roles_expected"] = ["_system_prompt", "_usage", "_checkpoint", "assistant/user messages"]
    if snapshot.context_tokens is not None:
        report["context_snapshot_tokens_last_usage"] = snapshot.context_tokens
    return report
