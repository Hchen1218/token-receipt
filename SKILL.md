---
name: token-receipt
description: Use when the user wants to view AI conversation token usage as a receipt, invoice, checkout slip, token bill, usage receipt, cost snapshot, or creative monospace thermal-paper artifact. Always consider this skill for Chinese prompts like 查看本次对话 Token 消耗, 生成 token 小票, 对话发票, AI 用量账单, 把这次对话打成小票, 看看这轮 token 消耗, or any request to make token/context usage visually shareable.
---

# Token Receipt

把本次 AI 对话的 Token 消耗做成一张可截图传播的 monospace 热敏纸小票。视觉优先级高于报表完整性，但数据口径必须诚实：真实日志优先，官方价格估算其次，缺失信息要明确标注。

## 用户怎么触发

下面这些说法默认应该直接触发：

- `token receipt`
- `token 小票`
- `对话发票`
- `AI 用量账单`
- `把这次对话打成小票`
- `看看这轮 token 消耗`
- `查看本次对话 Token 消耗`

Claude Code 如果装了自动触发，`SessionEnd` 结束时也会自动出票。

## 当前产品方向

- 主输出面仍然是聊天对话框里的文本小票，HTML 是跟随它一起返回的打印出口，不反过来抢主位。
- 不做二维码；底部继续保留当前的条形码 / receipt id 结构。
- 触发策略按宿主能力分层：
  - `Claude Code`：使用 `SessionEnd auto trigger + 触发词`。
  - `Codex`：使用触发词。
  - `Kimi Code`：使用 `--agent-tool kimi-code`（可读 `context.jsonl` 里 `_usage` 累计）。
  - `OpenCode`：使用 `--agent-tool opencode`（读默认数据目录下 `opencode*.db` SQLite，或 `--session <db> --opencode-session-id ses_...`）。
  - `Trae`：使用触发词。
- 不要假设所有宿主都有 Claude Code 那种 lifecycle hook。只有验证过支持 `SessionEnd` hook 的宿主，才做自动触发安装。

## 快速执行

优先运行脚本生成小票：

```bash
python3 scripts/token_receipt.py
```

如果是在任何支持的聊天宿主里手动触发，不要让 receipt 只停在 Bash stdout。
优先统一走聊天回复模式：

```bash
python3 scripts/token_receipt.py --agent-tool codex --chat-reply
python3 scripts/token_receipt.py --agent-tool claude-code --session ~/.claude/usage-data/session-meta/${CLAUDE_SESSION_ID}.json --chat-reply
python3 scripts/token_receipt.py --agent-tool kimi-code --chat-reply
python3 scripts/token_receipt.py --agent-tool opencode --chat-reply
```

这会同时做三件事：

- 把完整 receipt 作为聊天回复主体打印出来
- 自动落一份 `/tmp/token-receipt.html`
- 在回复底部附上 `[Printable HTML](/tmp/token-receipt.html)`

不要先跑一遍默认命令，再 `grep` 会话文件后重跑第二遍；那样只会在工具输出里刷出多张 logo。

常用参数：

```bash
python3 scripts/token_receipt.py --agent-tool codex --model gpt-5.4 --width 48 --stream
python3 scripts/token_receipt.py --agent-tool kimi-code
python3 scripts/token_receipt.py --agent-tool opencode
python3 scripts/token_receipt.py --provider anthropic --agent-tool claude-code --model claude-sonnet-4-5 --input-tokens 12487 --cached-input-tokens 8742 --output-tokens 3215
python3 scripts/token_receipt.py --provider openai --agent-tool trae --model gpt-5.4 --input-tokens 12487 --output-tokens 3215
python3 scripts/token_receipt.py --provider alibaba --agent-tool trae --model qwen3.6-plus --input-tokens 1000000 --output-tokens 1000000
python3 scripts/token_receipt.py --footer-tone snarky --conversation-summary "用户正在反复打磨 Claude Code 小票的传播视觉"
python3 scripts/token_receipt.py --show-fields
python3 scripts/install_claude_auto_trigger.py
python3 scripts/uninstall_claude_auto_trigger.py
```

脚本在交互式终端里默认会逐行打印；如果当前 stdout 不是 TTY，则会一次性输出完整小票。要强制逐行打印用 `--stream`，要强制整块输出用 `--no-stream`。若是在聊天框里回复，则把输出包在 Markdown 代码块里返回给用户，保持 monospace 视觉。

## 调用模式

- 默认目标是：让用户在对话框里直接看到完整 receipt 本体，而不是只看到 `RECEIPT # / TOTAL / USD ESTIMATE` 这种摘要。
- 只要 skill 是在聊天里被调用，优先返回完整 receipt 代码块；不要只汇报“已打印到终端”。
- 所有适配软件默认都走统一的聊天回复模式：`--chat-reply`。
- `--chat-reply` 会自动写出 `/tmp/token-receipt.html`，然后把 receipt 代码块和本地文件链接一起回出来。
- 终端 PTY 打印只是附加演示路径，不是默认主路径。只有用户明确说“打印到终端”“去 terminal 跑”时，才把终端当主输出面。
- 如果宿主支持 token streaming，回复内容尽量只放 receipt 本体，少写解释，让它在对话框里自然流出来。
- 如果宿主不支持把工具 stdout 增量渲染进聊天气泡，skill 也不能强行让 UI 逐行冒字；这时仍然应该把完整 receipt 贴回对话框，而不是退回成摘要。

## 聊天回复契约

- 默认回复必须是聊天友好的完整产物：receipt fenced code block + `[Printable HTML](/tmp/token-receipt.html)`。
- 代码块前后不要再加解释、总结、状态汇报、字段摘录、项目符号。
- 不要只返回 `RECEIPT #`、`TOTAL`、`USD ESTIMATE` 这种摘要。
- 在 Claude Code 里，如果需要用 Bash 跑脚本，优先直接用 `--chat-reply`；不要再手动拼 `--write /tmp/token-receipt.txt` + `--write-html ...` 的双步流。
- 只有在生成失败、字段缺失到无法出票、或用户明确要求解释时，才允许跳出这套默认回复格式；即便如此，也先给最短说明，再给 receipt 或错误原因。
- 推荐形态如下：

````text
```text
<full receipt here>
```

[Printable HTML](/tmp/token-receipt.html)
````

## 数据口径

1. 默认行为应该是“按当前软件取数”：
   - 在 Codex 里运行，就读 Codex 会话。
   - 在 Claude Code 的 hook 或会话里运行，就读 Claude Code usage log / transcript。
   - Kimi Code（Kimi CLI）：`--agent-tool kimi-code`，读 `context.jsonl` 里 `_usage.token_count`，为上下文累计而非 API 分项，美元估价会显示 `UNMAPPED`。
   - OpenCode：`~/.local/share/opencode/opencode*.db`（或 `OPENCODE_DATA_DIR` / `%LOCALAPPDATA%\\opencode`）里 `assistant` 消息的 `tokens.input` / `cache.read` / `cache.write` / `output` / `reasoning` 与 `modelID`（`provider/model`）；`--scope latest-turn` 取**最后一条**有 token/cost 的 assistant；`session` 对会话内多条 assistant **求和**。根会话来自 `session` 表不含 `parent_id` 的行（归档列缺失时降级查询）。
   - 不允许因为别的软件日志更新得更晚，就跨软件偷读。
2. 如果当前运行环境识别不出软件，而且本机同时存在多套日志，必须显式传 `--agent-tool codex`、`--agent-tool claude-code`、`--agent-tool kimi-code` 或 `--agent-tool opencode`；不要猜。
3. 默认使用最新 `token_count` 事件里的 `last_token_usage`，即“最新一轮小票”。
4. 如果用户要求累计账单，使用 `--scope session` 读取 `total_token_usage`。
5. 供应商优先读 `session_meta.payload.model_provider`；模型名先读 `session_meta.payload.model*`，若没有再回退读 `turn_context.model`；都没有时再要求调用者传 `--model`，否则小票显示 `MODEL: UNRECORDED`。
6. 价格只按 `references/pricing.json` 的官方价格表估算。匹配不到模型时显示 `PRICE: UNMAPPED`，不要自己编金额。
7. 价格表按模型条目保留币种；美元模型显示 `USD ESTIMATE`，人民币模型显示 `CNY ESTIMATE`。GLM 使用已标注的百炼 CNY 公开价格，MiMo 使用 OpenRouter 路由价格；不要把平台价伪装成厂商直连账单。
8. 主标题使用 `THANK YOU FOR CODING WITH ...`，让它更像真实品牌小票；不要在票面再放 `DATA: SNAPSHOT`。
9. 顶部 logo 按软件决定：Codex、Claude Code、Trae、Kimi Code、OpenCode 各有对应块标；感谢语仍按模型/供应商（Claude/GPT/Qwen…），不要把宿主 logo 当成模型名。
10. 用户切换语言时：
   - 英文：`--language en`
   - 中文：`--language zh-CN`
   - 如果用户直接说“中文版小票 / English receipt”，调用时就要带对这个参数。
11. 运行 `--show-fields` 可以查看当前日志里真实可读的字段。更详细说明见 `references/available-fields.md`。

## 架构

- `token_receipt/data.py`
  - 负责读取 Codex JSONL、Claude usage-data、Claude transcript model、Kimi Code context.jsonl、OpenCode SQLite、价格表和字段能力报告。
- `token_receipt/render.py`
  - 负责品牌头图、票面排版、footer、条形码和最终 receipt 文本。
- `token_receipt/hooks.py`
  - 负责 Claude Code `SessionEnd` hook 的 payload、安装和卸载。
- `scripts/token_receipt.py`
  - 只是 CLI 薄入口，不再堆所有业务逻辑。

## 触发策略

1. `Claude Code`
   - 对标 `claude-receipts` 的 `SessionEnd` hook。
   - 已提供安装器：`python3 scripts/install_claude_auto_trigger.py`
   - 已提供卸载器：`python3 scripts/uninstall_claude_auto_trigger.py`
   - 会话结束自动出 receipt；用户在会话中主动说“token receipt / token 小票 / 对话发票 / AI 用量账单”时也能触发。
2. `Codex`
   - 当前按触发词调用，不假设存在 `SessionEnd` hook。
3. `Kimi Code`（Moonshot kimi-cli）
   - `--agent-tool kimi-code`；可用环境变量 `KIMI_SESSION_ID` 指明会话，`KIMI_SHARE_DIR` 覆盖数据目录；或 `--session ~/.kimi/sessions/<hash>/<id>/context.jsonl`。
4. `OpenCode`
   - `--agent-tool opencode`；`OPENCODE_SESSION_ID`；`--session <opencode*.db> --opencode-session-id ses_...`；可选 `OPENCODE_DATA_DIR`。
5. `Trae`
   - 当前按触发词调用，不假设存在生命周期 hook。

## Kimi Code 一键示例

```bash
python3 scripts/token_receipt.py --agent-tool kimi-code
python3 scripts/token_receipt.py --session ~/.kimi/sessions/<hash>/<session-id>/context.jsonl
```

更细的触发词设计见 `references/trigger-phrases.md`。

## OpenCode 一键示例

```bash
python3 scripts/token_receipt.py --agent-tool opencode
python3 scripts/token_receipt.py --session ~/.local/share/opencode/opencode.db --opencode-session-id ses_xxx --scope session
```

## 视觉原则

- 默认宽度 48 字符；Logo 区可使用 `█░▒▓▐▛▜▌▘▝` 像素字符，金额区允许人民币符号 `¥`，其他票面尽量使用 ASCII。
- 顶部要像品牌小票，而不是普通表格：
  - Codex：使用用户指定的半色调像素标志 + `CODEX`。
  - Claude Code：使用参考图的像素螃蟹轮廓等比缩小版 + `CLAUDE CODE`。
  - Trae：使用用户指定的像素块标志 + `TRAE`。
  - Kimi Code：方块组成的标志 + `KIMI CODE`。
  - OpenCode：块状标志 + `OPENCODE`。
  - 未识别供应商：`AI CHECKOUT`。
- 中段用真实小票结构：`ITEM / TOKENS` 两列、横线分隔、数字右对齐。
- 三个工具通用的稳定票面字段固定为：`Input Tokens`、`Output Tokens`、`Cache Read Tokens`、`TOTAL`。这些字段只有能从日志或手动参数中查到时才打印；不要把未确认字段写上小票。
- 可选字段固定为：`Reasoning Tokens`、`Cache Write Tokens`。有真实字段就显示，没有就省略；其中 `Cache Write Tokens` 在 Codex 日志中通常没有，Anthropic cache 相关数据或手动参数提供时才显示。
- 当前 Codex 日志常见可读字段包括 `input_tokens`、`cached_input_tokens`、`output_tokens`、`reasoning_output_tokens`、`total_tokens`、`model_context_window`。
- 不再输出 `SCOPE LATEST-TURN`；改为 `CONTEXT USED`，展示本轮上下文输入量，若有上下文窗口则显示 `used/window`。
- `TOTAL` 要有视觉重量，底部必须有短口号、ASCII 条形码、receipt id。默认 footer 不是固定句库抽签，也不是 `subject/resource/artifact` 这类槽位拼句；它应该更像模型对这次对话的短吐槽或短鼓励。调用时优先用 `--conversation-summary` 传入当前对话一句话总结，也可以用自定义 `--footer`。
- 更详细的布局规则见 `references/receipt-style.md`。

## 验证

完成或修改 Skill 后至少运行：

```bash
python3 scripts/validate_receipt.py
```

它会检查行宽、必备字段、Claude block logo、条形码、未知价格降级，以及未固定字段不会被打印。
