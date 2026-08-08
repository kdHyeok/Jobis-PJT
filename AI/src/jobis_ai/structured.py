"""구조화 출력 헬퍼 (설계 8.4 / 9.4 의 `with_structured_output` 계층).

노드는 프롬프트와 Pydantic 스키마만 넘기면 되고, LLM provider·structured output
호출 방식은 이 파일이 흡수한다. provider 교체 시 노드는 손대지 않는다.

실패는 두 가지로 구분해 (None, warnings) 로 돌려준다:
- 키 없음(llm_not_configured): 개발/스켈레톤 모드 → 노드가 mock 샘플로 폴백해도 됨.
- 호출 실패(llm_call_failed): 키는 있는데 호출이 실패 → **재시도 후에도 안 되면** 노드는
  가짜 샘플을 내지 말고 '생성 실패(빈 결과 + 경고)'로 정직하게 처리해야 한다.
호출 실패는 여기서 먼저 여러 번 재시도한다(일시적 오류 흡수).

**재시도 소진은 로그에 WARNING 으로 남긴다.** 실측 사고(07-29): Claude CLI 인자 하나가 빠져
자기 루프 층이 통째로 죽었는데 결정론 폴백이 그럴듯하게 답해서 **아무도 몰랐다.** 경고는
응답 객체에 실려 아무도 읽지 않았고 trace 는 턴 끝에 사라졌다 — 남는 곳이 없었다.
LLM 호출 지점 16개가 전부 이 파일을 지나므로, 여기 한 줄이 그 전부를 덮는다.

**사용량(콜·토큰)도 여기서 걷는다** — 같은 이유다. 호출 지점 전부가 이 파일을 지나므로
`llm_usage.record` 한 자리가 "턴당 몇 콜, 토큰 몇"의 전체를 덮는다(평가 리포트 §1-2·§2-1).
토큰은 LangChain 콜백(구조화)·청크 usage(스트리밍)에서 걷고, 못 걷는 공급자는 None 으로
정직하게 남긴다 — 0 으로 지어내지 않는다.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from langchain_core.runnables import Runnable
from pydantic import BaseModel

from jobis_ai import llm_usage, trace
from jobis_ai.llm import LLMNotConfiguredError, get_llm

log = logging.getLogger(__name__)

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


def _retryable(exc: Exception) -> bool:
    """공급자가 영구 실패로 표시한 오류는 같은 입력으로 다시 보내지 않는다."""

    return bool(getattr(exc, "retryable", True))


def llm_unconfigured(warnings: list[dict]) -> bool:
    """경고가 '키 없음'(개발 모드)인지 판별. True 면 노드가 mock 샘플 폴백을 써도 된다.

    False 인데 결과가 None 이면 '호출 실패'이므로, 노드는 가짜 샘플 대신 정직한 빈 결과를 내야 한다.
    """

    return any(w.get("code") == "llm_not_configured" for w in warnings)


# 형식 위반(JSON 이 아님·스키마 불일치)의 지문. 네트워크·레이트리밋·타임아웃 실패와 갈라야
# 한다 — 그건 프롬프트 잘못이 아니라서 교정문을 붙일 이유가 없다.
_FORMAT_ERROR_MARKS = ("validation error", "json_invalid", "invalid json",
                       "jsondecodeerror", "expecting value", "field required")


def _repair_message(exc: Exception) -> str | None:
    """형식 위반 재시도에 실을 교정문. 형식 문제가 아니면 None.

    **왜 필요한가**: 재시도가 같은 프롬프트를 그대로 다시 보내면 형식 위반은 같은 자리에서
    같은 실패를 반복한다(flaky 가 아니라 stable-wrong — AGENTS.md §3-3). 실측(2026-08-03,
    `posting_analysis` 자기 루프): 모델이 `LoopDecision` 을 JSON 대신 마크다운
    (`**action**: read_posting …`)으로 내 3회 재시도가 전부 죽고, 결정론 폴백이 사용자에게
    "분석 결과"처럼 나갔다. 지시(“JSON 하나만”)는 이미 있었다 — 없던 것은 **틀렸다는 사실을
    모델에게 돌려주는 일**이다.

    스키마를 서버가 강제하는 공급자(openai/anthropic)는 이 자리에 오지 않는다.
    """

    text = str(exc)
    if not any(mark in text.lower() for mark in _FORMAT_ERROR_MARKS):
        return None
    return (
        "직전 응답이 규격을 어겨 사용할 수 없었다. 검증 오류:\n"
        f"{text[:500]}\n"
        "이번에는 스키마에 맞는 **JSON 객체 하나만** 출력하라. 첫 글자는 `{` 여야 한다. "
        "마크다운(`**필드**: 값`)·제목·설명·코드펜스를 붙이지 마라."
    )


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
        llm_usage.record(node=node, tier=tier, outcome="not_configured", attempts=0)
        return None, warnings

    # OpenAI(GMS) 경유는 기본 method(json_schema strict)가 기본값 있는 필드를 거부해
    # 호출이 실패한다(langchain-openai>=0.3). 경고 안내대로 function_calling 을 명시한다.
    from jobis_ai.config import get_settings

    method_kwargs = (
        {"method": "function_calling"} if get_settings().llm_provider == "openai" else {}
    )
    structured_llm = llm.with_structured_output(schema, **method_kwargs)
    messages = [("system", system_prompt), ("human", content)]

    # 토큰은 콜백으로 걷는다 — 구조화 출력은 파싱된 객체만 돌려줘 응답의 usage 가 사라진다.
    # LangChain Runnable 이 아닌 어댑터(claude_code CLI)는 config 를 못 받으므로 안 넘긴다
    # — 그 콜은 토큰 None(unmetered)으로 기록된다.
    usage_cb = llm_usage.UsageCallbackHandler()
    invoke_kwargs = (
        {"config": {"callbacks": [usage_cb]}} if isinstance(structured_llm, Runnable) else {}
    )

    # 일시적 오류(네트워크·레이트리밋·파싱)를 흡수하기 위해 여러 번 재시도한다.
    last_exc: Exception | None = None
    attempts_made = 0
    started = time.perf_counter()
    base_messages = messages
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        attempts_made = attempt
        try:
            result = structured_llm.invoke(messages, **invoke_kwargs)
            duration_ms = round((time.perf_counter() - started) * 1000)
            input_tokens, output_tokens = usage_cb.tokens()
            trace.emit("llm_call", f"{node}: LLM 호출 성공", {
                "node": node, "schema": schema.__name__, "outcome": "ok",
                "tier": tier, "attempt": attempt,
                "durationMs": duration_ms,
                "inputTokens": input_tokens, "outputTokens": output_tokens,
                "systemPrompt": system_prompt,
                "input": content,
                "output": result.model_dump(),
            })
            llm_usage.record(node=node, tier=tier, outcome="ok", attempts=attempt,
                             duration_ms=duration_ms,
                             input_tokens=input_tokens, output_tokens=output_tokens)
            return result, warnings
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도/폴백 대상
            last_exc = exc
            if attempt < _MAX_ATTEMPTS and _retryable(exc):
                # 형식 위반은 **같은 프롬프트를 다시 보내면 같은 실패가 반복된다.**
                # 힌트는 매번 base 위에 하나만 붙인다(쌓으면 입력이 불어난다).
                repair = _repair_message(exc)
                messages = base_messages if repair is None else [
                    *base_messages, ("human", repair)]
                time.sleep(_RETRY_BACKOFF_SEC * attempt)
                continue
            break

    warnings.append({
        "code": "llm_call_failed",
        "message": f"{node}: LLM 호출 {attempts_made}회 시도 후 실패 — {last_exc}",
    })
    duration_ms = round((time.perf_counter() - started) * 1000)
    # 실패한 시도도 응답까지 왔다가 파싱에서 죽었으면 토큰은 태웠다 — 실패 콜의 토큰도 합계에 든다.
    input_tokens, output_tokens = usage_cb.tokens()
    trace.emit("llm_call", f"{node}: LLM 호출 실패({attempts_made}회 시도)", {
        "node": node, "schema": schema.__name__, "outcome": "failed",
        "durationMs": duration_ms,
        "error": str(last_exc), "input": content,
    })
    llm_usage.record(node=node, tier=tier, outcome="failed", attempts=attempts_made,
                     duration_ms=duration_ms,
                     input_tokens=input_tokens, output_tokens=output_tokens)
    # 폴백이 그럴듯해도 로그에는 남는다 — 성공은 INFO 도 안 남기지만 실패는 WARNING 이다.
    log.warning("LLM 호출 실패: node=%s schema=%s tier=%s %d회 시도 후 포기 — %r",
                node, schema.__name__, tier, attempts_made, last_exc)
    return None, warnings


# 토큰 스트리밍 시 이 크기만큼 모아서 trace 로 흘린다 — 이벤트 폭주 방지.
_STREAM_FLUSH_CHARS = 16


def _content_text(content: object) -> str:
    """LangChain 메시지 content 에서 사용자향 텍스트만 뽑는다.

    anthropic 직접 호출(thinking 켜진 모델)은 content 가 문자열이 아니라
    [{"type": "thinking", ...}, {"type": "text", ...}] 블록 리스트로 온다.
    str() 폴백은 thinking 시그니처 repr 을 섞어 JSON 파싱을 오염시킨다.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content or "")


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
        llm_usage.record(node=node, tier=tier, outcome="not_configured", attempts=0)
        return "", warnings

    messages = [("system", system_prompt), ("human", content)]
    # 스트리밍 미지원 provider(claude_code CLI 등)는 invoke 한 번으로 대신한다 —
    # 완성본을 token 이벤트 하나로 흘려 호출부·프론트 경로는 동일하게 유지된다.
    streamable = hasattr(llm, "stream")
    last_exc: Exception | None = None
    attempts_made = 0
    started = time.perf_counter()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        attempts_made = attempt
        parts: list[str] = []
        buffer = ""
        usage: dict | None = None      # 스트리밍은 마지막 청크에 usage 합계가 실린다(stream_usage)
        try:
            if streamable:
                for chunk in llm.stream(messages):
                    usage = getattr(chunk, "usage_metadata", None) or usage
                    piece = _content_text(chunk.content)
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
                usage = getattr(result, "usage_metadata", None)
                whole = _content_text(result.content)
                parts.append(whole)
                if whole:
                    trace.emit("token", node, {"node": node, "text": whole})
            text = "".join(parts).strip()
            duration_ms = round((time.perf_counter() - started) * 1000)
            input_tokens = int(usage["input_tokens"]) if usage and "input_tokens" in usage else None
            output_tokens = int(usage["output_tokens"]) if usage and "output_tokens" in usage else None
            trace.emit("llm_call", f"{node}: LLM 스트리밍 성공", {
                "node": node, "schema": "(streaming text)", "outcome": "ok",
                "tier": tier, "attempt": attempt, "chars": len(text),
                "durationMs": duration_ms,
                "inputTokens": input_tokens, "outputTokens": output_tokens,
            })
            llm_usage.record(node=node, tier=tier, outcome="ok", attempts=attempt,
                             duration_ms=duration_ms,
                             input_tokens=input_tokens, output_tokens=output_tokens)
            return text, warnings
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도/폴백 대상
            last_exc = exc
            if attempt < _MAX_ATTEMPTS and _retryable(exc):
                time.sleep(_RETRY_BACKOFF_SEC * attempt)
                continue
            break

    warnings.append({
        "code": "llm_call_failed",
        "message": f"{node}: LLM 스트리밍 {attempts_made}회 시도 후 실패 — {last_exc}",
    })
    duration_ms = round((time.perf_counter() - started) * 1000)
    trace.emit("llm_call", f"{node}: LLM 스트리밍 실패({attempts_made}회 시도)", {
        "node": node, "schema": "(streaming text)", "outcome": "failed",
        "durationMs": duration_ms,
        "error": str(last_exc),
    })
    llm_usage.record(node=node, tier=tier, outcome="failed", attempts=attempts_made,
                     duration_ms=duration_ms)
    log.warning("LLM 스트리밍 실패: node=%s tier=%s %d회 시도 후 포기 — %r",
                node, tier, attempts_made, last_exc)
    return "", warnings
