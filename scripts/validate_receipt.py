#!/usr/bin/env python3
"""Smoke tests for token_receipt.py visual and pricing behavior."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from token_receipt.data import newest_claude_usage_file, requested_agent_tool, runtime_agent_tool, runtime_claude_session_id, runtime_opencode_session_id  # noqa: E402
from token_receipt.models import printable_receipt_char, visual_display_width  # noqa: E402

SCRIPT = ROOT / "scripts" / "token_receipt.py"
HOOK_SCRIPT = ROOT / "scripts" / "claude_session_end_hook.py"
INSTALLER = ROOT / "scripts" / "install_claude_auto_trigger.py"
UNINSTALLER = ROOT / "scripts" / "uninstall_claude_auto_trigger.py"


def run_script(script: Path, *args: str, env: dict[str, str] | None = None, stdin_text: str | None = None) -> str:
    child_env = {**os.environ}
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        child_env.update(env)
    result = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(ROOT),
        text=True,
        input=stdin_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.rstrip("\n")


def run_case(*args: str, env: dict[str, str] | None = None, stdin_text: str | None = None) -> str:
    return run_script(SCRIPT, *args, env=env, stdin_text=stdin_text)


def is_rule_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return len(set(stripped)) == 1 and stripped[0] in {"-", "─", "━"}


def assert_receipt(text: str, width: int, must_contain: list[str], language: str = "en") -> None:
    lines = text.splitlines()
    assert lines, "empty receipt"
    for line in lines:
        measured = visual_display_width(line, language)
        assert measured <= width + 0.51, f"line too wide ({measured}>{width}): {line!r}"
        for char in line:
            assert printable_receipt_char(char), f"unsupported control char in {line!r}"
    for needle in must_contain:
        assert needle in text, f"missing {needle!r}"
    assert "||" in text, "barcode-like bars missing"
    assert any(label in text for label in ("ITEM", "项目")), "receipt item column missing"
    assert any(label in text for label in ("TOKENS", "TOKEN")), "receipt token column missing"
    assert any(label in text for label in ("TOTAL", "总计")), "total line missing"
    assert any(set(line.strip()) == {"━"} for line in lines if line.strip()), "strong separator missing"
    assert any(set(line.strip()) == {"─"} for line in lines if line.strip()), "light separator missing"


def assert_html_receipt(text: str, must_contain: list[str], language: str = "en") -> None:
    assert text.startswith("<!DOCTYPE html>"), "html output should start with doctype"
    assert "<html" in text and "</html>" in text, "html wrapper missing"
    assert "@media print" in text, "print stylesheet missing"
    assert "window.print()" in text, "print button missing"
    assert f'lang="{language}"' in text, f"expected html lang={language!r}"
    assert "receipt-row" in text, "receipt rows missing"
    assert "receipt-barcode" in text, "barcode block missing"
    assert "receipt-language-panel" in text, "language toggle panel missing"
    assert 'data-language-button="en"' in text, "english language button missing"
    assert 'data-language-button="zh-CN"' in text, "chinese language button missing"
    assert 'data-language="en"' in text, "english receipt view missing"
    assert 'data-language="zh-CN"' in text, "chinese receipt view missing"
    assert "receipt-tip-panel" in text, "external tip panel missing"
    assert ".tip-options[hidden]" in text, "hidden tip options css missing"
    for needle in must_contain:
        assert needle in text, f"missing {needle!r}"


def extract_tip_config(text: str) -> dict[str, object]:
    start_marker = '<script id="tip-config" type="application/json">'
    end_marker = "</script>"
    start = text.find(start_marker)
    assert start >= 0, "tip config script missing"
    start += len(start_marker)
    end = text.find(end_marker, start)
    assert end >= 0, "tip config script not closed"
    return json.loads(text[start:end])


def extract_footer(text: str) -> list[str]:
    lines = text.splitlines()
    rule_indexes = [index for index, line in enumerate(lines) if is_rule_line(line)]
    assert rule_indexes, "no divider rules found"
    footer_lines: list[str] = []
    for line in lines[rule_indexes[-1] + 1 :]:
        if not line.strip():
            break
        footer_lines.append(line.strip())
    assert footer_lines, "footer block missing"
    return footer_lines


def assert_logo_label_aligned(text: str, label: str, max_delta: float = 0.5) -> None:
    top: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            break
        top.append(line)
    label_index = next((index for index, line in enumerate(top) if label in line), -1)
    assert label_index > 0, f"logo label {label!r} missing from top block"
    logo_lines = top[:label_index]
    starts: list[int] = []
    ends: list[int] = []
    for line in logo_lines:
        filled = [index for index, char in enumerate(line) if char != " "]
        if filled:
            starts.append(min(filled))
            ends.append(max(filled) + 1)
    assert starts and ends, "logo has no visible pixels"
    label_start = top[label_index].index(label)
    label_end = label_start + len(label)
    logo_center = (min(starts) + max(ends)) / 2
    label_center = (label_start + label_end) / 2
    delta = abs(label_center - logo_center)
    assert delta <= max_delta, f"{label} not centered under logo: delta={delta:.1f}"


def make_session_fixture() -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="token-receipt-validate-"))
    fixture = tmpdir / "session.jsonl"
    items = [
        {
            "timestamp": "2026-04-26T02:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "fixture-session",
                "timestamp": "2026-04-26T01:58:00Z",
                "model_provider": "openai",
            },
        },
        {
            "timestamp": "2026-04-26T02:00:00Z",
            "type": "turn_context",
            "payload": {
                "model": "gpt-5.5",
            },
        },
        {
            "timestamp": "2026-04-26T02:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "model_context_window": 258400,
                    "last_token_usage": {
                        "input_tokens": 161117,
                        "cached_input_tokens": 2432,
                        "output_tokens": 383,
                        "reasoning_output_tokens": 282,
                        "total_tokens": 161500,
                    },
                },
            },
        },
    ]
    with fixture.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    return fixture


def make_claude_usage_fixture() -> tuple[Path, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="token-receipt-claude-hook-"))
    usage = tmpdir / "claude-session.json"
    transcript = tmpdir / "claude-session.jsonl"
    usage.write_text(
        json.dumps(
            {
                "session_id": "claude-hook-session",
                "start_time": "2026-04-27T04:00:00Z",
                "input_tokens": 12487,
                "output_tokens": 3215,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    transcript_items = [
        {
            "message": {
                "model": "claude-sonnet-4.5",
            }
        }
    ]
    with transcript.open("w", encoding="utf-8") as handle:
        for item in transcript_items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    return usage, transcript


def make_claude_home_fixture() -> tuple[Path, str]:
    home = Path(tempfile.mkdtemp(prefix="token-receipt-claude-home-"))
    usage_dir = home / ".claude" / "usage-data" / "session-meta"
    project_dir = home / ".claude" / "projects" / "demo"
    usage_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    session_id = "claude-current-session"
    (usage_dir / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "start_time": "2026-04-27T04:00:00Z",
                "input_tokens": 12487,
                "output_tokens": 3215,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    (project_dir / f"{session_id}.jsonl").write_text(
        json.dumps({"message": {"model": "claude-sonnet-4.5"}}, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return home, session_id


def make_claude_mtime_tiebreak_fixture() -> tuple[Path, Path]:
    home = Path(tempfile.mkdtemp(prefix="token-receipt-claude-mtime-"))
    usage_dir = home / ".claude" / "usage-data" / "session-meta"
    usage_dir.mkdir(parents=True, exist_ok=True)

    older = usage_dir / "z-older.json"
    newer = usage_dir / "a-newer.json"

    older.write_text(
        json.dumps(
            {
                "session_id": "older-session",
                "start_time": "2026-04-27T04:00:00Z",
                "input_tokens": 100,
                "output_tokens": 10,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            {
                "session_id": "newer-session",
                "start_time": "2026-04-27T05:00:00Z",
                "input_tokens": 200,
                "output_tokens": 20,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    # Same integer second, different sub-second mtimes. The later semantic
    # session should still win via start_time rather than file mtime noise.
    os.utime(older, (1_777_262_400.900, 1_777_262_400.900))
    os.utime(newer, (1_777_262_400.100, 1_777_262_400.100))
    return home, newer


def make_kimi_kimi_home_fixture() -> tuple[Path, Path]:
    """Minimal ~/.kimi tree: sessions/<hash>/<id>/context.jsonl + config.toml."""
    home = Path(tempfile.mkdtemp(prefix="token-receipt-kimi-home-"))
    share = home / ".kimi"
    sess_root = share / "sessions" / "a1deadbeefcafefeedb8a1deadbeefcaf" / "kimi-session-xyz"
    sess_root.mkdir(parents=True)
    ctx = sess_root / "context.jsonl"
    lines = [
        json.dumps({"role": "_system_prompt", "content": "fixture system prompt"}, ensure_ascii=True),
        json.dumps({"role": "_usage", "token_count": 1000}, ensure_ascii=True),
        json.dumps({"role": "_usage", "token_count": 8150}, ensure_ascii=True),
    ]
    ctx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (share / "config.toml").write_text('default_model = "kimi-k2"\n', encoding="utf-8")
    return home, ctx


def make_opencode_sqlite_fixture() -> tuple[Path, str]:
    """Minimal OpenCode-style SQLite (session + message), compatible with CodeBurn schema."""
    tmpdir = Path(tempfile.mkdtemp(prefix="token-receipt-opencode-"))
    db = tmpdir / "opencode_fixture.db"
    sid = "ses_fixture_opencode_xx"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, title TEXT, "
        "time_created INTEGER, time_archived INTEGER, parent_id TEXT)"
    )
    conn.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)")
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?)",
        (sid, "/tmp/opencode_demo", "demo", 1_730_000_000, None, None),
    )
    base_msg = {
        "role": "assistant",
        "modelID": "anthropic/claude-sonnet-4-5",
        "tokens": {
            "input": 990,
            "output": 50,
            "reasoning": 10,
            "cache": {"read": 12, "write": 8},
        },
    }
    conn.execute(
        "INSERT INTO message VALUES (?,?,?,?)",
        ("msg_a1", sid, 1_730_000_001, json.dumps(base_msg, ensure_ascii=True)),
    )
    conn.execute(
        "INSERT INTO message VALUES (?,?,?,?)",
        (
            "msg_a2",
            sid,
            1_730_000_002,
            json.dumps(
                {
                    "role": "assistant",
                    "modelID": "anthropic/claude-sonnet-4-5",
                    "tokens": {"input": 100, "output": 20, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                },
                ensure_ascii=True,
            ),
        ),
    )
    conn.commit()
    conn.close()
    return db, sid


def main() -> int:
    fixture = make_session_fixture()
    claude_usage, claude_transcript = make_claude_usage_fixture()
    claude_home, claude_session_id = make_claude_home_fixture()
    claude_mtime_home, expected_newest_usage = make_claude_mtime_tiebreak_fixture()

    assert runtime_agent_tool({"CODEX_THREAD_ID": "thread"}) == "codex"
    assert runtime_agent_tool({"CLAUDECODE": "1"}) == "claude-code"
    assert runtime_agent_tool({"KIMI_SESSION_ID": "sess-1"}) == "kimi-code"
    assert runtime_opencode_session_id({"OPENCODE_SESSION_ID": " ses_x "}) == "ses_x"
    assert runtime_agent_tool({"OPENCODE_SESSION_ID": "ses-z"}) == "opencode"
    assert requested_agent_tool(SimpleNamespace(agent_tool=None, brand=None), {"CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop"}) == "codex"
    assert requested_agent_tool(SimpleNamespace(agent_tool=None, brand="generic"), {"CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop"}) == "codex"
    assert requested_agent_tool(SimpleNamespace(agent_tool="claude-code", brand=None), {"CODEX_THREAD_ID": "thread"}) == "claude-code"

    codex = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "gpt-5.4",
        "--input-tokens", "82149",
        "--cached-input-tokens", "52608",
        "--output-tokens", "541",
        "--reasoning-output-tokens", "86",
        "--context-window", "258400",
        "--width", "48",
    )
    assert_receipt(codex, 48, ["CODEX", "THANK YOU FOR CODING WITH", "CONTEXT USED", "USD ESTIMATE", "$"])
    assert_logo_label_aligned(codex, "CODEX")
    assert "DATA: SNAPSHOT" not in codex
    assert "Reasoning Tokens" in codex

    claude = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--cache-write-tokens", "1024",
        "--output-tokens", "3215",
        "--reasoning-output-tokens", "128",
        "--width", "48",
    )
    assert_receipt(claude, 48, ["████", "CLAUDE", "CODE", "Reasoning Tokens", "Cache Write Tokens", "USD ESTIMATE"])
    assert_logo_label_aligned(claude, "CLAUDE CODE", max_delta=1.0)

    claude_zh = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--cache-write-tokens", "1024",
        "--output-tokens", "3215",
        "--reasoning-output-tokens", "128",
        "--width", "48",
        "--language", "zh-CN",
        "--footer-tone", "snarky",
        "--conversation-summary", "再改一版 logo 对齐",
    )
    assert_receipt(claude_zh, 48, ["CLAUDE CODE", "感谢使用 Claude", "小票号", "供应商", "总计", "USD 预估"], language="zh-CN")
    assert_logo_label_aligned(claude_zh, "CLAUDE CODE", max_delta=1.0)
    assert any(word in claude_zh for word in ("账单", "费用", "代价", "预算", "钱包", "余额", "钱")), "zh receipt footer should read like a Chinese receipt footer"

    trae = run_case(
        "--provider", "openai",
        "--agent-tool", "trae",
        "--model", "gpt-5.4",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--output-tokens", "3215",
        "--width", "48",
    )
    assert_receipt(trae, 48, ["TRAE", "THANK YOU FOR CODING WITH ChatGPT", "USD ESTIMATE"])
    assert_logo_label_aligned(trae, "TRAE")

    kimi_home, kimi_ctx_path = make_kimi_kimi_home_fixture()
    kimi_by_session = run_case(
        "--agent-tool",
        "kimi-code",
        "--width",
        "48",
        env={**os.environ, "HOME": str(kimi_home), "USERPROFILE": str(kimi_home), "KIMI_SESSION_ID": "kimi-session-xyz"},
    )
    assert_receipt(kimi_by_session, 48, ["KIMI CODE", "THANK YOU FOR CODING WITH Kimi", "CONTEXT USED", "8,150"])
    assert "Input Tokens" not in kimi_by_session
    assert "UNMAPPED" in kimi_by_session
    assert_logo_label_aligned(kimi_by_session, "KIMI CODE")

    kimi_direct = run_case("--session", str(kimi_ctx_path), "--agent-tool", "kimi-code", "--width", "48")
    assert "8,150" in kimi_direct and "KIMI CODE" in kimi_direct

    opc_db, opc_sid = make_opencode_sqlite_fixture()
    opc_latest = run_case(
        "--session",
        str(opc_db),
        "--opencode-session-id",
        opc_sid,
        "--agent-tool",
        "opencode",
        "--scope",
        "latest-turn",
        "--width",
        "48",
    )
    assert_receipt(opc_latest, 48, ["OPENCODE", "THANK YOU FOR CODING WITH Claude", "Input Tokens", "USD ESTIMATE", "$"])
    assert_logo_label_aligned(opc_latest, "OPENCODE")

    opc_session = run_case(
        "--session",
        str(opc_db),
        "--opencode-session-id",
        opc_sid,
        "--agent-tool",
        "opencode",
        "--scope",
        "session",
        "--width",
        "48",
    )
    assert "OPENCODE" in opc_session and "USD ESTIMATE" in opc_session
    assert "Reasoning Tokens" in opc_session
    assert "1,090" in opc_session
    assert "1,190" in opc_session

    qwen = run_case(
        "--provider", "alibaba",
        "--agent-tool", "trae",
        "--model", "qwen3.6-plus",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(qwen, 48, ["THANK YOU FOR CODING WITH Qwen", "CNY ESTIMATE", "¥14.000000", "RATE NOTE"])

    deepseek = run_case(
        "--provider", "deepseek",
        "--agent-tool", "codex",
        "--model", "deepseek-chat",
        "--input-tokens", "1000000",
        "--cached-input-tokens", "500000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(deepseek, 48, ["THANK YOU FOR CODING WITH DeepSeek", "USD ESTIMATE", "$0.364000"])

    glm = run_case(
        "--provider", "bigmodel",
        "--agent-tool", "generic",
        "--model", "glm-5-1",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(glm, 48, ["THANK YOU FOR CODING WITH GLM", "CNY ESTIMATE", "¥30.000000", "ALIYUN CN"])

    mimo = run_case(
        "--provider", "xiaomi",
        "--agent-tool", "generic",
        "--model", "mimo-v2.5-pro",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(mimo, 48, ["THANK YOU FOR CODING WITH MiMo", "USD ESTIMATE", "$4.000000", "OPENROUTER"])

    minimax = run_case(
        "--provider", "minimax",
        "--agent-tool", "generic",
        "--model", "minimax-m2.7",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(minimax, 48, ["THANK YOU FOR CODING WITH MiniMax", "USD ESTIMATE", "$1.500000"])

    visual_footer_case = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "gpt-5.4",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--output-tokens", "3215",
        "--width", "48",
        "--conversation-summary", "反复打磨 logo 对齐和小票视觉",
    )
    pricing_footer_case = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "gpt-5.4",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--output-tokens", "3215",
        "--width", "48",
        "--conversation-summary", "核对价格表和美元估算口径",
    )
    visual_footer = extract_footer(visual_footer_case)
    pricing_footer = extract_footer(pricing_footer_case)
    assert visual_footer != pricing_footer, "different conversation summaries should not reuse the same footer"
    assert any(word in " ".join(visual_footer) for word in ("LOGO", "LAYOUT", "PIXELS", "ALIGNMENT")), "visual summary should steer footer theme"
    assert any(word in " ".join(pricing_footer) for word in ("PRICE", "BILL", "ESTIMATE", "RECEIPT")), "pricing summary should steer footer theme"
    assert "DOES NOT INCLUDE THIS RECEIPT" not in " ".join(visual_footer), "visual footer regressed to the old slot-filled formula"
    for line in visual_footer + pricing_footer:
        assert len(line) <= 40, f"footer line too long: {line!r}"

    unknown = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "mystery-model",
        "--input-tokens", "1000",
        "--output-tokens", "500",
        "--width", "42",
    )
    assert_receipt(unknown, 42, ["PRICE", "UNMAPPED"])

    split_brand_and_model = run_case(
        "--provider", "openai",
        "--agent-tool", "claude-code",
        "--model", "gpt-5.4",
        "--input-tokens", "1000",
        "--output-tokens", "500",
        "--width", "48",
    )
    assert_receipt(split_brand_and_model, 48, ["████", "THANK YOU FOR CODING WITH ChatGPT"])

    session_case = run_case(
        "--session", str(fixture),
        "--agent-tool", "codex",
        "--width", "48",
        "--footer-tone", "snarky",
    )
    assert_receipt(session_case, 48, ["MODEL", "gpt-5.5", "USD ESTIMATE", "$"])
    assert "UNRECORDED" not in session_case
    assert "UNMAPPED" not in session_case

    fields = run_case(
        "--session", str(fixture),
        "--show-fields",
    )
    assert "token_usage_fields_available" in fields
    assert "cache_write_tokens" in fields
    assert "turn_context.model" in fields

    write_target = Path(tempfile.mkdtemp(prefix="token-receipt-write-")) / "receipt.txt"
    quiet_stdout = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--output-tokens", "3215",
        "--write", str(write_target),
    )
    assert quiet_stdout == ""
    saved_receipt = write_target.read_text(encoding="utf-8")
    assert "CLAUDE CODE" in saved_receipt
    assert "THANK YOU FOR CODING WITH Claude" in saved_receipt

    html_target = Path(tempfile.mkdtemp(prefix="token-receipt-html-")) / "receipt.html"
    quiet_html = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--output-tokens", "3215",
        "--language", "zh-CN",
        "--footer", "打印测试通过。",
        "--output", "html",
        "--write", str(html_target),
    )
    assert quiet_html == ""
    saved_html = html_target.read_text(encoding="utf-8")
    assert_html_receipt(
        saved_html,
        ["CLAUDE CODE", "感谢使用 Claude", "USD 预估", "打印测试通过。", "加一点小费", "15%", "18%", "20%", "25%"],
        language="zh-CN",
    )
    zh_tip_config = extract_tip_config(saved_html)
    assert zh_tip_config["defaultLanguage"] == "zh-CN"
    zh_tip_payload = zh_tip_config["tip"]["zh-CN"]
    assert zh_tip_payload["language"] == "zh-CN"
    assert zh_tip_payload["defaultFooter"] == "打印测试通过。"
    assert zh_tip_payload["tipLabel"] == "小费"
    assert zh_tip_payload["grandTotalLabel"] == "应付总额"
    assert [option["percent"] for option in zh_tip_payload["options"]] == [15, 18, 20, 25]
    assert all(option["footer"] != zh_tip_payload["defaultFooter"] for option in zh_tip_payload["options"])
    assert all("打印效果" not in option["footer"] for option in zh_tip_payload["options"])
    assert all(" 。" not in option["footer"] and " ，" not in option["footer"] for option in zh_tip_payload["options"])

    dual_html_target = Path(tempfile.mkdtemp(prefix="token-receipt-dual-html-")) / "receipt.html"
    dual_export = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--output-tokens", "3215",
        "--write-html", str(dual_html_target),
    )
    assert "CLAUDE CODE" in dual_export
    assert dual_export.startswith(" ")
    dual_saved_html = dual_html_target.read_text(encoding="utf-8")
    assert_html_receipt(
        dual_saved_html,
        ["CLAUDE CODE", "THANK YOU FOR CODING WITH Claude", "USD ESTIMATE", "Add tip", "15%", "18%", "20%", "25%"],
        language="en",
    )
    en_tip_config = extract_tip_config(dual_saved_html)
    assert en_tip_config["defaultLanguage"] == "en"
    en_tip_payload = en_tip_config["tip"]["en"]
    assert en_tip_payload["language"] == "en"
    assert en_tip_payload["tipLabel"] == "TIP"
    assert en_tip_payload["grandTotalLabel"] == "GRAND TOTAL"
    assert [option["percent"] for option in en_tip_payload["options"]] == [15, 18, 20, 25]
    assert all(option["footer"] != en_tip_payload["defaultFooter"] for option in en_tip_payload["options"])

    claude_env = os.environ.copy()
    claude_env["HOME"] = str(claude_home)
    claude_env["CLAUDECODE"] = "1"
    claude_env["CLAUDE_SESSION_ID"] = claude_session_id
    claude_fields = run_case(
        "--show-fields",
        env=claude_env,
    )
    claude_report = json.loads(claude_fields)
    norm_source = claude_report["source"].replace("\\", "/")
    assert norm_source.endswith(f"/{claude_session_id}.json")
    assert claude_report["model"] == "claude-sonnet-4.5"

    original_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = str(claude_mtime_home)
        assert newest_claude_usage_file() == expected_newest_usage
    finally:
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home

    hook_env = os.environ.copy()
    hook_env["TOKEN_RECEIPT_CLAUDE_USAGE_PATH"] = str(claude_usage)
    hook_payload = {
        "session_id": "claude-hook-session",
        "transcript_path": str(claude_transcript),
        "hook_event_name": "SessionEnd",
    }
    hook_output = run_script(
        HOOK_SCRIPT,
        env=hook_env,
        stdin_text=json.dumps(hook_payload, ensure_ascii=True),
    )
    hook_json = json.loads(hook_output)
    assert hook_json["continue"] is True
    assert hook_json["suppressOutput"] is True
    assert "```text" in hook_json["systemMessage"]
    assert "CLAUDE CODE" in hook_json["systemMessage"]
    assert "THANK YOU FOR CODING WITH Claude" in hook_json["systemMessage"]
    assert "claude-sonnet-4.5" in hook_json["systemMessage"]

    settings_dir = Path(tempfile.mkdtemp(prefix="token-receipt-settings-"))
    settings_path = settings_dir / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo existing-stop",
                                }
                            ],
                        }
                    ]
                }
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    install_output = run_script(
        INSTALLER,
        "--settings", str(settings_path),
        "--hook-root", str(ROOT),
    )
    install_json = json.loads(install_output)
    assert install_json["installed"] is True
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    session_end = saved["hooks"]["SessionEnd"]
    assert len(session_end) == 1
    assert "claude_session_end_hook.py" in session_end[0]["hooks"][0]["command"]

    second_install = run_script(
        INSTALLER,
        "--settings", str(settings_path),
        "--hook-root", str(ROOT),
    )
    assert json.loads(second_install)["installed"] is True
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    matching_commands = [
        hook["command"]
        for entry in saved["hooks"]["SessionEnd"]
        for hook in entry.get("hooks", [])
        if "claude_session_end_hook.py" in hook.get("command", "")
    ]
    assert len(matching_commands) == 1, "installer should be idempotent"

    uninstall_output = run_script(
        UNINSTALLER,
        "--settings", str(settings_path),
    )
    assert json.loads(uninstall_output)["removed"] is True
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    session_end_after = saved.get("hooks", {}).get("SessionEnd", [])
    assert not session_end_after

    print("token-receipt validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
