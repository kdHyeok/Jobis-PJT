"""인제스트 중간 저장 단위를 계산한다.

run_ingest_additive.py 는 pgvector·임베딩 백엔드 같은 무거운 것들을 import 하므로,
순수 계산인 이 함수만 따로 둔다. 그래야 CI 의 가벼운 환경에서도 테스트할 수 있다.
"""
from __future__ import annotations


def plan_windows(all_chunks: list, unchanged: set[str], size: int) -> list[list]:
    """중간 저장 단위. 한 공고의 청크는 절대 쪼개지 않는다.

    upsert_chunks는 마지막에 delete_orphan_chunks(이번 공고들, 이번에 넘긴 청크)를
    돌린다. 한 공고를 두 윈도우로 나눠 넣으면 뒤 윈도우가 앞 윈도우의 청크를 고아로
    지운다. 그래서 변경분만이 아니라 그 공고의 전체 청크를 함께 넘긴다(내용 불변
    청크는 해시가 같아 쓰기 없이 통과하고, 사라진 청크만 정리된다).

    size는 윈도우당 '새로 임베딩할' 청크 수 기준이다.
    """
    by_uid: dict[str, list] = {}
    for chunk in all_chunks:
        by_uid.setdefault(chunk.posting_uid, []).append(chunk)

    windows, current, pending = [], [], 0
    for posting_chunks in by_uid.values():
        current.extend(posting_chunks)
        pending += sum(1 for c in posting_chunks if c.chunk_id not in unchanged)
        if pending >= size:
            windows.append(current)
            current, pending = [], 0
    if current:
        windows.append(current)
    return windows
