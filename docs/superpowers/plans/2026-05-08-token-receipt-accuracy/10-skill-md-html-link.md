# Part 10 — SKILL.md: use `file:///tmp/...` for the HTML link

**Parent plan:** [README.md](./README.md)

**Goal:** Fix defect #11. Host chat clients (Claude Code on macOS) show "application cannot open" when the user clicks a link with no scheme. Adding `file://` makes the link open.

## Files

- Modify: `SKILL.md:75-97` (specific lines identified below).

## Task 1: Update the two link references

The current file has two places that render `/tmp/token-receipt.html`:

1. The authoring instructions around line 77.
2. The literal reply example around line 97.

- [ ] **Step 1: Read the current SKILL.md section**

Run: `grep -n "/tmp/token-receipt.html" SKILL.md`
Expected output:
```
76:  - 可打印 HTML：`--write-html /tmp/token-receipt.html`
77:  - 最终回复里把 receipt 代码块贴出，再附一个本地文件链接 `[Printable HTML](/tmp/token-receipt.html)`。
97:[Printable HTML](/tmp/token-receipt.html)
```

- [ ] **Step 2: Update the instruction line (around line 77)**

Replace this line exactly:

```markdown
  - 最终回复里把 receipt 代码块贴出，再附一个本地文件链接 `[Printable HTML](/tmp/token-receipt.html)`。
```

with:

```markdown
  - 最终回复里把 receipt 代码块贴出，再附一个本地文件链接 `[Printable HTML](file:///tmp/token-receipt.html)`（必须带 `file://` 前缀，否则在部分聊天客户端里点击会提示"无法打开"）。
```

- [ ] **Step 3: Update the literal reply example (around line 97)**

Replace:

```markdown
[Printable HTML](/tmp/token-receipt.html)
```

with:

```markdown
[Printable HTML](file:///tmp/token-receipt.html)
```

- [ ] **Step 4: Verify nothing else still uses the bare path**

Run: `grep -n "](/tmp/token-receipt" SKILL.md`
Expected: no output (all bare refs are gone).

Run: `grep -n "file:///tmp/token-receipt" SKILL.md`
Expected: at least 2 matches.

- [ ] **Step 5: Run the full suite and validation script**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/validate_receipt.py`
Expected: both exit 0 (SKILL.md is not exercised by tests, but we run them to confirm no inadvertent edits elsewhere).

- [ ] **Step 6: Commit**

```bash
git add SKILL.md
git commit -m "fix(skill): use file:// scheme for HTML link so chat clients open it"
```
