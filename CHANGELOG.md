# Changelog

## 2026-05-08

### Added
- `--cache-ttl {auto,5m,1h}` — controls which Anthropic cache-write rate is billed
- `--hide-fields supplier,model,context,price-mapping,price-date,rate-note` — drops rows from the receipt
- `--scope today` and `--scope session-all` for Claude Code aggregation across `~/.claude/projects/**/*.jsonl`
- `PARTIAL` pricing status — rendered as `USD ESTIMATE*` + `PRICE: PARTIAL` (no PRICE DATE) when the rate table is incomplete
- `cache_write_1h_per_million` in every anthropic entry of `references/pricing.json`

### Fixed
- `TOTAL` now includes cache read and cache write tokens (previously undercounted by 50×+ on cache-heavy sessions)
- `USD ESTIMATE` now bills cached input and cache write at their own rates instead of dropping them (previously undercounted by 5–10×)
- `PROVIDER` and `MODEL` auto-detect AWS Bedrock from `CLAUDE_CODE_USE_BEDROCK=1` or `<region>.anthropic.*[1m]` model strings
- `CONTEXT USED` row is suppressed for `--scope session`, `today`, and `session-all` (was rendering a meaningless value)
- `--write` is fully silent; `--write --write-html` prints exactly two `wrote to:` lines
- `SKILL.md` HTML link example now uses `file:///tmp/...` so chat clients can open it

### Changed
- `--scope session` for Claude Code now reads the jsonl transcripts and dedupes sidechain/subagent branches, not just the current session-meta file
- Pricing, Bedrock normalization, and Claude aggregation live in new single-purpose modules under `token_receipt/`

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
