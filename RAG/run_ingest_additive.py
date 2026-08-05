"""신규 배치를 **가산(additive)** 적재한다 — 어떤 공고도 비활성화하지 않는다.

왜 run_embed.py를 쓰지 않는가
-----------------------------
run_embed.py는 `upsert_postings(...)`를 기본값(`deactivate_missing=True`)으로 호출한다.
그러면 배치에 없는 같은 source의 공고가 전부 `is_active=false`로 내려간다. 2026-07-29에
낡은 251건 스냅샷으로 이 경로를 돌려 활성 코퍼스 1,172 -> 211건이 된 사고가 있었다.

Jobis_통합본_20260728 배치(6,918건)도 기존 코퍼스의 상위집합이 **아니다**:
  기존 활성 1,172 중 808건만 신규 파일에 존재 -> 364건이 비활성화 대상이 된다.
그 364건에는 사람이 손수 라벨링한 118쌍과 judge 판정 439쌍이 걸려 있고, 사람 라벨은
지금 재생산이 불가능하다(사용자 확인). 평가 자산을 지키는 쪽이 압도적으로 이득이므로
**합집합 정책**을 택한다. 공고 마감 여부는 이 평가의 측정 대상이 아니다
(랭커가 적합 공고를 찾아내는지를 재는 것이지, 지금 지원 가능한지를 재는 게 아니다).

사용: python run_ingest_additive.py <입력JSON> [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pgvector.psycopg import register_vector

from jobrag import tokenizer
from jobrag.chunking import chunk_posting, chunk_stats
from jobrag.embedding import backend as embedding_backend, embed_texts
from jobrag.model_config import get_model_settings
from jobrag.sources import load_postings
from jobrag.store import connect, unchanged_chunk_ids, upsert_chunks, upsert_postings


def _counts(conn) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM postings WHERE is_active")
        act = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks")
        return act, cur.fetchone()[0]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return
    src, dry = Path(args[0]), "--dry-run" in sys.argv
    model_settings = get_model_settings()
    print(
        f"tokenizer={tokenizer.backend()}  "
        f"embedding={embedding_backend()}  "
        f"threads={model_settings.local_cpu_threads}  "
        f"embed_batch={model_settings.embed_batch_size}  input={src}"
    )

    raw_records = json.loads(src.read_text(encoding="utf-8"))
    raw_by_uid = {f"{r.get('source')}:{r.get('posting_id')}": r for r in raw_records}
    postings, stats = load_postings(src)
    print("[load]", json.dumps(stats, ensure_ascii=False))

    all_chunks = [c for p in postings for c in chunk_posting(p)]
    print("[chunk]", json.dumps(chunk_stats(all_chunks), ensure_ascii=False))

    conn = connect()
    register_vector(conn)
    act0, ch0 = _counts(conn)
    print(f"[before] 활성 공고 {act0} · 청크 {ch0}")

    unchanged = unchanged_chunk_ids(conn, all_chunks)
    todo = [c for c in all_chunks if c.chunk_id not in unchanged]
    print(f"[embed] 신규/변경 {len(todo)} · 해시동일 재사용 {len(unchanged)}")
    if dry:
        print("(--dry-run: DB 갱신 없음)")
        conn.close()
        return

    vectors: list[list[float] | None] = []
    B = model_settings.ingest_window_size
    for i in range(0, len(todo), B):
        vecs, _ = embed_texts(
            [c.text for c in todo[i:i + B]],
            batch_size=model_settings.embed_batch_size,
        )
        vectors.extend(vecs)
        print(f"  임베딩 {min(i + B, len(todo))}/{len(todo)}", flush=True)
    by_id = dict(zip((c.chunk_id for c in todo), vectors))
    embeddings = [by_id.get(c.chunk_id) for c in all_chunks]

    # 핵심: deactivate_missing=False — 기존 활성 공고를 건드리지 않는다
    ps = upsert_postings(conn, postings, raw_by_uid, deactivate_missing=False)
    print("[store_postings]", json.dumps(ps, ensure_ascii=False))
    cs = upsert_chunks(conn, all_chunks, embeddings)
    print("[store_chunks]", json.dumps(cs, ensure_ascii=False))
    conn.commit()

    act1, ch1 = _counts(conn)
    print(f"[after] 활성 공고 {act1} (+{act1 - act0}) · 청크 {ch1} (+{ch1 - ch0})")
    # 가산 적재의 불변식 — 깨지면 즉시 알아야 한다
    assert act1 >= act0, f"활성 공고가 줄었다: {act0} -> {act1}"
    assert ps.get("deactivated", 0) == 0, f"비활성화가 발생했다: {ps}"
    print("불변식 OK — 비활성화 0건")
    conn.close()


if __name__ == "__main__":
    main()
