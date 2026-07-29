"""크로스인코더 재순위 — BAAI/bge-reranker-v2-m3.

RRF 병합 후, Evaluator 전 단계. (쿼리, 청크텍스트) 쌍을 직접 어텐션으로 채점해
dense/tech 두 축이 놓치는 의미적 적합성(예: "백엔드" 쿼리에 프론트엔드 공고 감점)을 잡는다.
실패 시 RRF 순위 그대로 폴백 — 재순위는 있으면 좋은 개선이지 필수 경로가 아니다.
"""
from __future__ import annotations

_model = None
_backend = "unavailable"

# max_length을 안 정하면 입력마다 패딩 길이가 달라져서 매 호출 CUDA 커널을
# 새로 벤치마크(cuDNN 알고리즘 탐색)한다 — 실측 결과 동일 30쌍에서 6~35초로
# 5배 넘게 들쭉날쭉했다. 384로 고정하니 1.9초로 안정. 우리 청크 프리픽스(~80tok)
# + 본문 앞부분(담당업무/자격요건)이 이 안에 들어오므로 핵심 신호는 보존된다.
MAX_LENGTH = 384


def _load():
    global _model, _backend
    if _model is not None or _backend == "failed":
        return _model
    try:
        import torch
        from sentence_transformers import CrossEncoder
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=MAX_LENGTH, device=device)
        _backend = f"bge-reranker-v2-m3({device})"
    except Exception:
        _model = None
        _backend = "failed"
    return _model


def warmup():
    _load()


def backend() -> str:
    return _backend


def rerank(query: str, pairs: list[tuple[str, str]]) -> list[float] | None:
    """pairs: (posting_uid, chunk_text) 목록. 실패 시 None(호출측이 RRF 순위로 폴백)."""
    if not pairs:
        return []
    model = _load()
    if model is None:
        return None
    try:
        scores = model.predict([(query, text) for _, text in pairs])
        return [float(s) for s in scores]
    except Exception:
        return None
