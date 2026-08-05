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


@lru_cache(maxsize=4)
def get_llm(tier: str = "default") -> Any:
    """설정에 맞는 LangChain Chat 모델을 생성해 반환한다.

    반환 객체는 `.invoke(messages)` 를 지원하는 표준 LangChain 인터페이스라,
    provider 가 바뀌어도 노드 코드는 수정할 필요가 없다.

    tier — 호출 목적에 따른 모델 등급 (0724 토큰 비용 최적화):
    - "default": 고급 모델(LLM_MODEL). 긴 비정형 추출·사용자 대면 생성.
    - "light":   경량 모델(LLM_MODEL_LIGHT). 라벨 분류·이진 판정·짧은 요약 —
                 출력 스키마가 좁아 모델 성능 차이가 결과에 거의 안 실리는 곳.
    - "router":  라우팅 판정(플래너 등 "무엇을 실행할지"를 정하는 호출) — 오판이 턴
                 전체를 엉뚱한 일에 쓰게 하는 자리라 가장 강한 모델을 배정한다(D74).
                 전용 모델 미지정 프로바이더는 default 로 폴백.
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
            model=settings.active_model(tier),
            api_key=settings.gms_key,
            base_url=settings.llm_base_url,
            timeout=60,
            # 재시도는 structured.py 한 계층에서만 한다. 클라이언트까지 재시도하면
            # 3회 × 클라이언트 2회 = 최악 9회 네트워크 시도로 실패 시 지연이 폭주한다.
            max_retries=0,
            # 스트리밍 응답의 마지막 청크에 usage(토큰 합계)를 싣는다 — llm_usage 집계용.
            # 없으면 표현 계층(career_chat 등) 스트리밍 콜의 토큰이 영원히 미계측으로 남는다.
            stream_usage=True,
        )
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        if settings.max_output_tokens:
            kwargs["max_tokens"] = settings.max_output_tokens
        return ChatOpenAI(**kwargs)

    if settings.llm_provider == "claude_code":
        # 이 머신에 로그인된 Claude Code CLI(구독 시트)로 호출한다 — API 키·토큰 비용 없음.
        # 개발 반복용. 서버 배포에는 openai(GMS)나 anthropic(API 키)을 쓴다.
        from jobis_ai.claude_code_llm import ClaudeCodeChat

        return ClaudeCodeChat(model=settings.active_model(tier), cli=settings.claude_cli)

    if settings.llm_provider in {"codex", "gpt"}:
        # Codex OAuth/Responses 로직을 AI 패키지 안에 격리한다.
        # 노드의 system/human 메시지는 CodexChat이 instructions/input으로 그대로 보존한다.
        from jobis_ai.codex_llm import CodexChat

        return CodexChat(
            model=settings.active_model(tier),
            reasoning_effort=settings.codex_reasoning_effort,
            timeout_sec=settings.codex_timeout_sec,
        )

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # anthropic 경로는 아직 티어 미분리 — 필요 시 ANTHROPIC_MODEL_LIGHT 를 추가한다.
        kwargs = dict(
            model=settings.active_model(tier),
            api_key=settings.anthropic_api_key,
            timeout=60,
            # 재시도는 structured.py 한 계층에서만 한다. 클라이언트까지 재시도하면
            # 3회 × 클라이언트 2회 = 최악 9회 네트워크 시도로 실패 시 지연이 폭주한다.
            max_retries=0,
        )
        # 일부 최신 모델(opus-4-8 등)은 temperature 파라미터를 받지 않는다.
        # 명시적으로 설정된 경우에만 전달한다.
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        if settings.max_output_tokens:
            kwargs["max_tokens"] = settings.max_output_tokens
        return ChatAnthropic(**kwargs)

    raise LLMNotConfiguredError(f"지원하지 않는 LLM_PROVIDER: {settings.llm_provider}")
