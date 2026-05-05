# Changelog

## 2026-05-05

### Added

- HTML receipt language toggle (`EN / 中文`) outside the receipt body
- External HTML tip panel with `15% / 18% / 20% / 25%` presets
- Conditional `SUBTOTAL / TIP / GRAND TOTAL` rows that only appear after tip selection

### Changed

- HTML tip mode now replaces the original footer instead of appending a tail
- Tip-aware footer generation now follows a separate tone path from the default receipt
- Chinese tip footers were rewritten to avoid template-heavy phrasing and cleaner HTML spacing

### Notes

- Tip controls stay outside the printable receipt surface until the user explicitly opts in
- Default chat receipts remain unchanged; tips are currently an HTML-only interaction layer

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
