"""GMS 연결 설정 + 모델 티어 매핑 — AGENTS §0·§5.5.

모델 문자열·GMS 키/엔드포인트는 **이 파일(과 gateway)에만** 존재한다(AGENTS §6).
정적 티어 매핑이라 모델을 바꾸려면 `MODEL_TIER` 한 곳만 고친다.
"""
from __future__ import annotations

import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv()  # Agent_Test/.env → 환경변수 (GMS_KEY 등)

Tier = Literal["cheap", "mid", "strong"]

# 정적 티어 매핑 (AGENTS §5.5). 모델 변경은 여기 한 곳만.
MODEL_TIER: dict[str, str] = {
    "cheap": "gpt-4o-mini",   # 라우팅·공고정리·최종응답
    "mid": "gpt-4.1-mini",    # docx→profile 추출·요건 추출
    "strong": "gpt-4.1",      # 항목 매칭·대체직군 Thought
}

# GMS OpenAI-compat 엔드포인트 (AGENTS §0). .env로 덮어쓸 수 있음.
GMS_BASE_URL: str = os.environ.get(
    "OPENAI_API_BASE", "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
)


def get_gms_key() -> str:
    """GMS_KEY를 환경에서 읽는다. 없으면 조용한 실패 대신 명확한 에러."""
    key = os.environ.get("GMS_KEY")
    if not key:
        raise RuntimeError(
            "GMS_KEY가 설정되지 않았습니다. "
            "Agent_Test/.env 에 `GMS_KEY=<발급키>` 를 넣으세요 (.env.example 참고)."
        )
    return key
