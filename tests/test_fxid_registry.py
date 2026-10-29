"""Release effect IDs must be unique and clear of other ZDL collections.

Needs no compiler: reads manifests, dist/ headers and docs/FXID-REGISTRY.md.
Runs under pytest or `python3 -B -m unittest tests.test_fxid_registry`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

import fxid_check  # noqa: E402


class FxidRegistryTest(unittest.TestCase):
    def test_release_ids_clear(self) -> None:
        self.assertEqual(fxid_check.check(), [])

    def test_external_table_is_read(self) -> None:
        external = fxid_check.external_ids(fxid_check.REGISTRY.read_text())
        # Spool.ZDL (themanro) is the issue #8 clash; if the table stops
        # parsing, this fails before a real clash can slip through.
        self.assertIn((8, 409), external)
        self.assertIn((8, 700), external)  # generated CabIR slot range
        self.assertNotIn((8, 946), external)

    def test_parse_ids(self) -> None:
        self.assertEqual(fxid_check.parse_ids("403, 414–416, 500-502"),
                         [403, 414, 415, 416, 500, 501, 502])


if __name__ == "__main__":
    unittest.main()
