"""Sanity check that `python3 -m unittest discover` sees the tests directory."""

import unittest

from token_receipt import models


class ScaffoldTest(unittest.TestCase):
    def test_package_importable(self):
        self.assertTrue(hasattr(models, "UsageSnapshot"))
        self.assertTrue(hasattr(models, "PriceEstimate"))


if __name__ == "__main__":
    unittest.main()
