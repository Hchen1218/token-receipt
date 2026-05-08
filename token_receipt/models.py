"""Shared models and helpers for token receipt."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple


ALLOWED_WIDTHS = (42, 48, 56, 64)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PRICING = SKILL_DIR / "references" / "pricing.json"
DEFAULT_FOOTER = "auto"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "zh-CN")
PIXEL_CHARS = {"█", "░", "▒", "▓", "▐", "▛", "▜", "▌", "▘", "▝", "¥"}
# In terminal / code-block rendering, Chinese full-width characters behave
# much closer to a real 2-column cell than to the narrower chat-bubble estimate.
# Using the full width keeps zh-CN receipts aligned in Claude Code and PTY output.
CODE_BLOCK_WIDE_CHAR_WIDTH = 2.0
COMMON_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "total_tokens",
)
OPTIONAL_TOKEN_FIELDS = (
    "reasoning_output_tokens",
    "cache_write_tokens",
)
RECEIPT_TOKEN_FIELDS = COMMON_TOKEN_FIELDS + OPTIONAL_TOKEN_FIELDS


@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    # Kimi Code：context.jsonl 里 `_usage.token_count` 是上下文占用累计，≠ API 分项账单
    context_tokens: Optional[int] = None
    context_window: Optional[int] = None
    provider: str = "unknown"
    model: str = "UNRECORDED"
    source: str = "manual"
    session_id: str = "manual"
    timestamp: Optional[str] = None
    scope: str = "latest-turn"
    available_fields: Tuple[str, ...] = ()
    # 为 True 时不做单价估算（避免把上下文累计误当成 prompt/completion）
    skip_price_estimate: bool = False
    # Per-TTL split of cache-write tokens, populated by claude_aggregator when the
    # source carries message.usage.cache_creation.ephemeral_{5m,1h}_input_tokens.
    # Loaders that cannot distinguish leave these at 0; cache_write_tokens is the aggregate.
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    # Diagnostics for the new aggregator path; None for single-file loaders.
    aggregation_source: Optional[str] = None
    deduped_message_ids: int = 0


@dataclass
class PriceEstimate:
    status: str
    amount: Optional[float]
    model: str = "UNMAPPED"
    currency: str = "USD"
    source_url: str = ""
    source_checked_at: str = ""
    rate_note: str = ""
    # Non-empty only when status == "PARTIAL" — lists the rates we substituted for.
    partial_reasons: Tuple[str, ...] = ()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def fmt_int(value: Optional[int]) -> str:
    return f"{int(value or 0):,}"


def canonical_language(value: Optional[str]) -> str:
    normalized = (value or DEFAULT_LANGUAGE).strip().lower()
    if normalized in ("zh", "zh-cn", "zh_cn", "cn"):
        return "zh-CN"
    return "en"


def char_display_width(char: str) -> int:
    if not char:
        return 0
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2
    return 1


def display_width(value: str) -> int:
    return sum(char_display_width(char) for char in value)


def visual_char_width(char: str, language: Optional[str] = None) -> float:
    if not char:
        return 0.0
    if unicodedata.combining(char):
        return 0.0
    if canonical_language(language) == "zh-CN" and unicodedata.east_asian_width(char) in {"W", "F"}:
        return CODE_BLOCK_WIDE_CHAR_WIDTH
    return float(char_display_width(char))


def visual_display_width(value: str, language: Optional[str] = None) -> float:
    return sum(visual_char_width(char, language) for char in value)


def truncate(value: str, max_len: int, suffix: str = "...") -> str:
    if display_width(value) <= max_len:
        return value
    suffix_width = display_width(suffix)
    if max_len <= suffix_width:
        pieces: list[str] = []
        width = 0
        for char in value:
            char_width = char_display_width(char)
            if width + char_width > max_len:
                break
            pieces.append(char)
            width += char_width
        return "".join(pieces)
    pieces = []
    width = 0
    target = max_len - suffix_width
    for char in value:
        char_width = char_display_width(char)
        if width + char_width > target:
            break
        pieces.append(char)
        width += char_width
    return "".join(pieces) + suffix


def center_text(value: str, width: int) -> str:
    text = truncate(value, width)
    remaining = max(width - display_width(text), 0)
    left = remaining // 2
    right = remaining - left
    return (" " * left + text + " " * right).rstrip()


def truncate_visual(value: str, max_len: int, language: Optional[str] = None, suffix: str = "...") -> str:
    if visual_display_width(value, language) <= max_len:
        return value
    suffix_width = visual_display_width(suffix, language)
    if max_len <= suffix_width:
        pieces: list[str] = []
        width = 0.0
        for char in value:
            char_width = visual_char_width(char, language)
            if width + char_width > max_len:
                break
            pieces.append(char)
            width += char_width
        return "".join(pieces)
    pieces = []
    width = 0.0
    target = max_len - suffix_width
    for char in value:
        char_width = visual_char_width(char, language)
        if width + char_width > target:
            break
        pieces.append(char)
        width += char_width
    return "".join(pieces) + suffix


def center_text_visual(value: str, width: int, language: Optional[str] = None) -> str:
    text = truncate_visual(value, width, language)
    remaining = max(width - visual_display_width(text, language), 0.0)
    left = int(round(remaining / 2))
    right = max(width - left - int(round(visual_display_width(text, language))), 0)
    return (" " * left + text + " " * right).rstrip()


def printable_receipt_char(char: str) -> bool:
    return not unicodedata.category(char).startswith("C")


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_iso(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def display_time(value: Optional[str]) -> str:
    parsed = parse_iso(value)
    if not parsed:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    local = parsed.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")
