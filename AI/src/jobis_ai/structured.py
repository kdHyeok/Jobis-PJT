"""구조화 출력 헬퍼 (설계 8.4 / 9.4 의 `with_structured_output` 계층).

노드는 프롬프트와 Pydantic 스키마만 넘기면 되고, LLM provider·structured output
호출 방식은 이 파일이 흡수한다. provider 교체 시 노드는 손대지 않는다.

실패는 두 가지로 구분해 (None, warnings) 로 돌려준다:
- 키 없음(llm_not_configured): 개발/스켈레톤 모드 → 노드가 mock 샘플로 폴백해도 됨.
- 호출 실패(llm_call_failed): 키는 있는데 호출이 실패 → **재시도 후에도 안 되면** 노드는
  가짜 샘플을 내지 말고 '생성 실패(빈 결과 + 경고)'로 정직하게 처리해야 한다.
호출 실패는 여기서 먼저 여러 번 재시도한다(일시적 오류 흡수).
"""

from __future__ import annotations

import time
from typing import TypeVar

from pydantic import BaseModel

from jobis_ai import trace
from jobis_ai.llm import LLMNotConfiguredError, get_llm

T = TypeVar("T", bound=BaseModel)

# 본문이 너무 길면 토큰·비용이 커지므로 상한을 둔다(설계 16 견고성).
_MAX_INPUT_CHARS = 16000

# 상한 초과 시 뒤쪽을 무조건 버리면 안 된다 — 한국 채용공고는 자격요건·우대사항이
# 후반부에 몰린다. 이 키워드가 잘려 나가는 위치에 있으면 그 이후를 살려서 붙인다.
_TAIL_KEYWORDS = ("자격요건", "자격 요건", "지원자격", "지원 자격", "우대사항", "우대 사항", "필수요건")
_TAIL_BUDGET = 5000


def _truncate(content: str, node: str, warnings: list[dict]) -> str:
    """상한 초과 입력을 자르되, 잘려 나갈 후반부에 자격/우대 섹션이 있으면 보존한다."""

    if len(content) <= _MAX_INPUT_CHARS:
        return content
    head_len = _MAX_INPUT_CHARS - _TAIL_BUDGET
    tail_start = min(
        (idx for kw in _TAIL_KEYWORDS if (idx := content.find(kw, head_len)) != -1),
        default=-1,
    )
    if tail_start != -1:
        content = (content[:head_len] + "\n…(중략)…\n"
                   + content[tail_start:tail_start + _TAIL_BUDGET])
        warnings.append({"code": "input_truncated", "message": (
            f"{node}: 입력이 길어 앞 {head_len}자 + 자격/우대 섹션 이후를 보존해 잘랐습니다.")})
    else:
        content = content[:_MAX_INPUT_CHARS]
        warnings.append({"code": "input_truncated",
                         "message": f"{node}: 입력이 길어 {_MAX_INPUT_CHARS}자로 잘랐습니다."})
    return content

# LLM 호출 실패 시 재시도 정책 (일시적 오류 흡수). 노드가 가짜 폴백으로 넘어가기 전에 여기서 먼저 재시도.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = 1.5


def llm_unconfigured(warnings: list[dict]) -> bool:
    """경고가 '키 없음'(개발 모드)인지 판별. True 면 노드가 mock 샘플 폴백을 써도 된다.

    False 인데 결과가 None 이면 '호출 실패'이므로, 노드는 가짜 샘플 대신 정직한 빈 결과를 내야 한다.
    """

    return any(w.get("code") == "llm_not_configured" for w in warnings)


def run_structured(
    schema: type[T],
    system_prompt: str,
    user_content: str,
    *,
    node: str,
    tier: str = "default",
) -> tuple[T | None, list[dict]]:
    """schema 로 구조화된 결과를 뽑는다. 실패 시 (None, warnings).

    Parameters
    ----------
    schema : 반환받을 Pydantic 모델 타입
    system_prompt : 역할·규칙을 정의하는 시스템 지시문
    user_content : 분석 대상 원문(공고/이력서 텍스트 등)
    node : 경고 메시지에 남길 노드 이름
    tier : 모델 등급 — "default"(고급: 추출·생성) | "light"(경량: 분류·이진판정·요약)
    """

    warnings: list[dict] = []
    content = (user_content or "").strip()
    if not content:
        warnings.append({"code": "empty_input", "message": f"{node}: 분석할 텍스트가 없습니다."})
        return None, warnings

    content = _truncate(content, node, warnings)

    try:
        llm = get_llm(tier)
    except LLMNotConfiguredError as exc:
        warnings.append({"code": "llm_not_configured", "message": f"{node}: {exc}"})
        trace.emit("llm_call", f"{node}: LLM 미설정 — 호출 생략", {
            "node": node, "schema": schema.__name__, "outcome": "not_configured",
        })
        return None, warnings

    # OpenAI(GMS) 경유는 기본 method(json_schema strict)가 기본값 있는 필드를 거부해
    # 호출이 실패한다(langchain-openai>=0.3). 경고 안내대로 function_calling 을 명시한다.
    from jobis_ai.config import get_settings

    method_kwargs = (
        {"method": "function_calling"} if get_settings().llm_provider == "openai" else {}
    )
    structured_llm = llm.with_structured_output(schema, **method_kwargs)
    messages = [("system", system_prompt), ("human", content)]

    # 일시적 오류(네트워크·레이트리밋·파싱)를 흡수하기 위해 여러 번 재시도한다.
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            result = structured_llm.invoke(messages)
            trace.emit("llm_call", f"{node}: LLM 호출 성공", {
                "node": node, "schema": schema.__name__, "outcome": "ok",
                "tier": tier, "attempt": attempt,
                "durationMs": round((time.perf_counter() - started) * 1000),
                "systemPrompt": system_prompt,
                "input": content,
                "output": result.model_dump(),
            })
            return result, warnings
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도/폴백 대상
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC * attempt)

    warnings.append({
        "code": "llm_call_failed",
        "message": f"{node}: LLM 호출 {_MAX_ATTEMPTS}회 재시도 후 실패 — {last_exc}",
    })
    trace.emit("llm_call", f"{node}: LLM 호출 실패({_MAX_ATTEMPTS}회 재시도)", {
        "node": node, "schema": schema.__name__, "outcome": "failed",
        "durationMs": round((time.perf_counter() - started) * 1000),
        "error": str(last_exc), "input": content,
    })
    return None, warnings


# 토큰 스트리밍 시 이 크기만큼 모아서 trace 로 흘린다 — 이벤트 폭주 방지.
_STREAM_FLUSH_CHARS = 16


def run_streaming_text(
    system_prompt: str,
    user_content: str,
    *,
    node: str,
    tier: str = "default",
) -> tuple[str, list[dict]]:
    """표현 계층 전용 — 스키마 없이 텍스트를 **토큰 스트리밍**으로 생성한다.

    reply 문자열 하나뿐인 표현 계층(career_chat 등)은 구조화 출력이 줄 게 없고,
    통짜 도착이 체감 지연의 대부분이다. 토큰이 생기는 대로 trace("token") 으로 흘리고
    (웹 브릿지가 SSE delta 로 중계), 전체 텍스트를 모아 반환한다 — 금지표현 검증은
    호출부가 완성본에 대해 수행한다(사후 검증, 하네스 유지).

    실패 처리는 run_structured 와 동일: 미설정 → ("", llm_not_configured),
    재시도 소진 → ("", llm_call_failed). 부분 스트림 후 실패하면 그 시도는 버린다 —
    잘린 문장을 답으로 내보내지 않는다(재시도 시 새 스트림으로 다시 흘린다).
    """

    warnings: list[dict] = []
    content = (user_content or "").strip()
    if not content:
        warnings.append({"code": "empty_input", "message": f"{node}: 분석할 텍스트가 없습니다."})
        return "", warnings
    content = _truncate(content, node, warnings)

    try:
        llm = get_llm(tier)
    except LLMNotConfiguredError as exc:
        warnings.append({"code": "llm_not_configured", "message": f"{node}: {exc}"})
        trace.emit("llm_call", f"{node}: LLM 미설정 — 호출 생략", {
            "node": node, "schema": "(streaming text)", "outcome": "not_configured",
        })
        return "", warnings

    messages = [("system", system_prompt), ("human", content)]
    # 스트리밍 미지원 provider(claude_code CLI 등)는 invoke 한 번으로 대신한다 —
    # 완성본을 token 이벤트 하나로 흘려 호출부·프론트 경로는 동일하게 유지된다.
    streamable = hasattr(llm, "stream")
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        parts: list[str] = []
        buffer = ""
        try:
            if streamable:
                for chunk in llm.stream(messages):
                    piece = chunk.content if isinstance(chunk.content, str) else str(chunk.content or "")
                    if not piece:
                        continue
                    parts.append(piece)
                    buffer += piece
                    if len(buffer) >= _STREAM_FLUSH_CHARS:
                        trace.emit("token", node, {"node": node, "text": buffer})
                        buffer = ""
                if buffer:
                    trace.emit("token", node, {"node": node, "text": buffer})
            else:
                result = llm.invoke(messages)
                whole = result.content if isinstance(result.content, str) else str(result.content or "")
                parts.append(whole)
                if whole:
                    trace.emit("token", node, {"node": node, "text": whole})
            text = "".join(parts).strip()
            trace.emit("llm_call", f"{node}: LLM 스트리밍 성공", {
                "node": node, "schema": "(streaming text)", "outcome": "ok",
                "tier": tier, "attempt": attempt, "chars": len(text),
                "durationMs": round((time.perf_counter() - started) * 1000),
            })
            return text, warnings
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도/폴백 대상
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC * attempt)

    warnings.append({
        "code": "llm_call_failed",
        "message": f"{node}: LLM 스트리밍 {_MAX_ATTEMPTS}회 재시도 후 실패 — {last_exc}",
    })
    trace.emit("llm_call", f"{node}: LLM 스트리밍 실패({_MAX_ATTEMPTS}회 재시도)", {
        "node": node, "schema": "(streaming text)", "outcome": "failed",
        "durationMs": round((time.perf_counter() - started) * 1000),
        "error": str(last_exc),
    })
    return "", warnings
