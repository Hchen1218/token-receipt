# Changelog

## 2026-06-05

### Added

- Dedicated `token_receipt/pricing.py` module so pricing lookup, total fallback, and cost estimation can be tested independently
- New unit test suite covering pricing math, total-token fallback, Claude runtime session detection, chat-reply link formatting, and session-scope context rendering
- Refreshed pricing entries and aliases for newer model names including `ChatGPT 5.5`, `chat-latest`, `claude-opus-4.8`, `MiniMax 3`, and `MiMo V2.5 Pro`

### Changed

- Corrected total-token fallback so manual and Claude usage snapshots now sum every billable bucket instead of defaulting to `input + output`
- Corrected cost estimation so `cached_input_tokens` and `cache_write_tokens` are billed independently instead of being clamped by `input_tokens`
- Claude runtime session detection now prefers `CLAUDE_CODE_SESSION_ID` and falls back to `CLAUDE_SESSION_ID`
- `--chat-reply` and Claude hook messages now emit local Printable HTML links as `file://` URIs instead of raw filesystem paths
- Session-scope receipts now suppress `CONTEXT USED` to avoid presenting an accumulated view as if it were a single-turn context reading
- Smoke coverage in `scripts/validate_receipt.py` now checks the corrected cache-heavy totals/costs, the `file://` HTML link format, session-scope context suppression, and the newer model aliases/prices

### Notes

- An Anthropic-style baseline comparison run was recorded locally at `/tmp/token-receipt-core-correctness-workspace/iteration-1`
- In that validation round, the current version passed all eval assertions while the baseline version passed 22%, with the main regressions concentrated in cache billing math, local HTML link formatting, session-scope context display, and new-model price resolution

## 2026-05-05

### Added

- Unified `--chat-reply` mode for supported software, which returns the receipt code block and a local Printable HTML link in one shot
- HTML receipt language toggle (`EN / 中文`) outside the receipt body
- External HTML tip panel with `15% / 18% / 20% / 25%` presets
- Conditional `SUBTOTAL / TIP / GRAND TOTAL` rows that only appear after tip selection
- Tip controls now only appear for receipts with a real priced subtotal

### Changed

- HTML tip mode now replaces the original footer instead of appending a tail
- Tip-aware footer generation now follows a separate tone path from the default receipt
- HTML now uses raw footer lines for tip mode, which fixes Chinese spacing artifacts and keeps footer replacement clean
- Chinese tip footers were rewritten into a more checkout-like, more grateful voice instead of template-heavy phrasing
- Chinese tip footers now actually respond to style and bill-state signals instead of only scene + tip level
- English tip footers no longer keep repeating the product name as the sentence subject
- HTML language switching now updates the page-level `lang` state instead of only swapping the visible receipt

### Notes

- Tip controls stay outside the printable receipt surface until the user explicitly opts in
- Claude Code `SessionEnd` hook now follows the same text-plus-HTML reply path
- Default chat receipts still stay text-first; tips are currently an HTML-only interaction layer

## 2026-04-29

### Added

- Printable HTML export via `--output html`
- Quiet file output via `--write`
- Dual export support via `--write-html`, so text receipts can also drop a printable HTML file in the same run
- Embedded HTML logo assets for Codex and Trae
- Dedicated SVG logo path for Claude Code in HTML
- HTML smoke coverage in `scripts/validate_receipt.py`

### Changed

- Split receipt rendering into a shared `ReceiptView`, so text and HTML outputs use the same receipt data model
- Tuned HTML preview to look like a real receipt workflow: gray stage on screen, white paper when printed
- Switched HTML layout sizing to printer-like measurements for more stable print proportions
- Tightened HTML row layout so longer fields such as context usage stay on one line more reliably

### Notes

- Chat receipts remain the primary artifact
- HTML is still the secondary route for browser print preview and physical printer workflows
