"""LLM 클라이언트 팩토리 (부품 교체식 모듈화의 'LLM' 계층).

노드 코드는 내부를 몰라도 `get_llm()` 하나만 호출한다.
provider 를 바꾸거나 모델을 교체해도 호출부는 그대로 — 이 파일만 갈아끼운다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jobis_ai.config import get_settings


class LLMNotConfiguredError(RuntimeError):
    """API 키가 없어 실제 호출이 불가능할 때. 호출부가 잡아서 안내/폴백한다."""


@lru_cache(maxsize=1)
def get_llm() -> Any:
    """설정에 맞는 LangChain Chat 모델을 생성해 반환한다.

    반환 객체는 `.invoke(messages)` 를 지원하는 표준 LangChain 인터페이스라,
    provider 가 바뀌어도 노드 코드는 수정할 필요가 없다.
    """

    settings = get_settings()
    if not settings.has_llm_key:
        if settings.llm_provider == "openai":
            raise LLMNotConfiguredError(
                "GMS_KEY 가 설정되지 않았습니다. .env 를 확인하세요."
            )
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요."
        )

    if settings.llm_provider == "openai":
        # SSAFY GMS(API 게이트웨이) 경유 OpenAI 호환 채팅 엔드포인트.
        # 엔드포인트/키는 반드시 환경변수(LLM_BASE_URL/GMS_KEY)에서만 읽는다 — 하드코딩 금지.
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = dict(
            model=settings.llm_model,
            api_key=settings.gms_key,
            base_url=settings.llm_base_url,
            timeout=60,
            max_retries=2,
        )
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        return ChatOpenAI(**kwargs)

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = dict(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            timeout=60,
            max_retries=2,
        )
        # 일부 최신 모델(opus-4-8 등)은 temperature 파라미터를 받지 않는다.
        # 명시적으로 설정된 경우에만 전달한다.
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        return ChatAnthropic(**kwargs)

    raise LLMNotConfiguredError(f"지원하지 않는 LLM_PROVIDER: {settings.llm_provider}")
