<div align="center">
  <p>
    <a href="./README.md">English</a> |
    <a href="./README.zh-CN.md">简体中文</a>
  </p>
  <h1>token-receipt</h1>
  <p><strong>Turn AI token usage into a receipt with a punchline.</strong></p>
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
    No dashboard. No spreadsheet. No spiritual coping mechanism.
    <br />
    Just a bill that shows up before your denial does.
  </p>
</div>

## Why this exists

Most token tools explain usage.

`token-receipt` itemizes the damage.

It turns invisible AI spend into a thermal-paper artifact you can paste into chat, screenshot instantly, and post with a straight face.

Three rules run the whole project:

- `Visual first`
  The output should look like checkout, not admin UI.
- `Data honest`
  Real local logs first. Official pricing second. Unknowns stay unknown.
- `Artifact over analytics`
  If it is not screenshot-worthy, it is not finished.

---

## Preview

```text
                    ▐▛███▜▌
                   ▝▜█████▛▘
                     ▘▘ ▝▝
                  CLAUDE CODE

        THANK YOU FOR CODING WITH Claude
      RECEIPT #: CC_20260427_151928_7CE382
           DATE: 2026-04-27 15:19:28
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROVIDER                               ANTHROPIC
MODEL                          claude-sonnet-4.5
CONTEXT USED                              12,487
────────────────────────────────────────────────
ITEM                                      TOKENS
────────────────────────────────────────────────
Input Tokens                              12,487
Output Tokens                              3,215
Cache Read Tokens                          8,742
Reasoning Tokens                             128
Cache Write Tokens                         1,024
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL                              15,702 TOKENS
────────────────────────────────────────────────
USD ESTIMATE                           $0.062851
PRICE                          claude-sonnet-4.5
PRICE DATE                            2026-04-25
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    THE LOGO LOOKS CALM. THE BILL DOES NOT.

        ||| ||||| || ||| | | || |||  | |
           CC_20260427_151928_7CE382
```

### The footer is the feature

The footer is not decoration.
It is the coup de grace.

This project is built around the idea that the last line on the receipt should feel like the model watched you spend context on one more revision and decided to leave a note.

That now splits into two modes:

- the default receipt footer stays cold and mildly hostile
- the HTML tip flow can switch the receipt into a different closing voice, where the footer gets more grateful, more performative, and much more aware that you just added money on top
- in tip mode, English footers no longer keep starting from the product name, and Chinese footers now actually react to tone and bill weight instead of pretending to

Examples:

- `THE LOGO LOOKS CALM. THE BILL DOES NOT.`
- `REASONING WAS BILLED SEPARATELY.`
- `THE LAST REVISION WAS NOT THE LAST.`
- `画面稳了，预算死了。`
- `最后一版这个词，本来就不诚实。`

If the user adds a tip in HTML, the footer is rewritten instead of extended.
It stops acting like a dry bill and starts acting like a register that knows you tipped.

If the receipt looks good but the footer has no sting, the job is not done.

---

## How to trigger it

### 1. Trigger it inside chat

If you installed this repo as a skill, the normal path is not “open terminal and figure it out.”

The normal path is: say what you want in the chat box of the software you are already using.

Strong trigger phrases:

- `token receipt`
- `token bill`
- `usage receipt`
- `token 小票`
- `对话发票`
- `AI 用量账单`
- `把这次对话打成小票`
- `看看这轮 token 消耗`
- `查看本次对话 Token 消耗`

You can also be explicit about language:

- `token receipt in English`
- `中文版 token 小票`

### 2. Let Claude Code do it automatically

Claude Code can auto-print a receipt on `SessionEnd`.

Install the hook:

```bash
python3 scripts/install_claude_auto_trigger.py
```

After that, ending a Claude Code session will auto-fire the receipt without an extra chat message.

---

## Software support

It bills the software you are actually using.
It does not quietly switch to another app's newer logs.

| Software | Status | Data source | Notes |
| --- | --- | --- | --- |
| Codex | `supported now` | Codex JSONL sessions | Reads local session logs directly |
| Claude Code | `supported now` | Claude usage-data + projects | Uses usage logs for tokens and transcripts for model lookup |
| Trae | `manual mode now` | Trae app storage | Auto transcript import is not shipped yet |
| Kimi Code | `supported now` | kimi-cli `context.jsonl` (`~/.kimi/sessions/` or `KIMI_SHARE_DIR`) | Reads cumulative `_usage.token_count`; USD estimate omitted (no API split); use manual flags if you need priced input/output |
| OpenCode | `supported now` | `opencode*.db` SQLite under `~/.local/share/opencode/` (see `OPENCODE_DATA_DIR`, `XDG_DATA_HOME`) | Reads `session`/`message` rows (`message.data` JSON: `tokens`, `modelID`); supports `--scope latest-turn` \| `session` |

Notes:

- Some Trae builds use `Trae CN` / `.trae-cn` instead of `Trae`.
- Inside Codex, the runtime can be detected and `token-receipt` reads Codex logs.
- Inside Claude Code's SessionEnd hook, `token-receipt` reads Claude Code usage logs.
- If you run the script from a plain shell and more than one local software log exists, pass `--agent-tool` explicitly. Cross-software guessing is intentionally disabled.
- In current releases, `--agent-tool trae` is honest: it tells you to use manual mode instead of pretending Trae has clean JSONL session logs.

---

## Model coverage

There are two layers of support:

1. `Receipt rendering`
   Any model name can be rendered in manual mode.
2. `Price estimation`
   Cost only shows up when the model exists in `references/pricing.json`.

Current mapped model families include:

- `OpenAI`
  GPT-5 family, Codex family, GPT-4.1, GPT-4o, `o3`, `o4-mini`
- `Anthropic`
  Claude Opus, Sonnet, and Haiku families
- `Google`
  Gemini 2.x and 3.x families
- `Moonshot`
  Kimi K2 family
- `DeepSeek`
  DeepSeek V4 family
- `Alibaba`
  Qwen family
- `Zhipu`
  GLM family
- `Xiaomi`
  MiMo family
- `MiniMax`
  M2 family

If your model is not mapped yet, the receipt still renders.
The price just refuses to roleplay.

---

## What it actually reads

Current receipts intentionally stay conservative about what they print:

- `Input Tokens`
- `Output Tokens`
- `Cache Read Tokens`
- `TOTAL`
- `Reasoning Tokens` when actually available
- `Cache Write Tokens` when actually available

That policy is deliberate.

Better to omit a field than lie with confidence.

---

## Printable HTML

The main artifact is still the monospace receipt inside chat.

HTML is the secondary route: useful when you want browser print preview, real printer output, or a cleaner handoff to thermal-printer workflows.

```bash
python3 scripts/token_receipt.py --agent-tool claude-code --output html --write ./receipt.html
```

Open `receipt.html` in a browser, hit `Print receipt`, and let the browser talk to the printer.

If your host can render local file links, the cleaner flow is dual export:

```bash
python3 scripts/token_receipt.py --agent-tool claude-code --write /tmp/token-receipt.txt --write-html /tmp/token-receipt.html
```

That keeps the monospace receipt in chat while also giving you a clickable printable HTML file.

The current HTML path is tuned for the same three things people actually notice:

- a gray preview stage with a white receipt body, so the receipt edges stay visible on screen
- a pure white print result, so the browser preview does not lie about the final paper
- software-aware logos in HTML too: Claude Code uses a dedicated vector mark, while Codex and Trae use embedded image assets

And now it behaves more like a live checkout surface instead of a dead export:

- an `EN / 中文` toggle outside the receipt, so one printable page can flip languages without regenerating the file
- an external `Add tip` panel, so the controls stay off the paper until you explicitly opt in
- the tip panel only appears when the receipt has a real priced subtotal; unmapped receipts do not fake a gratuity flow
- `SUBTOTAL / TIP / GRAND TOTAL` only show up inside the receipt after a tip is selected
- tip mode replaces the original footer entirely; it does not bolt a canned thank-you tail onto the end
- tipped receipts switch into a different checkout voice: less cold, more grateful, more willing to flatter you for the extra money
- language switching now updates the page state as well, so the browser preview is not only visually switched but also semantically in the right language

---

## Claude Code auto-trigger

Install:

```bash
python3 scripts/install_claude_auto_trigger.py
```

Uninstall:

```bash
python3 scripts/uninstall_claude_auto_trigger.py
```

This wires `token-receipt` into Claude Code's `SessionEnd` hook.

The conversation ends.
The receipt arrives.
The denial window closes.

---

## Changelog

See [CHANGELOG.md](/Users/cecilialiu/Documents/Codex/token-receipt/CHANGELOG.md) for the running update log.

---

## Roadmap

- `Shipped now`
  Printable HTML export with language switching, external tip controls, and a live checkout-style print surface.
- `Next up`
  Printer-first presets for common paper widths and cleaner print defaults.
- `Also planned`
  Trae automatic session import once its local storage shape is stable enough to trust.

---

## One-line thesis

Every prompt leaves a tab.

`token-receipt` just prints it before you can emotionally recover.

---

> Inspired by [chrishutchinson/claude-receipts](https://github.com/chrishutchinson/claude-receipts).  
> Same receipt instinct. Different attitude. More software. Meaner footer.
