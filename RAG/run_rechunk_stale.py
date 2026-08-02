"""청크 프리픽스가 낡은 공고만 DB에서 재청킹·재임베딩한다.

배경: `exp_min` 본문 보강 백필(run_backfill_exp.py)로 연차가 채워지면
`chunking.context_prefix`의 `[핵심조건] 경력 …` 문구가 바뀐다. 프리픽스는 임베딩 입력에
그대로 들어가므로, 백필만 하고 재청킹을 안 하면 **검색 텍스트와 DB 필드가 어긋난다.**

왜 run_embed.py를 쓰지 않는가: 그 경로는 입력 JSON에 없는 공고를 전부 `is_active=false`로
내린다(`upsert_postings`의 정책). 상위 폴더의 all_job_postings.json은 251건짜리 낡은
스냅샷이라 그걸로 돌리면 코퍼스 978건이 비활성화된다 — 2026-07-29에 실제로 겪었다.
이 스크립트는 **DB의 raw를 원본으로 삼고 postings 행은 건드리지 않는다**(is_active 불변).

사용: python run_rechunk_stale.py [--dry-run] [--all]
  기본: 프리픽스가 실제로 바뀌는 공고만 처리
  --all: 활성 공고 전량 재청킹 (프리픽스 규칙 자체를 바꿨을 때)
"""
from __future__ import annotations

import sys

from pgvector.psycopg import register_vector

from jobrag.chunking import chunk_posting, context_prefix
from jobrag.embedding import embed_texts
from jobrag.sources import to_posting
from jobrag.store import connect, unchanged_chunk_ids, upsert_chunks


def _posting_from_row(raw: dict, uid: str, exp_min, exp_max, regions, tech, role):
    """DB 상태를 그대로 반영한 Posting을 만든다.

    to_posting(raw)는 파서를 다시 돌리므로 DB에 이미 백필된 값과 어긋날 수 있다.
    DB를 진실로 보고 필드를 덮어써, 청크 프리픽스가 현재 DB 상태와 일치하도록 한다.
    """
    p = to_posting(raw)
    p.exp_min, p.exp_max = exp_min, exp_max
    p.regions, p.tech = regions or [], tech or []
    p.role_category = role or ""
    return p   # uid는 Posting의 읽기전용 property — chunk_posting에 인자로 따로 넘긴다


def main():
    dry = "--dry-run" in sys.argv
    do_all = "--all" in sys.argv
    conn = connect()
    register_vector(conn)

    with conn.cursor() as cur:
        cur.execute("""SELECT uid, exp_min, exp_max, regions, tech, role_category, raw
                       FROM postings WHERE is_active ORDER BY uid""")
        rows = cur.fetchall()
    print(f"활성 공고 {len(rows)}건 검사")

    # 현재 DB 상태로 청크를 다시 만들고, 기존 청크와 텍스트가 다른 것만 고른다
    stale_uids, new_chunks = [], []
    for uid, exp_min, exp_max, regions, tech, role, raw in rows:
        p = _posting_from_row(raw, uid, exp_min, exp_max, regions, tech, role)
        if p.uid != uid:      # uid는 source:posting_id 파생값 — 어긋나면 매칭이 깨진다
            print(f"  !! uid 불일치 건너뜀: DB={uid} vs raw={p.uid}")
            continue
        chunks = chunk_posting(p)
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_id, text FROM chunks WHERE posting_uid = %s", (uid,))
            old = dict(cur.fetchall())
        changed = do_all or any(old.get(c.chunk_id) != c.text for c in chunks) \
            or len(old) != len(chunks)
        if changed:
            stale_uids.append(uid)
            new_chunks.extend(chunks)

    print(f"프리픽스가 달라진 공고 {len(stale_uids)}건 -> 재생성 청크 {len(new_chunks)}개")
    if not new_chunks:
        print("변경 없음.")
        conn.close()
        return
    if dry:
        print("(--dry-run: DB 갱신 없음)")
        for c in new_chunks[:3]:
            print(f"  예시 {c.chunk_id}: {c.text[:120]!r}...")
        conn.close()
        return

    skip = unchanged_chunk_ids(conn, new_chunks)
    todo = [c for c in new_chunks if c.chunk_id not in skip]
    print(f"임베딩 필요 {len(todo)}개 (해시 동일 재사용 {len(skip)}개)")

    embs: list[list[float] | None] = []
    B = 32
    for i in range(0, len(todo), B):
        vecs, _ = embed_texts([c.text for c in todo[i:i + B]])
        embs.extend(list(v) for v in vecs)
        print(f"  임베딩 {min(i + B, len(todo))}/{len(todo)}")

    stats = upsert_chunks(conn, todo, embs)
    conn.commit()
    print(f"청크 반영: {stats}")

    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM chunks ch JOIN postings p ON ch.posting_uid = p.uid
                       WHERE p.is_active AND p.exp_min IS NOT NULL
                         AND ch.text LIKE '%경력 무관/미상%'""")
        print(f"남은 낡은 청크: {cur.fetchone()[0]}개")
        cur.execute("SELECT count(*) FROM postings WHERE is_active")
        print(f"활성 공고 (불변 확인): {cur.fetchone()[0]}건")
    conn.close()


if __name__ == "__main__":
    main()
