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

# 모델별 단가 (USD / 1M 토큰, 입력·출력). **이 표는 낡는다** — 공급자가 가격을 바꾸면 여기도
# 바뀌어야 하고, 안 바꾸면 비용 숫자가 조용히 죽는다(baseline 이 죽던 것과 같은 종류의 사고다).
# 그래서 `costBasis` 로 기준일을 요약에 함께 실어 보낸다.
#
# **모르는 모델은 추정하지 않는다**(§2-1 모른다 ≠ 0): 표에 없으면 그 콜의 비용은 None 이고
# `uncostedCalls` 로 따로 센다. 구독형(claude_code CLI)은 애초에 토큰을 안 주므로 여기 없다 —
# 콜당 단가라는 개념이 성립하지 않는 경로이고, 그 사실이 `unmeteredCalls` 로 이미 남는다.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4.1":      (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
}
PRICE_BASIS = "2026-08-04"


def call_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """콜 하나의 비용. 단가를 모르거나 토큰을 못 쟀으면 **None**(0 이 아니다)."""

    price = MODEL_PRICES_USD_PER_MTOK.get((model or "").strip())
    if price is None or input_tokens is None:
        return None
    return (input_tokens * price[0] + (output_tokens or 0) * price[1]) / 1_000_000


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
        costs = [call_cost_usd(c.get("model") or "", c.get("inputTokens"), c.get("outputTokens"))
                 for c in ok + failed]
        priced = [c for c in costs if c is not None]
        return {
            "calls": len(ok) + len(failed),
            "ok": len(ok),
            "failed": len(failed),
            "notConfigured": sum(1 for c in self.calls if c["outcome"] == "not_configured"),
            "retries": sum(max(0, int(c.get("attempts") or 1) - 1) for c in ok + failed),
            "inputTokens": sum(c["inputTokens"] for c in metered) if metered else None,
            "outputTokens": sum(c.get("outputTokens") or 0 for c in metered) if metered else None,
            "unmeteredCalls": len(ok) + len(failed) - len(metered),
            # 비용은 **단가를 아는 콜의 합**이다. 하나도 없으면 None — 0 이라고 하면
            # "공짜로 돌았다"로 읽힌다.
            "costUsd": round(sum(priced), 6) if priced else None,
            "uncostedCalls": len(costs) - len(priced),
            "costBasis": PRICE_BASIS,
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
    """활성 수집기가 있으면 논리 콜 1건을 기록, 없으면 no-op (trace.emit 과 같은 규약).

    모델명은 인자로 받지 않고 **`Settings.active_model(tier)` 에서 파생한다** — 호출부가
    따로 적으면 언젠가 실제 부른 모델과 갈린다(하네스가 `llm_model` 을 프로바이더와 무관하게
    적어 baseline 에 모델이 오귀속됐던 것과 같은 실수다. §4-3·D58).
    """

    collector = _current.get()
    if collector is None:
        return
    try:
        from jobis_ai.config import get_settings
        model = get_settings().active_model(tier)
    except Exception:   # noqa: BLE001 — 계측이 실행을 막지 않는다
        model = ""
    collector.record({
        "node": node, "tier": tier, "model": model, "outcome": outcome, "attempts": attempts,
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
