# Part 01 — Test scaffold

**Parent plan:** [README.md](./README.md)

**Goal:** Create a `tests/` directory that `python3 -m unittest discover` can pick up, with no production code yet, so later parts can land failing tests the standard way.

## Files

- Create: `tests/__init__.py` (empty)
- Create: `tests/test_scaffold.py`

## Task 1: Add the test directory and a sanity test

- [ ] **Step 1: Write `tests/__init__.py`**

`tests/__init__.py` (0 bytes):

```python
```

- [ ] **Step 2: Write the scaffold test**

`tests/test_scaffold.py`:

```python
"""Sanity check that `python3 -m unittest discover` sees the tests directory."""

import unittest

from token_receipt import models


class ScaffoldTest(unittest.TestCase):
    def test_package_importable(self):
        self.assertTrue(hasattr(models, "UsageSnapshot"))
        self.assertTrue(hasattr(models, "PriceEstimate"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run discovery to verify the scaffold passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: `Ran 1 test` + `OK`.

- [ ] **Step 4: Run the existing validation smoke suite to confirm no regressions**

Run: `python3 scripts/validate_receipt.py`
Expected: exits 0 with no stdout asserts failing.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/test_scaffold.py
git commit -m "test: add unittest scaffold"
```
