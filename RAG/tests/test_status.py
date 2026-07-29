from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from eval.status import summarize_checks


class ContractStatusTest(unittest.TestCase):
    def test_all_explicit_checks_pass(self):
        self.assertEqual(
            summarize_checks([
                {"name": "latency", "p95": 1.2},
                {"name": "shape", "passed": True},
            ]),
            ("passed", True),
        )

    def test_failed_check_wins(self):
        self.assertEqual(
            summarize_checks([
                {"name": "shape", "passed": None},
                {"name": "sorted", "passed": False},
            ]),
            ("failed", False),
        )

    def test_skipped_check_is_incomplete(self):
        self.assertEqual(
            summarize_checks([
                {"name": "latency", "p95": 1.2},
                {"name": "adapter", "passed": None},
            ]),
            ("incomplete", False),
        )

    def test_no_explicit_checks_is_incomplete(self):
        self.assertEqual(
            summarize_checks([{"name": "latency", "p95": 1.2}]),
            ("incomplete", False),
        )


if __name__ == "__main__":
    unittest.main()
