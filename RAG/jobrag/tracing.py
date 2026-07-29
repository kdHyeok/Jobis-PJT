"""표준 로깅 스키마 (평가계획 Layer 1 — 구현 우선순위 #1).

모든 노드가 동일 스키마로 logs/trace.jsonl에 기록:
{ trace_id, node_name, stage, input_summary, output_summary,
  metrics, duration_ms, status, error, timestamp }

로깅은 항상 ON(§6.4). 골든셋 지표 계산은 여기서 하지 않는다 — 조건부 별도 실행.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _write(record: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@contextmanager
def node_span(trace_id: str, node_name: str, stage: str, input_summary: str = ""):
    """노드 실행 구간 측정. span.metrics / span.output_summary를 채워서 반환."""
    span = _Span()
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        yield span
    except Exception as e:  # 실패도 동일 스키마로 기록 후 재전파
        status, error = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        _write({
            "trace_id": trace_id,
            "node_name": node_name,
            "stage": stage,                       # batch | query
            "input_summary": input_summary,
            "output_summary": span.output_summary,
            "metrics": span.metrics,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "status": status,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


class _Span:
    def __init__(self):
        self.metrics: dict = {}
        self.output_summary: str = ""
