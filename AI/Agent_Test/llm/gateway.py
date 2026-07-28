"""LLM 호출 단일 창구 — AGENTS §5.5·§6.

모든 모듈은 모델을 직접 만들지 말고 여기서 얻는다.
- `get_llm(tier)`            : 자유 텍스트용 ChatModel (라우팅·응답 생성)
- `get_structured_llm(...)`  : 스키마 강제(Pydantic) — 파서·갭분석용
non-stream(`.invoke`) 전제 (프로토타입).
"""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from llm.config import GMS_BASE_URL, MODEL_TIER, Tier, get_gms_key


def get_llm(tier: Tier) -> BaseChatModel:
    """티어에 해당하는 모델 손잡이를 반환. GMS 경유(base_url·api_key 명시)."""
    return init_chat_model(
        MODEL_TIER[tier],
        model_provider="openai",
        base_url=GMS_BASE_URL,
        api_key=get_gms_key(),
    )


def get_structured_llm(tier: Tier, schema: type[BaseModel]) -> Runnable:
    """스키마를 강제하는 모델을 반환. 출력이 `schema` 인스턴스로 파싱된다."""
    return get_llm(tier).with_structured_output(schema)
