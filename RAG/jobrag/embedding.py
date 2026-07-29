"""BGE-M3 dense 임베딩 (1024d), L2 정규화 후 저장 → 코사인=내적.

실패 청크는 1회 재시도 후 스킵하고 로그만 남긴다 (임베딩 성공률 ≥99.5% 지표).
"""
from __future__ import annotations

import numpy as np

_model = None


def _load():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def warmup():
    _load()


def embed_texts(texts: list[str], batch_size: int = 16) -> tuple[list[list[float] | None], dict]:
    """반환: (임베딩 리스트, {"attempted": n, "succeeded": n, "failed": n})."""
    if not texts:  # 전량 재사용된 배치 — 모델 로딩조차 하지 않는다
        return [], {"attempted": 0, "succeeded": 0, "failed": 0}
    model = _load()
    out: list[list[float] | None] = [None] * len(texts)
    failed = 0
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        idxs = list(range(start, start + len(batch)))
        vecs = _encode_with_retry(model, batch)
        if vecs is None:
            failed += len(batch)
            continue
        for i, v in zip(idxs, vecs):
            out[i] = v.tolist()
    stats = {"attempted": len(texts), "succeeded": len(texts) - failed, "failed": failed}
    return out, stats


def _encode_with_retry(model, batch: list[str], retries: int = 1):
    for attempt in range(retries + 1):
        try:
            vecs = model.encode(batch, normalize_embeddings=True, convert_to_numpy=True)
            return vecs
        except Exception:
            if attempt == retries:
                return None
    return None


def content_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
