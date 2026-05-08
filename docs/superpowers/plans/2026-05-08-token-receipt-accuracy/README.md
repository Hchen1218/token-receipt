# Token Receipt Accuracy & UX Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-08-token-receipt-accuracy-design.md`](../../specs/2026-05-08-token-receipt-accuracy-design.md)

**Goal:** Fix the token receipt under-reporting (451K → 30.6M tokens, $10.87 → $73–$104) for Claude Code on Bedrock, plus 10 related correctness and UX defects, via targeted extractions from `data.py` / `render.py` into three small modules.

**Architecture:** Three new modules carve single responsibilities out of today's 1117-line `data.py` and 1529-line `render.py`: `pricing.py` (cost math + TTL + PARTIAL status), `claude_aggregator.py` (walks `~/.claude/projects/**/*.jsonl` with sidechain+msg-id dedup), `bedrock.py` (normalizes `global.anthropic.claude-opus-4-7[1m]` → `aws bedrock` + `claude-opus-4.7`). Existing loaders stay intact; `resolve_snapshot` wires the new pieces behind new flags (`--cache-ttl`, `--hide-fields`, expanded `--scope`).

**Tech Stack:** Python 3 stdlib only. Tests use `unittest` (no new dependencies). Integration smoke-tests extend `scripts/validate_receipt.py`.

---

## How to read this plan

The plan is split into 11 parts, one file each, so you can hold one part in context at a time. Each part is independently reviewable and committable. Execute **in order**: Part 02 builds on Part 01, Part 03 on Part 02, and so on. Deviating from the order will break mid-state tests.

Every part contains:
- **Files** touched (exact paths + line ranges where known)
- **Bite-sized steps** (write failing test → run → implement → run → commit)
- **Full code** in every step — no "TODO" placeholders

After each part, tests pass and `scripts/validate_receipt.py` still passes. That's the gate for moving on.

## Part index

| # | File | Scope | Fix(es) |
|---|------|-------|---------|
| 01 | [`01-test-scaffold.md`](./01-test-scaffold.md) | Create `tests/` dir, `tests/__init__.py`, and a tiny runner shim. Land the unittest convention before any real tests. | infra |
| 02 | [`02-extract-pricing-module.md`](./02-extract-pricing-module.md) | Move existing `estimate_cost` / `find_price` / `load_pricing` verbatim from `data.py` to new `token_receipt/pricing.py`. Re-export from `data.py` for back-compat. Behavior-preserving. | refactor |
| 03 | [`03-pricing-json-cache-write-1h.md`](./03-pricing-json-cache-write-1h.md) | Add `cache_write_1h_per_million` field to all 10 anthropic entries in `references/pricing.json`. | #6 |
| 04 | [`04-snapshot-cache-write-fields.md`](./04-snapshot-cache-write-fields.md) | Extend `UsageSnapshot` with `cache_write_5m_tokens`, `cache_write_1h_tokens`, `aggregation_source`, `deduped_message_ids`, and extend `PriceEstimate` with `partial_reasons`. Tests for invariants. | #1, #6 |
| 05 | [`05-pricing-math-and-ttl.md`](./05-pricing-math-and-ttl.md) | Rewrite `estimate_cost` (remove clamp, add all 4 buckets), add `compute_total`, add `resolve_cache_write_split`, add `PARTIAL` status. Regression test uses the reported session numbers. | #1, #2, #3, #6 |
| 06 | [`06-bedrock-normalization.md`](./06-bedrock-normalization.md) | New `token_receipt/bedrock.py`: env detection, model-string normalization, provider rewrite. Wire into `resolve_snapshot`. | #4 |
| 07 | [`07-claude-aggregator.md`](./07-claude-aggregator.md) | New `token_receipt/claude_aggregator.py`: walk `~/.claude/projects/**/*.jsonl`, dedup by `isSidechain` + `message.id`, split `cache_creation.ephemeral_{5m,1h}_input_tokens`, return `UsageSnapshot`. | #7, #8 |
| 08 | [`08-cli-and-scope-wiring.md`](./08-cli-and-scope-wiring.md) | Add `--cache-ttl`, `--hide-fields`, expand `--scope` to include `today` and `session-all`, wire aggregator into `resolve_snapshot`, make `--write` silent. | #7, #9, #10 |
| 09 | [`09-render-changes.md`](./09-render-changes.md) | Gate `context_used` to `latest-turn`, build dynamic `summary_rows`, render `PARTIAL` with `*` and drop `PRICE DATE`. | #5, #6, #9 |
| 10 | [`10-skill-md-html-link.md`](./10-skill-md-html-link.md) | Update `SKILL.md` HTML-link template to `file:///tmp/...` so the link opens when clicked from chat. | #11 |
| 11 | [`11-validate-script-and-manual-regression.md`](./11-validate-script-and-manual-regression.md) | Extend `scripts/validate_receipt.py` with assertions for PARTIAL, Bedrock, hide-fields, silent `--write`, scope gating. Final manual regression check against the reported numbers. | regression |

## Defect → Part mapping (cross-reference)

| # | Defect | Primary part |
|---|--------|-------------|
| 1 | TOTAL misses cache buckets | 05 |
| 2 | USD misses cache read + cache write | 05 |
| 3 | No 1h TTL support | 05 |
| 4 | Bedrock host mis-labeled, model unmapped | 06 |
| 5 | `CONTEXT USED` wrong for non-latest-turn scopes | 09 |
| 6 | Price table partially populated but shown as vetted | 03, 04, 05, 09 |
| 7 | Session scope only reads single session-meta | 07, 08 |
| 8 | Subagent/sidechain duplication | 07 |
| 9 | Cannot hide receipt rows | 08, 09 |
| 10 | Noisy stdout with `--write` | 08 |
| 11 | HTML link not clickable from chat | 10 |

## Global conventions

- **Imports:** the project uses relative imports inside `token_receipt/`. New modules follow the same pattern (`from .models import ...`).
- **Formatting:** keep existing spacing and `from __future__ import annotations` at the top of each new file. No reformatting of untouched code.
- **Commits:** one commit per part (or per task inside a part when the part says so). Conventional style matching recent history: `feat:`, `fix:`, `refactor:`, `test:`. Do not add a `Co-Authored-By` line unless a parent committer explicitly asks — CHANGELOG tone stays human.
- **Test runner:** `python3 -m unittest discover -s tests -v`. No pytest fixtures, no third-party deps.
- **Validation script:** `python3 scripts/validate_receipt.py` must pass after every part.
- **Back-compat:** `snapshot.cache_write_tokens` remains the aggregate; `_5m` / `_1h` default to 0 for loaders that cannot split. `PriceEstimate` consumers that only check `status == "ESTIMATE"` keep working for unchanged entries; the new `PARTIAL` case is explicitly tested.
- **No speculative features:** only what the spec lists. No new pricing entries, no new loaders, no visual rework.

## Exit criteria

1. `python3 -m unittest discover -s tests -v` — all green.
2. `python3 scripts/validate_receipt.py` — exit 0.
3. Manual regression per spec §"Sanity check against the reported session": TOTAL ≈ 30,631,257; USD ≈ `$73.07` (5m) or `$103.74` (1h); `SUPPLIER: AWS BEDROCK`; `PRICE: claude-opus-4.7`.
4. `SKILL.md` chat example renders with `file:///tmp/token-receipt.html`.
