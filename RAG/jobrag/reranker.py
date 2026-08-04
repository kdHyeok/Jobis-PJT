"""크로스인코더 재순위 — BAAI/bge-reranker-v2-m3 + 마이크로배치.

RRF 병합 후, Evaluator 전 단계. (쿼리, 청크텍스트) 쌍을 직접 어텐션으로 채점해
dense/tech 두 축이 놓치는 의미적 적합성(예: "백엔드" 쿼리에 프론트엔드 공고 감점)을 잡는다.
실패 시 RRF 순위 그대로 폴백 — 재순위는 있으면 좋은 개선이지 필수 경로가 아니다.

동시 요청 시 각 요청의 (query, text) 쌍을 큐에 모아 한 번의 predict()로 처리한다.
단일 요청이어도 BATCH_TIMEOUT_S 후 즉시 실행되므로 지연은 최대 30ms.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

_model = None
_backend = "unavailable"

# max_length을 안 정하면 입력마다 패딩 길이가 달라져서 매 호출 CUDA 커널을
# 새로 벤치마크(cuDNN 알고리즘 탐색)한다 — 384로 고정하면 안정.
MAX_LENGTH = 384

BATCH_TIMEOUT_S = 0.030  # 30ms — 단일 요청 추가 지연 vs 동시 처리 이득의 균형점
MAX_BATCH_SLOTS = 10     # 이만큼 모이면 타임아웃 전이라도 즉시 실행


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


# ── 마이크로배치 인프라 ──────────────────────────────────────────

@dataclass
class _Slot:
    """한 rerank() 호출이 큐에 등록하는 단위."""
    pairs: list[tuple[str, str]]      # (query, text) 쌍
    result: list[float] | None = None
    error: Exception | None = None
    done: threading.Event = field(default_factory=threading.Event)


class _BatchQueue:
    """동시 rerank 요청을 모아 한 번의 predict()로 처리."""

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: list[_Slot] = []
        self._timer: threading.Timer | None = None

    def submit(self, pairs: list[tuple[str, str]]) -> _Slot:
        slot = _Slot(pairs=pairs)
        with self._lock:
            self._slots.append(slot)
            if len(self._slots) >= MAX_BATCH_SLOTS:
                self._cancel_timer()
                batch = self._drain()
            else:
                if self._timer is None:
                    self._timer = threading.Timer(BATCH_TIMEOUT_S, self._on_timeout)
                    self._timer.daemon = True
                    self._timer.start()
                batch = None

        if batch:
            self._execute(batch)
        return slot

    def _on_timeout(self):
        with self._lock:
            self._timer = None
            batch = self._drain()
        if batch:
            self._execute(batch)

    def _drain(self) -> list[_Slot]:
        slots = self._slots
        self._slots = []
        return slots

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _execute(self, slots: list[_Slot]):
        model = _load()
        if model is None:
            for s in slots:
                s.result = None
                s.done.set()
            return

        all_pairs = []
        boundaries = []  # (start, end) per slot
        for s in slots:
            start = len(all_pairs)
            all_pairs.extend(s.pairs)
            boundaries.append((start, len(all_pairs)))

        try:
            all_scores = model.predict(all_pairs)
            for s, (lo, hi) in zip(slots, boundaries):
                s.result = [float(sc) for sc in all_scores[lo:hi]]
                s.done.set()
        except Exception as exc:
            for s in slots:
                s.error = exc
                s.done.set()


_queue = _BatchQueue()


def rerank(query: str, pairs: list[tuple[str, str]]) -> list[float] | None:
    """pairs: (posting_uid, chunk_text) 목록. 실패 시 None(호출측이 RRF 순위로 폴백).

    동시 호출 시 내부 배치 큐에 모여 한 번의 GPU 호출로 처리된다.
    단일 호출이어도 최대 30ms 대기 후 즉시 실행."""
    if not pairs:
        return []
    if _load() is None:
        return None

    ce_pairs = [(query, text) for _, text in pairs]
    slot = _queue.submit(ce_pairs)
    slot.done.wait()

    if slot.error is not None:
        return None
    return slot.result
