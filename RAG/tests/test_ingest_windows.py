from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_DIR))

from jobrag.ingest_windows import plan_windows  # noqa: E402


@dataclass
class FakeChunk:
    chunk_id: str
    posting_uid: str


def corpus(shape: dict[str, int]) -> list[FakeChunk]:
    return [
        FakeChunk(f"{uid}-c{index}", uid)
        for uid, count in shape.items()
        for index in range(count)
    ]


class PlanWindowsTest(unittest.TestCase):
    def test_a_posting_is_never_split_across_windows(self) -> None:
        chunks = corpus({"a": 3, "b": 3, "c": 3})
        windows = plan_windows(chunks, unchanged=set(), size=2)

        placement = {
            chunk.posting_uid: index
            for index, window in enumerate(windows)
            for chunk in window
        }
        for index, window in enumerate(windows):
            for chunk in window:
                # 쪼개지면 upsert_chunks의 고아 정리가 앞 윈도우 청크를 지운다.
                self.assertEqual(placement[chunk.posting_uid], index)

    def test_every_chunk_appears_exactly_once(self) -> None:
        chunks = corpus({"a": 3, "b": 1, "c": 5, "d": 2})
        windows = plan_windows(chunks, unchanged={"c-c0", "c-c1"}, size=2)

        flattened = [chunk.chunk_id for window in windows for chunk in window]
        self.assertEqual(sorted(c.chunk_id for c in chunks), sorted(flattened))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_unchanged_chunks_do_not_count_toward_window_size(self) -> None:
        chunks = corpus({"a": 2, "b": 2, "c": 2})
        unchanged = {c.chunk_id for c in chunks if c.posting_uid != "c"}

        # 새로 임베딩할 청크가 c의 2개뿐이므로 윈도우는 하나로 묶인다.
        self.assertEqual(1, len(plan_windows(chunks, unchanged, size=2)))
        self.assertEqual(6, len(plan_windows(chunks, unchanged, size=2)[0]))

    def test_no_chunks_yields_no_windows(self) -> None:
        self.assertEqual([], plan_windows([], unchanged=set(), size=64))


if __name__ == "__main__":
    unittest.main()
