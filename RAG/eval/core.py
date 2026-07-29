"""평가 핵심 유틸 — 스냅샷 검증, IR 지표, 부트스트랩, Chapman 추정."""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

ARCHIVE_PATH = Path(__file__).parent / "_archive" / "v3_exhaustive_3queries.json"
GRADE = {"Correct": 2, "Ambiguous": 1, "Incorrect": 0}


# ── 스냅샷 ──────────────────────────────────────────────

def snapshot_hash(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT uid FROM postings WHERE is_active ORDER BY uid")
        uids = [r[0] for r in cur.fetchall()]
    return hashlib.sha256("\n".join(uids).encode()).hexdigest()[:16]


def verify_snapshot(conn, expected: str) -> bool:
    return snapshot_hash(conn) == expected


# ── IR 지표 ─────────────────────────────────────────────

def _dcg(gains: list[float], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg_at_k(ranked_labels: list[str], qrels: dict[str, str], k: int = 3) -> float:
    gains = [GRADE.get(qrels.get(uid, "Incorrect"), 0) for uid in ranked_labels[:k]]
    ideal = sorted([GRADE.get(v, 0) for v in qrels.values()], reverse=True)
    idcg = _dcg(ideal, k)
    return _dcg(gains, k) / idcg if idcg > 0 else 0.0


def precision_at_k(ranked_labels: list[str], qrels: dict[str, str], k: int = 3) -> float:
    relevant = sum(1 for uid in ranked_labels[:k] if GRADE.get(qrels.get(uid, "Incorrect"), 0) >= 2)
    return relevant / k if k > 0 else 0.0


def ap_at_k(ranked_labels: list[str], qrels: dict[str, str], k: int = 3) -> float:
    hits = 0
    total = 0.0
    for i, uid in enumerate(ranked_labels[:k]):
        if GRADE.get(qrels.get(uid, "Incorrect"), 0) >= 2:
            hits += 1
            total += hits / (i + 1)
    n_rel = sum(1 for v in qrels.values() if GRADE.get(v, 0) >= 2)
    return total / min(n_rel, k) if n_rel > 0 else 0.0


# ── 정규화 (랜덤 바닥 / 풀 오라클 천장) ────────────────

def random_baseline_ndcg(qrels: dict[str, str], k: int, n_trials: int = 10000) -> float:
    uids = list(qrels.keys())
    if not uids:
        return 0.0
    ideal = sorted([GRADE.get(v, 0) for v in qrels.values()], reverse=True)
    idcg = _dcg(ideal, k)
    if idcg == 0:
        return 0.0
    total = 0.0
    for _ in range(n_trials):
        sample = random.sample(uids, min(k, len(uids)))
        gains = [GRADE.get(qrels.get(u, "Incorrect"), 0) for u in sample]
        total += _dcg(gains, k) / idcg
    return total / n_trials


def normalized_score(actual: float, rand_floor: float, oracle: float) -> float:
    span = oracle - rand_floor
    if span <= 0:
        return 0.0
    return max(0.0, (actual - rand_floor) / span)


# ── 쌍대 부트스트랩 ────────────────────────────────────

def paired_bootstrap(scores_a: list[float], scores_b: list[float],
                     n_resamples: int = 10000, seed: int = 42) -> dict:
    rng = random.Random(seed)
    n = len(scores_a)
    deltas = []
    for _ in range(n_resamples):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        deltas.append(
            sum(scores_b[i] for i in idx) / n - sum(scores_a[i] for i in idx) / n
        )
    deltas.sort()
    lo = deltas[int(n_resamples * 0.025)]
    hi = deltas[int(n_resamples * 0.975)]
    mean_delta = sum(deltas) / len(deltas)
    return {
        "mean_delta": round(mean_delta, 4),
        "ci_95": [round(lo, 4), round(hi, 4)],
        "significant": not (lo <= 0 <= hi),
    }


# ── 포획-재포획 (Chapman) ──────────────────────────────

def chapman_estimate(n1: int, n2: int, m: int) -> float:
    return (n1 + 1) * (n2 + 1) / (m + 1) - 1


def load_exhaustive_labels() -> dict[str, dict[str, str]]:
    if not ARCHIVE_PATH.exists():
        return {}
    data = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    return {qid: q["labels"] for qid, q in data.get("queries", {}).items()}


def pool_miss_bounds(pool_qrels: dict[str, str],
                     bm25_uids: list[str], dense_uids: list[str]) -> dict:
    bm25_rel = {u for u in bm25_uids if GRADE.get(pool_qrels.get(u, "Incorrect"), 0) >= 2}
    dense_rel = {u for u in dense_uids if GRADE.get(pool_qrels.get(u, "Incorrect"), 0) >= 2}
    m = len(bm25_rel & dense_rel)
    n_hat = chapman_estimate(len(bm25_rel), len(dense_rel), m)
    pool_rel = sum(1 for v in pool_qrels.values() if GRADE.get(v, 0) >= 2)
    missed = max(0.0, n_hat - pool_rel)
    return {
        "n1_bm25_rel": len(bm25_rel),
        "n2_dense_rel": len(dense_rel),
        "overlap": m,
        "chapman_N": round(n_hat, 1),
        "pool_rel": pool_rel,
        "estimated_missed": round(missed, 1),
    }


def bias_correction_bounds(exhaustive_labels: dict[str, dict[str, str]],
                           pool_builder, conn, region_vocab) -> dict:
    if not exhaustive_labels:
        return {"note": "no exhaustive labels available"}
    ratios = []
    for qid, labels in exhaustive_labels.items():
        truth_rel = sum(1 for v in labels.values() if GRADE.get(v, 0) >= 2)
        if truth_rel == 0:
            continue
        pool_qrels, bm25_uids, dense_uids = pool_builder(conn, qid, region_vocab)
        bm25_rel = sum(1 for u in bm25_uids if GRADE.get(labels.get(u, "Incorrect"), 0) >= 2)
        dense_rel = sum(1 for u in dense_uids if GRADE.get(labels.get(u, "Incorrect"), 0) >= 2)
        m = len({u for u in bm25_uids if GRADE.get(labels.get(u, "Incorrect"), 0) >= 2}
                & {u for u in dense_uids if GRADE.get(labels.get(u, "Incorrect"), 0) >= 2})
        n_hat = chapman_estimate(bm25_rel, dense_rel, m)
        if n_hat > 0:
            ratios.append(truth_rel / n_hat)
    if not ratios:
        return {"note": "no computable ratios"}
    return {
        "n_calibration_queries": len(ratios),
        "bias_ratio_range": [round(min(ratios), 3), round(max(ratios), 3)],
        "ratios": [round(r, 3) for r in ratios],
    }
