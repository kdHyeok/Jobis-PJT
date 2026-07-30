"""LLM 사용량 집계 — "이 턴이 몇 콜로 결론에 도달했고 토큰을 얼마나 태웠나"를 숫자로 만든다.

평가 리포트(4영역 16지표)가 영구 미확정으로 남긴 공백을 닫는 계층이다:
- §1-2 턴당 LLM 호출 횟수를 세는 집계기가 없다 (trace 는 턴 종료 시 소멸)
- §2-1 `usage_metadata`/`prompt_tokens` 를 읽는 코드 0곳 — 토큰 실측 0
- §2-3 비용 대비 성능 — 분자가 없어 판정 불능

trace 로 세지 않는 이유: trace 는 창문이다(레코더가 없으면 no-op, 이벤트는 턴 끝에 사라진다).
집계는 별도 contextvar 수집기로 돈다 — `chat.handle_chat` 이 턴마다 열고, 평가 하네스는
run 마다 연다. 중첩되면 부모에게도 전달한다(하네스가 턴 안의 콜을 놓치지 않게 —
trace.TraceRecorder 의 _parent 와 같은 규약).

**모른다 ≠ 0** (AGENTS §2-1): 토큰을 주지 않는 공급자(claude_code CLI)의 콜은 추정하지 않고
토큰 None 으로 기록해 `unmeteredCalls` 로 따로 센다. 합계는 "잰 콜의 합"이며, 전체가 아닐 수
있다는 사실 자체가 숫자(unmeteredCalls > 0)로 남는다.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler

_current: contextvars.ContextVar["UsageCollector | None"] = contextvars.ContextVar(
    "jobis_llm_usage", default=None
)


class UsageCallbackHandler(BaseCallbackHandler):
    """LangChain 콜백으로 `usage_metadata` 를 걷는다.

    구조화 출력(with_structured_output)은 파싱된 객체만 돌려줘 응답의 usage 가 사라진다 —
    콜백은 파서 앞의 모델 단계에서 걷으므로 그 손실이 없다. 재시도 중 "응답은 왔는데 파싱이
    실패"한 시도도 잡힌다: 그 토큰은 실제로 태웠으므로 합계에 드는 것이 맞다.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.metered = False

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: ANN401
        for gens in getattr(response, "generations", None) or []:
            for gen in gens:
                usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if usage:
                    self.input_tokens += int(usage.get("input_tokens") or 0)
                    self.output_tokens += int(usage.get("output_tokens") or 0)
                    self.metered = True

    def tokens(self) -> tuple[int | None, int | None]:
        """(입력, 출력) — 한 번도 usage 를 못 받았으면 (None, None). 0 으로 지어내지 않는다."""

        return (self.input_tokens, self.output_tokens) if self.metered else (None, None)


class UsageCollector:
    """논리 콜(재시도 포함 1건) 단위 기록 누적기. 병렬 에이전트 구간에서도 안전하다."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._parent: "UsageCollector | None" = None

    def record(self, call: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append(call)
        if self._parent is not None:
            self._parent.record(call)

    def summary(self) -> dict[str, Any]:
        """집계 요약. `calls` 는 실제 네트워크 시도가 일어난 논리 콜(ok+failed)만 센다.

        `notConfigured`(키 없음 — 호출 자체가 없었다)를 콜로 세면 개발 모드의 스켈레톤
        실행이 "콜 N건"으로 보인다.
        """

        ok = [c for c in self.calls if c["outcome"] == "ok"]
        failed = [c for c in self.calls if c["outcome"] == "failed"]
        metered = [c for c in ok + failed if c.get("inputTokens") is not None]
        by_node: dict[str, int] = {}
        for call in ok + failed:
            by_node[call["node"]] = by_node.get(call["node"], 0) + 1
        return {
            "calls": len(ok) + len(failed),
            "ok": len(ok),
            "failed": len(failed),
            "notConfigured": sum(1 for c in self.calls if c["outcome"] == "not_configured"),
            "retries": sum(max(0, int(c.get("attempts") or 1) - 1) for c in ok + failed),
            "inputTokens": sum(c["inputTokens"] for c in metered) if metered else None,
            "outputTokens": sum(c.get("outputTokens") or 0 for c in metered) if metered else None,
            "unmeteredCalls": len(ok) + len(failed) - len(metered),
            "durationMs": sum(int(c.get("durationMs") or 0) for c in ok + failed),
            "byNode": by_node,
        }


def record(
    *,
    node: str,
    tier: str,
    outcome: str,               # "ok" | "failed" | "not_configured"
    attempts: int = 1,
    duration_ms: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """활성 수집기가 있으면 논리 콜 1건을 기록, 없으면 no-op (trace.emit 과 같은 규약)."""

    collector = _current.get()
    if collector is None:
        return
    collector.record({
        "node": node, "tier": tier, "outcome": outcome, "attempts": attempts,
        "durationMs": duration_ms,
        "inputTokens": input_tokens, "outputTokens": output_tokens,
    })


@contextmanager
def collecting() -> Iterator[UsageCollector]:
    """이 블록 안의 LLM 콜을 모두 담는 수집기를 활성화한다. 중첩이면 부모에게도 전달."""

    collector = UsageCollector()
    collector._parent = _current.get()
    token = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)
