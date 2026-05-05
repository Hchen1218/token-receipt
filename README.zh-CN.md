<div align="center">
  <p>
    <a href="./README.md">English</a> |
    <a href="./README.zh-CN.md">简体中文</a>
  </p>
  <h1>token-receipt</h1>
  <p><strong>把 AI 用量，打印成一张自带补刀的账单。</strong></p>
  <p>
    <code>ASCII-native</code>
    <code>pricing-aware</code>
    <code>software-aware</code>
    <code>Claude Code</code>
    <code>Codex</code>
    <code>Trae</code>
    <code>Kimi Code</code>
    <code>OpenCode</code>
  </p>
  <p>
    不是仪表盘。不是表格。不是自我安慰。
    <br />
    是一张在你开始合理化成本之前，先把账打出来的小票。
  </p>
</div>

## 这项目为什么存在

大多数 token 工具在“解释用量”。

`token-receipt` 在“给你结账”。

它把原本藏在后台的 AI 成本，变成一张热敏纸风格的小票。你可以直接贴进对话、截图发帖，或者把它当成“这轮到底烧了多少”的物证。

这个项目只有三条原则：

- `先有小票感，再有后台感`
  输出应该像结账，不像管理台。
- `口径必须诚实`
  先读本地真实日志，再谈官方价格；对不上就承认对不上。
- `结果必须可传播`
  不能只是“能看”，要达到“想发”。

---

## 预览

```text
                    ▐▛███▜▌
                   ▝▜█████▛▘
                     ▘▘ ▝▝
                  CLAUDE CODE

                 感谢使用 Claude
        小票号: CC_20260427_155533_9A83E3
            日期: 2026-04-27 15:55:33
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
供应商                                  ANTHROPIC
模型                            claude-sonnet-4.5
已用上下文                                  12,487
────────────────────────────────────────────────
项目                                        TOKEN
────────────────────────────────────────────────
输入 Tokens                                12,487
输出 Tokens                                 3,215
缓存读取                                     8,742
推理 Tokens                                   128
缓存写入                                     1,024
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总计                                15,702 Tokens
────────────────────────────────────────────────
USD 预估                                $0.062851
价格映射                         claude-sonnet-4.5
价格日期                                2026-04-25
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                画面稳了，预算死了。

         ||| |||||  ||||||| |||||||||  |
            CC_20260427_155533_9A83E3
```

---

## 怎么触发

`token-receipt` 有三种触发方式。

### 1. 在聊天里直接触发

如果你是把这个 repo 当 skill 装进软件里，正常用法不是先去终端里手动试命令。

正常用法是：就在你正在用的那个软件聊天框里，直接开口让它结账。

这些说法都应该触发：

- `token 小票`
- `对话发票`
- `AI 用量账单`
- `把这次对话打成小票`
- `看看这轮 token 消耗`
- `查看本次对话 Token 消耗`
- `token receipt`
- `token bill`
- `usage receipt`

如果你想指定语言，也可以直接说：

- `中文版 token 小票`
- `token receipt in English`

### 2. 让 Claude Code 自动触发

Claude Code 支持 `SessionEnd` 自动出票。

先安装 hook：

```bash
python3 scripts/install_claude_auto_trigger.py
```

装好以后，Claude Code 会话结束时就会自动出 receipt，不需要你再多说一句。

### 3. 直接跑 CLI

如果你不是通过 skill 触发，而是想手动直接跑脚本，就用：

```bash
python3 scripts/token_receipt.py --agent-tool codex
python3 scripts/token_receipt.py --agent-tool claude-code
python3 scripts/token_receipt.py --agent-tool kimi-code
python3 scripts/token_receipt.py --agent-tool opencode
python3 scripts/token_receipt.py --session ~/.local/share/opencode/opencode.db --opencode-session-id ses_xxx --agent-tool opencode
python3 scripts/token_receipt.py --agent-tool claude-code --language zh-CN
```

触发方式一览：

| 软件 | 聊天里手动触发 | 自动触发 |
| --- | --- | --- |
| Codex | 说 `token receipt` 或同义触发词 | 暂未提供 |
| Claude Code | 说 `token receipt` 或同义触发词 | 安装后支持 `SessionEnd` |
| Trae | 说 `token receipt` 或同义触发词 | 暂未提供 |
| Kimi Code | 说 `token receipt` 或同义触发词；CLI 可用 `--agent-tool kimi-code` | 暂未提供（读本地 `context.jsonl`） |
| OpenCode | 同上；CLI `--agent-tool opencode` 或指定 `opencode*.db` | 暂未提供（读本地 SQLite） |

---

## footer 才是亮点

footer 不是装饰。

footer 是最后那一刀。

这个项目的核心想法之一，就是让小票最后一行像模型看着你为了“再改一版”多烧了一轮上下文以后，冷冷留下一句评语。

例如：

- `画面稳了，预算死了。`
- `最后一版这个词，本来就不诚实。`
- `推理不免费，犹豫更贵。`
- `问题死了，账单活着。`

如果小票好看，但 footer 不够扎心，那这张票还没完成。

---

## 支持哪些软件

它会优先给你当前正在用的软件结账。
不会因为别的软件日志更新得更晚，就偷偷换源。

| 软件 | 当前状态 | 数据来源 | 说明 |
| --- | --- | --- | --- |
| Codex | `现在就支持` | Codex JSONL 会话 | 直接读本地会话日志 |
| Claude Code | `现在就支持` | Claude usage-data + projects | 用 usage log 取 token，用 transcript 辅助识别模型 |
| Trae | `当前先支持手动出票` | Trae 应用存储 | 自动导入暂未发版 |
| Kimi Code | `现在就支持` | kimi-cli `context.jsonl`（`~/.kimi/sessions/` 或 `KIMI_SHARE_DIR`） | 读 `_usage.token_count` 上下文累计；不做美元分项估算；要精确计价请用手动 `--input-tokens` / `--output-tokens` |
| OpenCode | `现在就支持` | `~/.local/share/opencode/opencode*.db`（可用 `OPENCODE_DATA_DIR`、`XDG_DATA_HOME`） | 读 SQLite 中 `message.data` 的 `tokens` / `modelID`；支持 `--scope latest-turn` / `session` |

补充说明：

- 部分 Trae 构建会使用 `Trae CN` / `.trae-cn` 命名。
- 在 Codex 里运行时，当前 runtime 可以被识别，`token-receipt` 会读 Codex 日志。
- 在 Claude Code 的 SessionEnd hook 里运行时，`token-receipt` 会读 Claude Code usage log。
- 如果你是在普通 shell 里直接运行，而且本机同时有多套软件日志，就要显式加 `--agent-tool`；现在不再允许跨软件猜最新日志。
- 目前版本里，`--agent-tool trae` 的态度是诚实的：它会明确告诉你先用手动模式，而不是假装 Trae 已经有稳定的 JSONL 会话日志可读。

---

## 支持哪些模型

这里分两层：

1. `小票渲染`
   手动模式下，任何模型名都能渲染到小票上。
2. `价格估算`
   只有在 `references/pricing.json` 里有映射的模型，才会显示价格。

当前已覆盖的模型家族包括：

- `OpenAI`
  GPT-5 家族、Codex 家族、GPT-4.1、GPT-4o、`o3`、`o4-mini`
- `Anthropic`
  Claude Opus / Sonnet / Haiku 家族
- `Google`
  Gemini 2.x / 3.x 家族
- `Moonshot`
  Kimi K2 家族
- `DeepSeek`
  DeepSeek V4 家族
- `Alibaba`
  Qwen 家族
- `Zhipu`
  GLM 家族
- `Xiaomi`
  MiMo 家族
- `MiniMax`
  M2 家族

如果你的模型还没进映射表，小票照样能出。

只是价格不会陪你一起演戏。

---

## 它到底读哪些字段

当前小票字段是故意收着打的：

- `Input Tokens`
- `Output Tokens`
- `Cache Read Tokens`
- `TOTAL`
- `Reasoning Tokens` 仅在真实可读时显示
- `Cache Write Tokens` 仅在真实可读时显示

这个策略是故意的。

宁可少打一项，也不乱打一项。

---

## 快速开始

目前不用装额外依赖，Python 标准库就能跑。

```bash
python3 scripts/token_receipt.py
```

如果是在 Codex 或 Claude Code 里面跑，当前软件可以被自动识别。
如果是在普通 shell 里跑，而且本机同时有多套软件日志，就要显式加 `--agent-tool`。

常用的软件级调用示例：

```bash
python3 scripts/token_receipt.py --agent-tool codex
python3 scripts/token_receipt.py --agent-tool claude-code
python3 scripts/token_receipt.py --agent-tool codex --scope session
python3 scripts/token_receipt.py --agent-tool claude-code --show-fields
python3 scripts/token_receipt.py --agent-tool trae --provider openai --model gpt-5.4 --input-tokens 12487 --output-tokens 3215
```

常用的渲染参数：

```bash
python3 scripts/token_receipt.py --width 48 --stream
python3 scripts/token_receipt.py --agent-tool codex --language en
python3 scripts/token_receipt.py --agent-tool claude-code --language zh-CN
python3 scripts/token_receipt.py --agent-tool claude-code --output html --write ./receipt.html
python3 scripts/token_receipt.py --agent-tool claude-code --session ~/.claude/usage-data/session-meta/${CLAUDE_SESSION_ID}.json --write /tmp/token-receipt.txt
python3 scripts/token_receipt.py --footer-tone snarky --conversation-summary "one more revision for visual polish"
python3 scripts/token_receipt.py --provider anthropic --agent-tool claude-code --model claude-sonnet-4.5 --input-tokens 12487 --cached-input-tokens 8742 --output-tokens 3215
```

在 Claude Code 的 skill 上下文里，`${CLAUDE_SESSION_ID}` 会被替换成当前会话 id。

这些参数翻译成人话：

- `--agent-tool codex`
  读 Codex 的数据，并使用 Codex 的票头。
- `--agent-tool claude-code`
  读 Claude Code 的数据，并使用 Claude Code 的票头。
- `--agent-tool trae`
  用 Trae 的票头。当前请自带 token 数字。
- `--show-fields`
  先问日志：你到底能证明哪些字段是真的。
- `--language en`
  打印英文版小票。
- `--language zh-CN`
  打印中文版小票，但不另起一套排版逻辑。
- `--output html`
  导出一张适合浏览器打印的 HTML 小票页面，而不是聊天里的 monospace 版本。
- `--write /tmp/token-receipt.txt`
  把小票静默写进文件，不往 Bash stdout 里刷屏。这是 Claude Code 聊天里更干净的调用方式。
- `--write-html /tmp/token-receipt.html`
  保持文本小票还是主输出，但额外落一份可打印 HTML，方便在支持本地文件链接的宿主里一起回给用户。
- `--stream`
  让它像一台知道你花多了的小票机一样吐单。

---

## 可打印 HTML

聊天里的 monospace 小票仍然是主输出。

HTML 是第二出口：适合走浏览器打印预览、连真实打印机，或者接热敏纸工作流。

```bash
python3 scripts/token_receipt.py --agent-tool claude-code --output html --write ./receipt.html
```

把 `receipt.html` 用浏览器打开，点一下 `Print receipt`，剩下的交给浏览器和打印机。

如果宿主支持本地文件链接，更顺手的做法是双导出：

```bash
python3 scripts/token_receipt.py --agent-tool claude-code --write /tmp/token-receipt.txt --write-html /tmp/token-receipt.html
```

这样聊天里保留 monospace 小票，同时还能顺手附上一份可点击的打印版 HTML。

这一版的 HTML 主要盯住了三件最容易被看出来的事：

- 屏幕上有一层淡灰背景板，小票本体保持白色，边界更清楚
- 真正打印时仍然是纯白票面，不会把预览背景一起带上纸
- HTML 里也按软件切 logo：Claude Code 用单独的矢量标，Codex 和 Trae 用嵌入式图片素材

现在它也不只是“导出一张静态网页”了，而更像一个真的收银台界面：

- 小票外有 `EN / 中文` 切换，不用重新生成文件也能直接换语言
- 小票外有 `加一点小费` 面板，控制项不印进纸里，默认票面更干净
- 只有真的选了小费比例，票内才会出现 `小计 / 小费 / 应付总额`
- 进入小费模式后，footer 会直接改写，不是在原句后面硬拼一句感谢语
- 小费态的 footer 会明显换口气：默认小票更冷，给了小费以后会更会来事、更领情

---

## Claude Code 自动出票

安装：

```bash
python3 scripts/install_claude_auto_trigger.py
```

卸载：

```bash
python3 scripts/uninstall_claude_auto_trigger.py
```

这会把 `token-receipt` 接进 Claude Code 的 `SessionEnd` hook。

对话结束。

账单出现。

嘴硬窗口关闭。

---

## 这个项目的脾气

这个项目故意不“温柔”。

- 不把主输出做成 Markdown 表格
- 先不做二维码
- 别的工具有的字段，这里不一定照单全收
- 平台路由价，不会伪装成厂商直连价
- 保留那种“真像一张账单”的别扭劲儿

如果输出太干净，往往说明它已经不够真实了。

---

## 验证

改完东西以后，至少跑这一条：

```bash
python3 scripts/validate_receipt.py
```

它会帮你确认：

- 行宽没炸
- 必备字段还在
- logo 没歪
- 条形码还活着
- 价格降级逻辑没坏
- 没把不该打印的字段偷偷打上票面

---

## 更新日志

持续更新记录见 [CHANGELOG.md](/Users/cecilialiu/Documents/Codex/token-receipt/CHANGELOG.md)。

---

## 更新计划

- `现在已经有`
  可打印 HTML 导出，方便走浏览器打印预览和实体小票机。
- `接下来会做`
  更适合常见纸宽的打印预设，以及更干净的打印默认样式。
- `后面准备补`
  Trae 的自动会话导入，前提是本地存储结构足够稳定，值得信。

---

## 最后一刀

每一次提示词，都会留下账单。

`token-receipt` 只是比你的心理防线更早把它打印出来。

---

> 灵感来自 [chrishutchinson/claude-receipts](https://github.com/chrishutchinson/claude-receipts)。  
> 同样是 receipt 的直觉，不同的是语气更黑，软件更多，footer 更狠。
