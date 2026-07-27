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

from jobis_ai.llm import LLMNotConfiguredError, get_llm

T = TypeVar("T", bound=BaseModel)

# 본문이 너무 길면 토큰·비용이 커지므로 상한을 둔다(설계 16 견고성).
_MAX_INPUT_CHARS = 16000

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
) -> tuple[T | None, list[dict]]:
    """schema 로 구조화된 결과를 뽑는다. 실패 시 (None, warnings).

    Parameters
    ----------
    schema : 반환받을 Pydantic 모델 타입
    system_prompt : 역할·규칙을 정의하는 시스템 지시문
    user_content : 분석 대상 원문(공고/이력서 텍스트 등)
    node : 경고 메시지에 남길 노드 이름
    """

    warnings: list[dict] = []
    content = (user_content or "").strip()
    if not content:
        warnings.append({"code": "empty_input", "message": f"{node}: 분석할 텍스트가 없습니다."})
        return None, warnings

    if len(content) > _MAX_INPUT_CHARS:
        content = content[:_MAX_INPUT_CHARS]
        warnings.append(
            {"code": "input_truncated", "message": f"{node}: 입력이 길어 {_MAX_INPUT_CHARS}자로 잘랐습니다."}
        )

    try:
        llm = get_llm()
    except LLMNotConfiguredError as exc:
        warnings.append({"code": "llm_not_configured", "message": f"{node}: {exc}"})
        return None, warnings

    structured_llm = llm.with_structured_output(schema)
    messages = [("system", system_prompt), ("human", content)]

    # 일시적 오류(네트워크·레이트리밋·파싱)를 흡수하기 위해 여러 번 재시도한다.
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return structured_llm.invoke(messages), warnings
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도/폴백 대상
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC * attempt)

    warnings.append({
        "code": "llm_call_failed",
        "message": f"{node}: LLM 호출 {_MAX_ATTEMPTS}회 재시도 후 실패 — {last_exc}",
    })
    return None, warnings
