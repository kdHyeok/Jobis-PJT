# -*- coding: utf-8 -*-
"""풀 구축 v2 — 판정 캐시 위에서 모든 arm을 무비용 재조합할 수 있는 '원자' 풀.

설계 (사전등록 §2·§3에 맞춤):
  원자 = 축(dense/BM25) × 필터구성 3종 × 깊이 50 + random 30
    - full:     지역+연차 하드필터 (프로덕션 기본)
    - noregion: 지역 완화 (RELAX_ORDER 1단계)
    - nofilter: 전체 완화 = 무필터 (필터 손실 측정용 상한)
  교차 점수 캐시 = 풀 합집합의 모든 uid에 대해 dense 코사인·BM25 점수 저장
    → alpha 가중합 융합·RRF_K·CANDIDATE_K 스윕을 재검색 없이 재조합
  CE 점수 캐시 = full 구성 합집합(dense∪bm25 top50)에 크로스인코더 점수 박제
    → rrf_ce arm과 RERANK_TOP_N 스윕을 오프라인 재조합
  필터 플래그 = uid별 ok_region/ok_exp (파싱 spec 기준)
    → rrf_relax(계층 병합) 시뮬레이션과 소실 퍼널 원인 태깅(recall/precision 방향)

분할: 65질의를 축 층화 + 결정적 해시로 dev 30 / holdout 35 봉인.
      holdout은 질의 목록만 박제하고 풀·판정을 만들지 않는다(개봉 시 재실행).

실행 (RAG 디렉토리):
    python -m eval.pool_v2              # dev 30 풀 구축 → eval/pool_v2.json
    python -m eval.pool_v2 --holdout    # 홀드아웃 개봉(별도 파일) — 사전등록 §3 이후에만
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from golden.queries import QUERIES
from jobrag import search as S
from jobrag import reranker
from jobrag.embedding import embed_texts
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.store import connect

from . import core

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_v2.json"
HOLDOUT_POOL_PATH = EVAL_DIR / "pool_v2_holdout.json"
EXPECTED_PARSE = EVAL_DIR.parent / "golden" / "expected_parse.json"

DEPTH = 50            # 원자 깊이 — CANDIDATE_K 스윕 상한(50)과 같아야 prefix 재조합 가능
N_RANDOM = 30
N_DEV = 30

CONFIGS = {           # 필터구성 → jobrag.search 완화 튜플
    "full": (),
    "noregion": ("region",),
    "nofilter": ("region", "exp"),
}

AXES = {
    "기술": {"tech_focus", "tech_alias", "multi_tech"},
    "지역": {"region_focus", "colloquial_region"},
    "제약": {"exp_focus", "boundary_exp", "combo_balanced", "combo_dense"},
    "난이도": {"sparse_relax", "low_resource_role", "parser_trap", "negative_signal", "freeform"},
}
AXIS_TARGETS = {"기술": 8, "지역": 7, "제약": 8, "난이도": 7}


# ── 분할 (결정적) ───────────────────────────────────────

def split_queries() -> tuple[list[dict], list[dict]]:
    """축 층화 + sha256 정렬로 dev 30 선정. 나머지가 홀드아웃(봉인)."""
    by_axis: dict[str, list[dict]] = defaultdict(list)
    for q in QUERIES:
        for axis, cats in AXES.items():
            if q["category"] in cats:
                by_axis[axis].append(q)

    dev_ids: list[str] = []
    taken = set()
    for axis, target in AXIS_TARGETS.items():
        pool = sorted(by_axis[axis],
                      key=lambda q: hashlib.sha256(f"{q['id']}:{q['text']}".encode()).hexdigest())
        n = 0
        for q in pool:
            if n >= target:
                break
            if q["id"] in taken:
                continue
            taken.add(q["id"])
            dev_ids.append(q["id"])
            n += 1
    dev_ids = dev_ids[:N_DEV]
    dev = [q for q in QUERIES if q["id"] in dev_ids]
    holdout = [q for q in QUERIES if q["id"] not in dev_ids]
    return dev, holdout


# ── 원자 검색 ───────────────────────────────────────────

def _axis_atoms(conn, vec, spec) -> dict[str, list[list]]:
    """6개 원자: {dense|bm25}_{full|noregion|nofilter} → [[uid, score], ...] 깊이 50.

    dense 점수는 코사인 유사도(1-dist), bm25는 Okapi raw. 순위는 리스트 순서가 정본.
    """
    atoms = {}
    for cfg_name, relaxed in CONFIGS.items():
        dense = S._dense_axis(conn, vec, spec, relaxed)
        atoms[f"dense_{cfg_name}"] = [[uid, round(1.0 - float(dist), 6)]
                                      for uid, _cid, dist in dense]
        bm25 = S._bm25_axis(conn, spec, relaxed)
        atoms[f"bm25_{cfg_name}"] = [[uid, round(float(score), 6)]
                                     for uid, _cid, score in bm25]
    return atoms


def _random_atom(conn, qid: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT uid FROM postings WHERE is_active ORDER BY uid")
        all_uids = [r[0] for r in cur.fetchall()]
    seed = int(hashlib.sha256(f"random:{qid}".encode()).hexdigest()[:12], 16)
    return sorted(random.Random(seed).sample(all_uids, min(N_RANDOM, len(all_uids))))


# ── 교차 점수 캐시 ──────────────────────────────────────

def _dense_scores_for(conn, vec, uids: list[str]) -> dict[str, float]:
    """합집합 uid 전체의 최고 청크 코사인 — 필터 무관, 순수 유사도."""
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (posting_uid) posting_uid, (embedding <=> %s::vector) AS dist
               FROM chunks WHERE posting_uid = ANY(%s) AND embedding IS NOT NULL
               ORDER BY posting_uid, embedding <=> %s::vector""",
            (vec, uids, vec),
        )
        return {r[0]: round(1.0 - float(r[1]), 6) for r in cur.fetchall()}


def _bm25_scores_for(conn, spec, uids: set[str]) -> dict[str, float]:
    """합집합 uid의 최고 청크 BM25 — 필터 무관. 0점은 생략(매치 없음)."""
    tokens = S._tokenize(spec.text)
    if not tokens:
        return {}
    index = S._load_bm25_index(conn)
    scores = index["bm25"].get_scores(tokens)
    best: dict[str, float] = {}
    for (uid, _cid), sc in zip(index["chunks"], scores):
        if uid in uids and sc > 0 and sc > best.get(uid, 0.0):
            best[uid] = float(sc)
    return {u: round(s, 6) for u, s in best.items()}


def _ce_scores_for(conn, spec, uids: list[str]) -> tuple[dict[str, float], str]:
    """full 구성 합집합의 크로스인코더 점수. 실패 시 빈 dict + 백엔드 문자열."""
    if not uids:
        return {}, reranker.backend()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (posting_uid) posting_uid, text FROM chunks
               WHERE posting_uid = ANY(%s)
               ORDER BY posting_uid, (part = 'full') DESC, chunk_id""",
            (uids,),
        )
        texts = dict(cur.fetchall())
    pairs = [(u, texts[u]) for u in uids if u in texts]
    scores = reranker.rerank(spec.text, pairs)
    if scores is None:
        return {}, reranker.backend()
    return {u: round(float(s), 6) for (u, _), s in zip(pairs, scores)}, reranker.backend()


# ── 필터 플래그·메타 ────────────────────────────────────

def _posting_flags(conn, spec, uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT uid, regions, exp_min, role_category FROM postings
               WHERE uid = ANY(%s)""",
            (uids,),
        )
        out = {}
        for uid, regions, exp_min, role in cur.fetchall():
            regions = regions or []
            ok_region = (not spec.regions) or bool(set(regions) & set(spec.regions))
            ok_exp = (spec.exp_years is None) or (exp_min is None) or (exp_min <= spec.exp_years)
            out[uid] = {
                "regions": regions, "exp_min": exp_min, "role_category": role or "",
                "ok_region": ok_region, "ok_exp": ok_exp,
            }
        return out


# ── 파서 검증 (expected_parse 대조) ─────────────────────

def _parser_check(qid: str, spec, expected: dict) -> dict:
    exp = expected.get(qid)
    if not exp:
        return {"has_expected": False}
    # 기대 지역은 시도 단위 축약("서울") — 파싱 결과는 시군구까지 나올 수 있어 접두 매칭
    exp_regions = exp.get("regions") or []
    parsed_regions = spec.regions or []
    region_match = (not exp_regions and not parsed_regions) or any(
        p == e or p.startswith(e + " ") or e.startswith(p)
        for p in parsed_regions for e in exp_regions
    )
    exp_match = (exp.get("exp_years") == spec.exp_years)
    return {
        "has_expected": True,
        "parsed": {"regions": parsed_regions, "exp_years": spec.exp_years, "tech": spec.tech},
        "expected": {"regions": exp_regions, "exp_years": exp.get("exp_years"),
                     "tech": exp.get("tech", [])},
        "region_match": region_match, "exp_match": exp_match,
        "review": exp.get("review", ""),
    }


# ── 풀 구축 ─────────────────────────────────────────────

def build(conn, queries: list[dict], out_path: Path, split_meta: dict) -> dict:
    S.CANDIDATE_K = DEPTH  # 원자 깊이 50 — _dense_axis/_bm25_axis가 호출 시점에 참조
    region_vocab = load_region_vocab(conn)
    expected = (json.loads(EXPECTED_PARSE.read_text(encoding="utf-8"))
                if EXPECTED_PARSE.exists() else {})

    reranker.warmup()
    q_out, parser_report = {}, {}
    t_start = time.time()

    for i, q in enumerate(queries, 1):
        t0 = time.time()
        spec = parse_query(q["text"], region_vocab)
        [vec], _ = embed_texts([spec.text])

        atoms = _axis_atoms(conn, vec, spec)
        rand_uids = _random_atom(conn, q["id"])

        union = set(rand_uids)
        for lst in atoms.values():
            union.update(uid for uid, _ in lst)
        union_l = sorted(union)

        dense_sc = _dense_scores_for(conn, vec, union_l)
        bm25_sc = _bm25_scores_for(conn, spec, union)
        flags = _posting_flags(conn, spec, union_l)

        full_union = sorted({uid for uid, _ in atoms["dense_full"]}
                            | {uid for uid, _ in atoms["bm25_full"]})
        ce_sc, ce_backend = _ce_scores_for(conn, spec, full_union)

        scores = {}
        for uid in union_l:
            f = flags.get(uid, {})
            scores[uid] = {
                "dense": dense_sc.get(uid),
                "bm25": bm25_sc.get(uid),
                "ce": ce_sc.get(uid),
                **f,
            }

        parser_report[q["id"]] = _parser_check(q["id"], spec, expected)
        q_out[q["id"]] = {
            "query": q["text"],
            "category": q["category"],
            "spec": {"regions": spec.regions, "exp_years": spec.exp_years, "tech": spec.tech},
            "atoms": atoms,
            "scores": scores,
            "random": rand_uids,
            "uids": union_l,
            "n_pool": len(union_l),
            "ce_backend": ce_backend,
        }
        print(f"[{i}/{len(queries)}] {q['id']} {q['text'][:30]} — 풀 {len(union_l)} "
              f"(full합 {len(full_union)}, CE {len(ce_sc)}) {time.time()-t0:.1f}s", flush=True)

    data = {
        "meta": {
            "version": "pool_v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_hash": core.snapshot_hash(conn),
            "n_postings": _count_active(conn),
            "embed_model": "BAAI/bge-m3",
            "reranker_backend": reranker.backend(),
            "depth": DEPTH, "n_random": N_RANDOM,
            "configs": {k: list(v) for k, v in CONFIGS.items()},
            "split": split_meta,
            "elapsed_sec": round(time.time() - t_start, 1),
        },
        "parser_check": parser_report,
        "queries": q_out,
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    total = sum(v["n_pool"] for v in q_out.values())
    print(f"\n저장: {out_path}")
    print(f"질의 {len(q_out)}개 / 총 판정 대상 {total}쌍 "
          f"(배치 {total // 20 + len(q_out)}호출 내외)", flush=True)
    mism = [qid for qid, p in parser_report.items()
            if p.get("has_expected") and not (p["region_match"] and p["exp_match"])]
    if mism:
        print(f"[파서 불일치] {len(mism)}건: {', '.join(mism)} — 원인 태깅에 parser_error로 반영")
    return data


def _count_active(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM postings WHERE is_active")
        return cur.fetchone()[0]


def main():
    dev, holdout = split_queries()
    split_meta = {
        "rule": "축 층화(기술8/지역7/제약8/난이도7) + sha256(id:text) 정렬 상위",
        "dev": [q["id"] for q in dev],
        "holdout": [q["id"] for q in holdout],
    }
    conn = connect()
    try:
        if "--holdout" in sys.argv:
            print(f"홀드아웃 개봉: {len(holdout)}질의 — 사전등록 §3 스윕 확정 후에만 유효")
            build(conn, holdout, HOLDOUT_POOL_PATH, split_meta)
        else:
            print(f"dev {len(dev)}질의 / holdout {len(holdout)}질의 (봉인)")
            build(conn, dev, POOL_PATH, split_meta)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
