# Part 11 — Extend `validate_receipt.py` + manual regression

**Parent plan:** [README.md](./README.md)

**Goal:** Pin the new behavior from inside the project's existing smoke-test script so future regressions surface immediately, and confirm the originally reported session now produces the numbers the spec promises.

## Files

- Modify: `scripts/validate_receipt.py` — add six assertion cases.
- Modify: `CHANGELOG.md` — add a `## 2026-05-08` block.

## Task 1: Add six assertion cases to `validate_receipt.py`

The file already has a `main()` driver that runs a long series of `run_case(...)` + `assert_receipt(...)` assertions. Append six new cases at the end, just before the current trailing `return 0`. The exact insertion point is whatever line currently reads `return 0` at the end of `main()`.

- [ ] **Step 1: Find the insertion point**

Run: `grep -n "^    return 0$" scripts/validate_receipt.py`
Expected: one line number (e.g., `783:    return 0`). Record that line; all six cases below go immediately above it.

- [ ] **Step 2: Add the Bedrock normalization case**

Explicit `--model` always wins per spec §Back-compat, so we can only exercise Bedrock *provider* rewrite while keeping the Bedrock-shaped model string visible — that's still the common Claude Code path (env flag set, model string is the Bedrock ID). For full model normalization we rely on the unit tests in `tests/test_bedrock.py`.

Insert:

```python
    # --- Part 06: Bedrock provider rewrite (env flag path) ---
    # --model is explicit here, so _finalize only rewrites provider; the unit
    # tests in tests/test_bedrock.py cover normalize_bedrock_model end-to-end.
    bedrock_text = run_case(
        "--agent-tool", "claude-code",
        "--model", "global.anthropic.claude-opus-4-7[1m]",
        "--input-tokens", "16897",
        "--cached-input-tokens", "22000000",
        "--cache-write-tokens", "8180000",
        "--output-tokens", "434360",
        "--width", "48",
        env={"CLAUDE_CODE_USE_BEDROCK": "1"},
    )
    assert "AWS BEDROCK" in bedrock_text, f"expected AWS BEDROCK, got: {bedrock_text!r}"
    assert "TOTAL" in bedrock_text
    # The explicit model flag wins — display keeps the raw Bedrock string.
    assert "global.anthropic.claude-opus-4-7[1m]" in bedrock_text, "explicit --model should be preserved"

```

- [ ] **Step 3: Add the all-four-buckets math case (5m default)**

Insert:

```python
    # --- Part 05: all four buckets billed, 5m TTL default ---
    opus_5m = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-opus-4.7",
        "--input-tokens", "16897",
        "--cached-input-tokens", "22000000",
        "--cache-write-tokens", "8180000",
        "--output-tokens", "434360",
        "--width", "48",
    )
    # Expect ~$73.07 (see spec).
    assert "$73." in opus_5m, f"expected $73.xx, got: {opus_5m}"
    assert "30,631,257" in opus_5m, "expected fixed TOTAL=30,631,257 across all 4 buckets"

```

- [ ] **Step 4: Add the 1h TTL case**

Insert:

```python
    # --- Part 05: 1h TTL via --cache-ttl 1h ---
    opus_1h = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-opus-4.7",
        "--input-tokens", "16897",
        "--cached-input-tokens", "22000000",
        "--cache-write-tokens", "8180000",
        "--output-tokens", "434360",
        "--cache-ttl", "1h",
        "--width", "48",
    )
    assert "$103." in opus_1h, f"expected $103.xx, got: {opus_1h}"

```

- [ ] **Step 5: Add the PARTIAL case**

Insert:

```python
    # --- Part 05/09: PARTIAL status renders estimate* + PRICE: PARTIAL, no PRICE DATE ---
    partial_pricing = Path(tempfile.mkdtemp()) / "pricing.json"
    partial_pricing.write_text(json.dumps({
        "currency": "USD",
        "models": [{
            "provider": "acme", "model": "bare", "aliases": ["bare"],
            "input_per_million": 1.0,
            # output_per_million intentionally missing
        }],
    }))
    partial_text = run_case(
        "--provider", "acme", "--model", "bare",
        "--agent-tool", "generic",
        "--pricing", str(partial_pricing),
        "--input-tokens", "1000", "--output-tokens", "1000",
        "--width", "48",
    )
    assert "PARTIAL" in partial_text, f"expected PRICE: PARTIAL, got: {partial_text}"
    assert "PRICE DATE" not in partial_text, "PARTIAL must drop PRICE DATE row"
    assert "USD ESTIMATE*" in partial_text, "PARTIAL estimate label must carry trailing *"

```

- [ ] **Step 6: Add the `--hide-fields` case**

Insert:

```python
    # --- Part 08/09: --hide-fields drops rows ---
    hide_text = run_case(
        "--provider", "anthropic", "--model", "claude-sonnet-4.5",
        "--agent-tool", "claude-code",
        "--input-tokens", "100", "--output-tokens", "100",
        "--hide-fields", "price-date,context",
        "--width", "48",
    )
    assert "PRICE DATE" not in hide_text, "expected PRICE DATE hidden"
    assert "CONTEXT USED" not in hide_text, "expected CONTEXT USED hidden"
    assert "USD ESTIMATE" in hide_text, "PRICE line should still render"

```

- [ ] **Step 7: Add the silent `--write` case**

Insert:

```python
    # --- Part 08: --write produces zero stdout; --write + --write-html prints exactly two "wrote to:" lines ---
    with tempfile.TemporaryDirectory() as write_tmp:
        write_txt = Path(write_tmp) / "r.txt"
        write_html = Path(write_tmp) / "r.html"
        write_only = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--provider", "anthropic", "--model", "claude-sonnet-4.5",
             "--agent-tool", "claude-code",
             "--input-tokens", "1", "--output-tokens", "1",
             "--write", str(write_txt)],
            cwd=str(ROOT), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
        assert write_only.stdout == "", f"--write alone must be silent; got {write_only.stdout!r}"

        write_both = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--provider", "anthropic", "--model", "claude-sonnet-4.5",
             "--agent-tool", "claude-code",
             "--input-tokens", "1", "--output-tokens", "1",
             "--write", str(write_txt),
             "--write-html", str(write_html)],
            cwd=str(ROOT), text=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
        lines = [line for line in write_both.stdout.splitlines() if line]
        assert len(lines) == 2, f"expected exactly two 'wrote to:' lines, got: {write_both.stdout!r}"
        assert all(line.startswith("wrote to:") for line in lines), write_both.stdout

```

- [ ] **Step 8: Run the validation script**

Run: `python3 scripts/validate_receipt.py`
Expected: exit 0 with no assertion errors.

- [ ] **Step 9: Run the full test suite one more time**

Run: `python3 -m unittest discover -s tests -v`
Expected: every test in `tests/` passes.

## Task 2: Manual regression against the reported session

- [ ] **Step 10: Generate the reported-session receipt and eyeball it**

Run:

```bash
python3 scripts/token_receipt.py \
  --provider anthropic \
  --agent-tool claude-code \
  --model claude-opus-4.7 \
  --input-tokens 16897 \
  --cached-input-tokens 22000000 \
  --cache-write-tokens 8180000 \
  --output-tokens 434360 \
  --width 48
```

Expected content (from spec §"Sanity check"):
- `TOTAL` line reads `30,631,257 TOKENS`
- `USD ESTIMATE` reads `$73.07` (give or take rounding on the last cent)
- `PRICE: claude-opus-4.7` present
- `PRICE DATE: 2026-04-25` present

Then with 1h TTL:

```bash
python3 scripts/token_receipt.py \
  --provider anthropic \
  --agent-tool claude-code \
  --model claude-opus-4.7 \
  --input-tokens 16897 \
  --cached-input-tokens 22000000 \
  --cache-write-tokens 8180000 \
  --output-tokens 434360 \
  --cache-ttl 1h \
  --width 48
```

Expected: `USD ESTIMATE` reads `$103.74` (give or take a cent).

Then Bedrock provider + model normalization (no explicit `--model`, so `_finalize` rewrites both):

```bash
CLAUDE_CODE_USE_BEDROCK=1 python3 scripts/token_receipt.py \
  --agent-tool claude-code \
  --input-tokens 16897 \
  --cached-input-tokens 22000000 \
  --cache-write-tokens 8180000 \
  --output-tokens 434360 \
  --width 48
```

For this to exercise the full rewrite, the manual snapshot's loader (`load_manual_snapshot`) must pick up a Bedrock-shaped model. Since manual mode reads `args.model` or `model_from_env()` or `UNRECORDED`, the easiest repro is to set `MODEL_FROM_ENV` equivalents in the environment — but those vary across loaders. The realistic end-to-end path is from a live Claude Code session log; run the end-to-end regression **inside** a Claude Code session with `CLAUDE_CODE_USE_BEDROCK=1` and no `--model` override, not via manual flags. Expected on the real session:

- `PROVIDER: AWS BEDROCK`
- `MODEL: claude-opus-4.7`
- `USD ESTIMATE` ≈ `$73.07` (or `$103.74` with `--cache-ttl 1h` or `ENABLE_PROMPT_CACHING_1H_BEDROCK=1`)

For an offline manual regression, use the explicit `--provider anthropic --model claude-opus-4.7` path above — it exercises the same pricing math.

If any of these expected values are off, loop back to the relevant part and iterate.

## Task 3: Record the change

- [ ] **Step 11: Prepend a CHANGELOG block**

Insert the following block at the top of `CHANGELOG.md`, directly after the `# Changelog` line and before the existing `## 2026-05-05` block:

```markdown
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
```

- [ ] **Step 12: Commit**

```bash
git add scripts/validate_receipt.py CHANGELOG.md
git commit -m "test: pin Bedrock, all-buckets, 1h TTL, PARTIAL, hide-fields, silent --write"
```

- [ ] **Step 13: Push**

Follow the repo's global convention (no-verify):

```bash
git push --no-verify origin main
```

Only run this step if the user has explicitly approved pushing. If unsure, stop after step 12 and ask.
