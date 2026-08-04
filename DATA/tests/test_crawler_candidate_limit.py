from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
CRAWLERS = (
    "crawl_jobkorea_it.py",
    "crawl_saramin_it.py",
    "crawl_wanted_it.py",
    "crawl_incruit_it.py",
    "crawl_work24_it.py",
)


class CrawlerCandidateLimitTest(unittest.TestCase):
    def test_all_crawlers_expose_max_candidates_cli_option(self) -> None:
        for crawler in CRAWLERS:
            with self.subTest(crawler=crawler):
                completed = subprocess.run(
                    [sys.executable, str(DATA_DIR / crawler), "--help"],
                    check=False,
                    capture_output=True,
                )

                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertIn(b"--max-candidates", completed.stdout)

    def test_all_crawlers_stop_before_processing_candidate_over_limit(self) -> None:
        guard = "if args.max_candidates and index > args.max_candidates:"
        for crawler in CRAWLERS:
            with self.subTest(crawler=crawler):
                source = (DATA_DIR / crawler).read_text(encoding="utf-8")

                self.assertIn(guard, source)
                self.assertIn("status=max_candidates_reached", source)


if __name__ == "__main__":
    unittest.main()
