"""Claude Code SessionEnd hook helpers for token receipt."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Dict, Optional

from .cli import format_chat_reply
from .data import (
    find_claude_usage_for_session,
    load_snapshot_from_claude_usage,
    newest_claude_usage_file,
)
from .html_render import render_receipt_html
from .models import DEFAULT_PRICING
from .pricing import estimate_cost
from .render import render_receipt


DEFAULT_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
DEFAULT_HOOK_ROOT = Path.home() / ".codex" / "skills" / "token-receipt"
HOOK_SCRIPT_RELATIVE = Path("scripts") / "claude_session_end_hook.py"
HOOK_MARKER = str(HOOK_SCRIPT_RELATIVE)
DEFAULT_HTML_EXPORT = Path("/tmp/token-receipt.html")


def build_claude_hook_command(hook_root: Optional[Path] = None, python_bin: str = "python3") -> str:
    root = (hook_root or DEFAULT_HOOK_ROOT).expanduser()
    script_path = root / HOOK_SCRIPT_RELATIVE
    return f"{python_bin} {shlex.quote(str(script_path))}"


def build_session_end_hook_entry(command: str) -> Dict[str, Any]:
    return {
        "matcher": "*",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 30,
            }
        ],
    }


def load_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return data


def save_settings(path: Path, settings: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _strip_existing_token_receipt_hooks(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for entry in entries:
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            kept.append(entry)
            continue
        commands = [
            hook.get("command", "")
            for hook in hooks
            if isinstance(hook, dict) and hook.get("type") == "command"
        ]
        if any(HOOK_MARKER in str(command) for command in commands):
            continue
        kept.append(entry)
    return kept


def install_session_end_hook(
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    hook_root: Optional[Path] = None,
    python_bin: str = "python3",
) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"'hooks' must be an object in {settings_path}")
    existing = hooks.get("SessionEnd") or []
    if not isinstance(existing, list):
        raise SystemExit(f"'hooks.SessionEnd' must be a list in {settings_path}")
    command = build_claude_hook_command(hook_root, python_bin)
    hooks["SessionEnd"] = _strip_existing_token_receipt_hooks(existing) + [
        build_session_end_hook_entry(command)
    ]
    save_settings(settings_path, settings)
    return {
        "settings_path": str(settings_path),
        "installed": True,
        "command": command,
    }


def uninstall_session_end_hook(settings_path: Path = DEFAULT_SETTINGS_PATH) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return {
            "settings_path": str(settings_path),
            "removed": False,
            "reason": "hooks_missing",
        }
    existing = hooks.get("SessionEnd") or []
    if not isinstance(existing, list):
        return {
            "settings_path": str(settings_path),
            "removed": False,
            "reason": "session_end_not_list",
        }
    cleaned = _strip_existing_token_receipt_hooks(existing)
    if cleaned:
        hooks["SessionEnd"] = cleaned
    else:
        hooks.pop("SessionEnd", None)
    save_settings(settings_path, settings)
    return {
        "settings_path": str(settings_path),
        "removed": len(cleaned) != len(existing),
    }


def build_session_end_system_message(
    hook_input: Dict[str, Any],
    usage_path: Optional[Path] = None,
    pricing_path: Path = DEFAULT_PRICING,
    width: int = 48,
) -> Dict[str, Any]:
    session_id = str(hook_input.get("session_id") or "")
    transcript_path = hook_input.get("transcript_path")
    transcript = Path(transcript_path) if isinstance(transcript_path, str) and transcript_path else None
    resolved_usage = usage_path or find_claude_usage_for_session(session_id) or newest_claude_usage_file()
    if not resolved_usage:
        return {
            "continue": True,
            "suppressOutput": True,
            "systemMessage": "Token Receipt skipped: no Claude usage log found.",
        }

    snapshot = load_snapshot_from_claude_usage(
        resolved_usage,
        model_override=None,
        provider_override=None,
        transcript_path=transcript,
    )
    estimate = estimate_cost(snapshot, pricing_path)
    receipt_text = render_receipt(
        snapshot=snapshot,
        estimate=estimate,
        width=width,
        agent_tool="claude-code",
        footer="auto",
        footer_tone="auto",
        conversation_hint="",
    )
    html_receipt = render_receipt_html(
        snapshot=snapshot,
        estimate=estimate,
        width=width,
        agent_tool="claude-code",
        footer="auto",
        footer_tone="auto",
        conversation_hint="",
        language="en",
    )
    DEFAULT_HTML_EXPORT.write_text(html_receipt + "\n", encoding="utf-8")
    return {
        "continue": True,
        "suppressOutput": True,
        "systemMessage": format_chat_reply(receipt_text, DEFAULT_HTML_EXPORT),
    }
