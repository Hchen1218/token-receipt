# Token Receipt Accuracy & UX Rework — Design

Date: 2026-05-08
Status: Draft for review
Scope: All 11 reported issues, one coherent redesign

## Problem

The token-receipt skill under-reports token totals and USD cost when used against Claude Code on AWS Bedrock, the typical path today. Observed on a real session:

- `TOTAL` printed `451,257` tokens (input + output only) while the actual usage was ~30.6M once cache read and cache write are counted.
- `USD ESTIMATE` printed `$10.87` while the realistic cost was ~$73 (5m TTL) or ~$104 (1h TTL).
- Receipt still advertised `PRICE: claude-opus-4.7` + `PRICE DATE: 2026-04-25` giving the false impression the estimate was vetted.
- Bedrock host was mis-labeled `anthropic` and the model string `global.anthropic.claude-opus-4-7[1m]` never matched the price table without a manual `--provider` override.
- Default data source only read a single session-meta file, so multi-session/multi-project days could not be billed without hand-aggregation.
- Secondary UX bugs: noisy stdout with `--write`, `CONTEXT USED` shown for accumulation scopes where it is meaningless, `Printable HTML` link fails to open from chat, no way to hide rows.

All 11 defects share a root: the cost estimator, aggregation layer, and surface rendering are tangled inside a 1117-line `data.py` and a 1529-line `render.py`, making each correctness fix double as a refactor risk.

## Goals

1. Numbers on the receipt are correct: total tokens cover all four buckets; USD includes cache read + cache write at their own rates; 1h TTL supported.
2. Receipt is honest: when the price table is incomplete or the scope makes a field meaningless, say so (`PRICE: PARTIAL`, drop `CONTEXT USED`) instead of rendering pretty-but-wrong.
3. Claude Code on Bedrock works without manual `--provider` and `--model` flags.
4. Default Claude Code data path covers a whole day of usage across all projects, with sidechain/subagent dedup.
5. Output surface is clean: `--write` stays silent, HTML link opens when clicked.
6. Code boundaries allow each concern to be tested and changed independently.

## Non-goals

- Changing Codex, Kimi Code, OpenCode, or Trae loaders except where they touch the shared pricing module.
- Expanding the price table beyond adding `cache_write_1h_per_million` fields.
- A new receipt visual style; existing layout stays.
- Retroactive CloudWatch reconciliation or live billing-API integration.

## Architecture

Three new modules + targeted edits. Each new module has one reason to change.

```
token_receipt/
  pricing.py            # NEW  rate lookup, TTL resolution, cost math, PARTIAL status
  claude_aggregator.py  # NEW  walks ~/.claude/projects/**/*.jsonl, dedup, time filter
  bedrock.py            # NEW  provider/model normalization for Bedrock
  data.py               # EDIT loaders + runtime detection, delegates to above
  render.py             # EDIT dynamic summary_rows, context gating, PARTIAL render
  cli.py                # EDIT new flags: --cache-ttl, --hide-fields, scope values
  models.py             # EDIT UsageSnapshot + PriceEstimate fields
references/
  pricing.json          # EDIT add cache_write_1h_per_million per anthropic entry
SKILL.md                # EDIT HTML link template: file:///tmp/...
scripts/
  validate_receipt.py   # EDIT assertions for PARTIAL, hide-fields, Bedrock, totals
```

Boundaries:

- `pricing.py` owns "how much did this cost". Fixes #1, #2, #3, #6.
- `claude_aggregator.py` owns "which Claude Code records belong to this receipt". Fixes #7, #8.
- `bedrock.py` owns "what does this Bedrock model map to in pricing.json". Fixes #4.
- `render.py` only decides what rows are visible. Fixes #5, #9.
- `cli.py` wires new flags and silences `--write`. Fixes #10.
- `SKILL.md` fixes the chat-link format. Fixes #11.

## Data model

### `UsageSnapshot` (models.py)

```python
@dataclass
class UsageSnapshot:
    # existing fields unchanged
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0          # aggregate, kept for back-compat
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    context_window: Optional[int] = None
    context_tokens: Optional[int] = None
    provider: str = "unknown"
    model: str = "UNRECORDED"
    source: str = ""
    session_id: str = ""
    timestamp: Optional[str] = None
    scope: str = "latest-turn"           # expanded values below
    available_fields: tuple[str, ...] = ()

    # NEW
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    aggregation_source: Optional[str] = None  # "session-meta" | "projects-jsonl" | "manual" | "codex-jsonl" | ...
    deduped_message_ids: int = 0              # diagnostic, exposed via --show-fields
```

Invariant: `cache_write_tokens == cache_write_5m_tokens + cache_write_1h_tokens` when a loader can distinguish. Loaders that cannot (session-meta, codex) set the aggregate only and leave `_5m` / `_1h` at 0; the TTL resolver then decides.

`scope` values expand from `("latest-turn", "session")` to `("latest-turn", "session", "today", "session-all")`.

### `PriceEstimate` (models.py)

```python
@dataclass
class PriceEstimate:
    status: str    # "ESTIMATE" | "UNMAPPED" | "PARTIAL"    (PARTIAL is NEW)
    amount: Optional[float]
    model: str = ""
    currency: str = "USD"
    source_url: str = ""
    source_checked_at: str = ""
    rate_note: str = ""
    partial_reasons: tuple[str, ...] = ()   # NEW  e.g. ("cache_write_1h_per_million",)
```

`PARTIAL` semantics: we found a matching entry and produced an amount, but at least one rate we actually needed was missing and we substituted a documented fallback. Render drops the `PRICE DATE` row in this case to avoid the "already vetted" illusion.

### `pricing.json` (references/)

Per entry, add optional `cache_write_1h_per_million`. Example:

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4.7",
  "input_per_million": 5.0,
  "cached_input_per_million": 0.5,
  "cache_write_5m_per_million": 6.25,
  "cache_write_1h_per_million": 10.0,
  "output_per_million": 25.0,
  "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
  "source_checked_at": "2026-04-25"
}
```

Populate for all anthropic entries in this rework. Missing ⇒ PARTIAL.

## Cost estimator (pricing.py)

### Total tokens — fix #1

```python
def compute_total(snapshot: UsageSnapshot) -> int:
    return (
        snapshot.input_tokens
        + snapshot.output_tokens
        + snapshot.cached_input_tokens
        + snapshot.cache_write_tokens
        + snapshot.reasoning_output_tokens
    )
```

Used only when the source did not supply its own `total_tokens`. Session-meta and codex jsonl both carry an authoritative total; keep using it. Manual mode and the new aggregator path compute via this function.

### Cache-write TTL resolution — fix #3

```python
def resolve_cache_write_split(snapshot, cli_override=None, env=None):
    env = env or os.environ

    # 1. explicit CLI override wins
    if cli_override == "5m":
        return (snapshot.cache_write_tokens, 0)
    if cli_override == "1h":
        return (0, snapshot.cache_write_tokens)

    # 2. per-message split carried by the snapshot
    if snapshot.cache_write_5m_tokens or snapshot.cache_write_1h_tokens:
        return (snapshot.cache_write_5m_tokens, snapshot.cache_write_1h_tokens)

    # 3. Claude Code Bedrock 1h env flag
    if env.get("ENABLE_PROMPT_CACHING_1H_BEDROCK", "").strip() in ("1", "true", "TRUE"):
        return (0, snapshot.cache_write_tokens)

    # 4. default to 5m
    return (snapshot.cache_write_tokens, 0)
```

`cli_override` is the value of `--cache-ttl` (`auto` passes `None`).

### Cost math — fix #2

```python
def estimate_cost(snapshot, pricing_path, cache_ttl_override=None) -> PriceEstimate:
    if snapshot.skip_price_estimate:
        return PriceEstimate(status="UNMAPPED", amount=None)

    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    missing = []

    input_rate  = entry.get("input_per_million")
    output_rate = entry.get("output_per_million")
    cached_rate = entry.get("cached_input_per_million", input_rate)
    write_5m    = entry.get("cache_write_5m_per_million", input_rate)
    write_1h    = entry.get("cache_write_1h_per_million")

    split_5m, split_1h = resolve_cache_write_split(snapshot, cache_ttl_override)

    if split_1h > 0 and write_1h is None:
        missing.append("cache_write_1h_per_million")
        write_1h = (input_rate or 0) * 2.0   # documented Anthropic 1h fallback ratio

    amount = (
        snapshot.input_tokens        * (input_rate  or 0)
      + snapshot.cached_input_tokens * (cached_rate or 0)
      + split_5m                     * write_5m
      + split_1h                     * write_1h
      + (snapshot.output_tokens + snapshot.reasoning_output_tokens) * (output_rate or 0)
    ) / 1_000_000

    if input_rate is None:
        missing.append("input_per_million")
    if output_rate is None:
        missing.append("output_per_million")

    status = "PARTIAL" if missing else "ESTIMATE"
    return PriceEstimate(
        status=status,
        amount=amount,
        model=str(entry.get("model", snapshot.model)),
        currency=str(entry.get("currency", pricing.get("currency", "USD"))).upper(),
        source_url=str(entry.get("source_url", "")),
        source_checked_at=str(entry.get("source_checked_at", "")),
        rate_note=str(entry.get("rate_note", "")),
        partial_reasons=tuple(missing),
    )
```

The key change vs current: the `min(cached_input_tokens, input_tokens)` clamp is removed. `cached_input_tokens` and `cache_write_tokens` are independent counts on the Anthropic schema, not subsets of `input_tokens`.

### Sanity check against the reported session

Input 16,897, output 434,360, cache read 22M, cache write 8.18M, Opus 4.7 on Bedrock:

- Current (buggy clamp): treats all 16,897 as cached @ $0.5/M, ignores cache read + cache write → `16,897 × $0.5/M + 434,360 × $25/M = $0.008 + $10.86 = $10.87`, total tokens `451,257`.
- New (5m TTL): input `$0.08` + cache-read `$11.00` + cache-write `$51.13` + output `$10.86` = **`$73.07`**, total tokens `~30.63M`.
- New (1h TTL): input `$0.08` + cache-read `$11.00` + cache-write `$81.80` + output `$10.86` = **`$103.74`**, total tokens `~30.63M`.

## Claude-projects aggregator (claude_aggregator.py)

### Default data source change — fix #7

After this rework, `--agent-tool claude-code` default behavior:

| `--scope` value | Data source | Notes |
|---|---|---|
| `latest-turn` (default) | `~/.claude/usage-data/session-meta/<sid>.json` | unchanged |
| `session` | `~/.claude/projects/**/*.jsonl` filtered by `sessionId` | CHANGED: was session-meta cumulative |
| `today` | `~/.claude/projects/**/*.jsonl` filtered by `local_midnight(now) <= timestamp < now` | NEW |
| `session-all` | `~/.claude/projects/**/*.jsonl` filtered by `sessionId` across time | NEW |

Rationale for switching default `session` to jsonl: session-meta only covers the current session file; the jsonl transcripts are the authoritative usage log Claude Code writes. With dedup, the jsonl total is more accurate than summing session-meta across multiple files by hand.

### Dedup strategy — fix #8

Two layers, both applied in `aggregate_claude_projects`:

1. Skip lines with `isSidechain == True`. These are subagent branches; the parent session already records the same usage.
2. Track `seen_message_ids: set[str]` keyed on `line["message"]["id"]` (Anthropic `msg_*`). First occurrence wins.
3. Fallback key when `message.id` missing: `(sessionId, uuid)`.

### Extraction per line

```python
def extract_usage(line: dict) -> Optional[dict]:
    if line.get("type") != "assistant":
        return None
    if line.get("isSidechain") is True:
        return None
    msg = line.get("message") or {}
    usage = msg.get("usage") or {}
    ephemeral = usage.get("cache_creation") or {}
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "cached_input_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_write_5m_tokens": ephemeral.get("ephemeral_5m_input_tokens", 0),
        "cache_write_1h_tokens": ephemeral.get("ephemeral_1h_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "model": msg.get("model"),
        "message_id": msg.get("id"),
        "timestamp": line.get("timestamp"),
        "session_id": line.get("sessionId"),
        "uuid": line.get("uuid"),
    }
```

### Aggregator signature

```python
def aggregate_claude_projects(
    since: datetime,
    until: datetime,
    *,
    session_id: Optional[str] = None,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> UsageSnapshot:
    ...
```

Returns a `UsageSnapshot` with `aggregation_source="projects-jsonl"`, `deduped_message_ids=<count>`, and token buckets summed across kept lines.

## Bedrock normalization (bedrock.py)

Fixes #4. ~30 lines.

```python
BEDROCK_MODEL_PREFIXES = (
    "global.anthropic.",
    "us.anthropic.",
    "eu.anthropic.",
    "apac.anthropic.",
)

def is_bedrock_env(env=None) -> bool:
    env = env or os.environ
    return env.get("CLAUDE_CODE_USE_BEDROCK", "").strip() in ("1", "true", "TRUE")

def looks_like_bedrock_model(model: str) -> bool:
    return any(model.startswith(p) for p in BEDROCK_MODEL_PREFIXES)

def normalize_bedrock_model(model: str) -> str:
    for p in BEDROCK_MODEL_PREFIXES:
        if model.startswith(p):
            model = model[len(p):]
            break
    model = re.sub(r"\[[^\]]*\]$", "", model)              # strip [1m] etc.
    model = re.sub(r"^(claude-[a-z]+-\d+)-(\d+)$", r"\1.\2", model)  # "claude-opus-4-7" → "claude-opus-4.7"
    return model

def resolve_provider_and_model(raw_provider, raw_model, env=None):
    if is_bedrock_env(env) or looks_like_bedrock_model(raw_model):
        return ("aws bedrock", normalize_bedrock_model(raw_model))
    return (raw_provider, raw_model)
```

Called once in `resolve_snapshot(args)` after the loader returns and before `estimate_cost`. Receipt prints `SUPPLIER: AWS BEDROCK`; price lookup uses the normalized string against the existing anthropic entries. No new pricing entries needed — Bedrock on-demand matches Anthropic list prices.

Explicit `--provider` / `--model` flags still win if the user passes them.

## Render changes (render.py)

### `context_used` — fix #5

```python
def context_used(snapshot):
    if snapshot.scope != "latest-turn":
        return None   # drop the row entirely
    if snapshot.context_tokens is not None:
        used_src = snapshot.context_tokens
    else:
        used_src = snapshot.input_tokens
    used = fmt_int(used_src)
    return f"{used}/{fmt_int(snapshot.context_window)}" if snapshot.context_window else used
```

### Dynamic `summary_rows` + `--hide-fields` — fix #9

Replace the hard-coded tuple with a builder:

```python
HIDEABLE_FIELDS = frozenset({
    "supplier", "model", "context", "price-mapping", "price-date", "rate-note",
})

def build_summary_rows(snapshot, labels, hidden: frozenset[str]) -> tuple[ReceiptRow, ...]:
    rows: list[ReceiptRow] = []
    if "supplier" not in hidden:
        rows.append(ReceiptRow(labels["provider"], snapshot.provider.upper()))
    if "model" not in hidden:
        rows.append(ReceiptRow(labels["model"], snapshot.model))
    ctx = context_used(snapshot)
    if ctx is not None and "context" not in hidden:
        rows.append(ReceiptRow(labels["context"], ctx))
    return tuple(rows)
```

### PARTIAL pricing rows — fix #6

```python
def build_pricing_rows(estimate, labels, hidden):
    if estimate.status == "UNMAPPED":
        return [
            ReceiptRow(labels["estimate"].format(currency=estimate.currency), money(None, estimate.currency)),
            ReceiptRow(labels["price"], labels["unmapped"]),
        ]
    if estimate.status == "PARTIAL":
        rows = [
            ReceiptRow(labels["estimate"].format(currency=estimate.currency) + "*",
                       money(estimate.amount, estimate.currency)),
            ReceiptRow(labels["price"], "PARTIAL"),
        ]
        # Intentionally no price_date row; PARTIAL means the rate table was incomplete.
        return rows
    # ESTIMATE
    rows = [
        ReceiptRow(labels["estimate"].format(currency=estimate.currency),
                   money(estimate.amount, estimate.currency)),
        ReceiptRow(labels["price"], estimate.model),
    ]
    if estimate.source_checked_at and "price-date" not in hidden:
        rows.append(ReceiptRow(labels["price_date"], estimate.source_checked_at))
    if estimate.rate_note and "rate-note" not in hidden:
        rows.append(ReceiptRow(labels["rate_note"], estimate.rate_note))
    return rows
```

`PRICE: PARTIAL` and the `*` on the estimate amount are the visual tells. `--hide-fields price-mapping` additionally drops the `PRICE:` row for callers who want the amount only.

## CLI changes (cli.py)

New/changed flags:

```python
parser.add_argument("--scope",
    choices=("latest-turn", "session", "today", "session-all"),
    default="latest-turn")

parser.add_argument("--cache-ttl",
    choices=("auto", "5m", "1h"), default="auto",
    help="Cache-write TTL for cost. auto = per-message split if available, "
         "else ENABLE_PROMPT_CACHING_1H_BEDROCK env, else 5m.")

parser.add_argument("--hide-fields", default="",
    help="Comma-separated keys to drop from the receipt: "
         "supplier, model, context, price-mapping, price-date, rate-note.")
```

`--cache-ttl auto` maps to `cli_override=None` in `resolve_cache_write_split`.

### Silent `--write` — fix #10

```python
if args.write:
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(receipt_text + "\n", encoding="utf-8")
    if args.write_html:
        sys.stdout.write(f"wrote to: {args.write}\n")
        sys.stdout.write(f"wrote to: {args.write_html}\n")
    # else: fully silent
    return 0
```

No receipt body, no receipt id, no descriptive prefix. When both paths are written, the two `wrote to:` lines are the only stdout.

## SKILL.md change — fix #11

Update the chat-reply template from `[Printable HTML](/tmp/token-receipt.html)` to `[Printable HTML](file:///tmp/token-receipt.html)`, with a single-line explanation: without the `file://` scheme, host chat clients (Claude Code on macOS) show "application cannot open" when the user clicks the link.

Update the Claude Code quick-run example similarly:

```bash
python3 scripts/token_receipt.py --agent-tool claude-code \
  --session ~/.claude/usage-data/session-meta/${CLAUDE_SESSION_ID}.json \
  --write /tmp/token-receipt.txt \
  --write-html /tmp/token-receipt.html
# then paste the text contents as the final chat reply, and link:
# [Printable HTML](file:///tmp/token-receipt.html)
```

## Data flow (end-to-end)

1. `cli.main` parses args.
2. `data.resolve_snapshot(args)` picks a loader:
   - manual if `has_manual_usage`
   - else Claude Code path: `latest-turn` → `load_snapshot_from_claude_usage`, other scopes → `claude_aggregator.aggregate_claude_projects`
   - else existing codex/kimi/opencode loaders, unchanged
3. After loader returns, `bedrock.resolve_provider_and_model` rewrites `snapshot.provider` / `snapshot.model` if Bedrock detected.
4. If the source didn't populate `total_tokens`, set `snapshot.total_tokens = pricing.compute_total(snapshot)`.
5. `pricing.estimate_cost(snapshot, args.pricing, args.cache_ttl)` returns `PriceEstimate` with status `ESTIMATE` | `UNMAPPED` | `PARTIAL`.
6. `render.build_receipt_view` consumes snapshot + estimate + `--hide-fields` and builds summary/token/pricing rows dynamically.
7. Output:
   - `--write` → write file, silent stdout (or two `wrote to:` lines with `--write-html`).
   - else → print receipt (streamed or not).
8. SKILL.md instructs the caller to format the chat reply with `file:///tmp/...`.

## Error handling

- Missing `message.usage` in a jsonl line → skip silently, count as dedup-irrelevant.
- Corrupt jsonl line (`JSONDecodeError`) → skip line, don't abort aggregation. Increment a `skipped_lines` counter in snapshot diagnostics.
- `session_id` filter matches nothing → return empty snapshot with `aggregation_source="projects-jsonl"` and `deduped_message_ids=0`; render as `TOTAL: 0` + `PRICE: UNMAPPED` (no model means no rate match).
- `pricing.json` entry missing `input_per_million` or `output_per_million` → `PARTIAL` with reason.
- `--cache-ttl 1h` but entry has no `cache_write_1h_per_million` → `PARTIAL` with fallback `2 × input_per_million`.

## Back-compat

- `--scope session` semantic changes. Existing callers get more accurate numbers but not the same numbers. Document in CHANGELOG.
- `UsageSnapshot.cache_write_tokens` stays as the aggregate; `cache_write_5m_tokens` / `cache_write_1h_tokens` default to 0 for loaders that can't split. Downstream consumers reading only `cache_write_tokens` keep working.
- Existing `--provider` / `--model` overrides still beat auto-detection.
- `PriceEstimate.partial_reasons` is new; consumers checking only `status` for `"ESTIMATE"` need to also accept `"PARTIAL"` or special-case.

## Testing

### Unit tests

- `tests/test_pricing_math.py` — 4-bucket cost on representative Opus 4.7 / Sonnet 4.6 / GPT-5 / Qwen entries. Includes the reported-session numbers as a regression.
- `tests/test_ttl_resolver.py` — all four resolution branches (CLI override, per-message split, env flag, 5m default).
- `tests/test_bedrock.py` — model normalization for `global.anthropic.claude-opus-4-7[1m]`, env detection, explicit override precedence.
- `tests/test_aggregator.py` — fixture jsonl with sidechain lines, duplicated `msg_*` IDs, missing `message.id`; asserts dedup count + summed buckets + ephemeral split.
- `tests/test_render_rows.py` — `context_used` returns None off latest-turn; `--hide-fields supplier,model,context` leaves an empty summary block; `PARTIAL` renders `*` + drops price_date.

### Integration — `scripts/validate_receipt.py`

Add assertions:
- `TOTAL` includes cache buckets in manual mode when `--total-tokens` omitted.
- `CONTEXT USED` absent when `--scope session|today|session-all`.
- `SUPPLIER: AWS BEDROCK` with `CLAUDE_CODE_USE_BEDROCK=1` + bare `--model global.anthropic.claude-opus-4-7[1m]`.
- `PRICE: PARTIAL` when a synthetic pricing entry drops `output_per_million`.
- `--hide-fields price-date,context` removes both rows while leaving PRICE row.
- `--write /tmp/out.txt` produces zero stdout; `--write /tmp/out.txt --write-html /tmp/out.html` produces exactly two `wrote to:` lines.

### Manual verification

Run against the originally reported session (Opus 4.7 on Bedrock, 8.18M cache write, 22M cache read). Expected output:

```
TOTAL             30,631,257 tokens
USD ESTIMATE           $103.74    (with ENABLE_PROMPT_CACHING_1H_BEDROCK=1)
PRICE:            claude-opus-4.7
PRICE DATE:             2026-04-25
```

Or without the env flag:

```
TOTAL             30,631,257 tokens
USD ESTIMATE            $73.07
PRICE:            claude-opus-4.7
PRICE DATE:             2026-04-25
```

## Open questions

None. All clarifying questions answered during brainstorming.

## Implementation order (hint for plan)

1. Extract `pricing.py` with current behavior; ensure all existing tests pass against the new module (no behavior change yet).
2. Add `cache_write_1h_per_million` fields to `references/pricing.json` for all anthropic entries.
3. Fix cost math in `pricing.py` (remove clamp, add TTL resolver, introduce `PARTIAL`). Update `validate_receipt.py` golden values.
4. Add `UsageSnapshot.cache_write_5m_tokens` / `_1h_tokens`; update `load_manual_snapshot` total math.
5. Add `bedrock.py`; wire into `resolve_snapshot`.
6. Add `claude_aggregator.py`; wire `--scope today` / `session` / `session-all`.
7. Render changes: `context_used` gating, dynamic summary rows, PARTIAL rendering.
8. CLI flags + silent `--write`.
9. SKILL.md chat-link template update.
10. Validation script and tests; manual regression against reported session.
