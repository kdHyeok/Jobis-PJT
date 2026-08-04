from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from jobrag import spec_adapter
from jobrag.query_parser import QuerySpec
from jobrag.search import SearchHit, SearchResult


def _dense_only_result(*, bm25_candidates: int) -> SearchResult:
    spec = QuerySpec(text="backend developer")
    hit = SearchHit(
        posting_uid="posting-1",
        company="Example",
        title="Backend Developer",
        url="https://example.test/jobs/1",
        regions=[],
        tech=[],
        exp_min=None,
        dense_rank=1,
        bm25_rank=None,
        dense_score=0.9,
        rrf=0.02,
    )
    return SearchResult(
        spec=spec,
        hits=[hit],
        dense_candidates=30,
        bm25_candidates=bm25_candidates,
        reranked=True,
    )


class SpecAdapterRerankGuardTest(unittest.TestCase):
    def _search(self, result: SearchResult) -> dict:
        raw = {
            "posting-1": {
                "posting_id": "1",
                "title": "Backend Developer",
                "company": "Example",
                "url": "https://example.test/jobs/1",
            }
        }
        with (
            patch.object(spec_adapter, "load_region_vocab", return_value={}),
            patch.object(spec_adapter, "parse_query", return_value=result.spec),
            patch.object(spec_adapter, "hybrid_search", return_value=result),
            patch.object(spec_adapter, "_fetch_raw", return_value=raw),
        ):
            return spec_adapter.search(object(), "backend developer")

    def test_keeps_reranked_dense_hit_when_bm25_had_candidates(self):
        response = self._search(_dense_only_result(bm25_candidates=4))
        self.assertEqual(len(response["postings"]), 1)
        self.assertEqual(response["postings"][0]["posting_id"], "1")

    def test_empty_ok_still_rejects_query_without_any_bm25_candidate(self):
        response = self._search(_dense_only_result(bm25_candidates=0))
        self.assertEqual(response, {"postings": []})


if __name__ == "__main__":
    unittest.main()
