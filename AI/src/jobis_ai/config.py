"""환경 설정 로더 (부품 교체식 모듈화의 '설정' 계층).

개인 키·모델명 등 사람마다 다른 값은 전부 여기(환경변수/.env)로 외부화한다.
코드에는 안전한 기본값만 두고, 비밀값 기본값은 두지 않는다.
다른 사람은 clone 후 자신의 `.env`만 채우면 그대로 동작한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv 미설치 환경에서도 순수 환경변수로 동작
    load_dotenv = None

# 레포 루트의 .env 를 로드 (실행 위치와 무관하게 항상 같은 파일).
# config.py -> jobis_ai -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_env_once() -> None:
    if load_dotenv is not None:
        load_dotenv(_REPO_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    """실행에 필요한 설정 묶음. 값의 출처는 오직 환경변수/.env."""

    llm_provider: str          # "openai"(GMS 경유) | "anthropic"(API 키) | "claude_code"(로컬 Claude 구독)
    anthropic_api_key: str
    anthropic_model: str
    claude_cli: str            # Claude Code CLI 명령 (기본 "claude", 예: "wsl claude")
    claude_code_model: str        # claude_code 고급 티어 모델 별칭 (sonnet 등)
    claude_code_model_light: str  # claude_code 경량 티어 모델 별칭 (haiku 등)
    llm_base_url: str          # GMS 경유 챗 엔드포인트 base URL (llm_provider="openai" 일 때)
    llm_model: str             # GMS 로 호출할 모델명 — 고급 티어(추출·생성)
    llm_model_light: str       # 경량 티어 모델명 — 분류·이진판정·요약
    temperature: float | None  # None 이면 모델 기본값 사용(일부 모델은 temperature 미지원)
    max_output_tokens: int | None  # 응답 토큰 상한. None 이면 모델 기본값
    model_version: str         # 응답 meta.modelVersion 에 기록
    rag_provider: str          # "null"(미연결, 기본) | RAG 담당자가 붙일 provider 명
    embed_provider: str        # "null"(미연결, 기본) | "openai" (GMS 경유 OpenAI 임베딩)
    gms_key: str               # SSAFY GMS(API 게이트웨이) 발급 키. LLM/임베딩 호출 공용
    embed_base_url: str        # GMS 경유 임베딩 엔드포인트 base URL
    embed_model: str           # 임베딩 모델명 (예: text-embedding-3-small)

    @property
    def has_llm_key(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.gms_key)
        if self.llm_provider == "claude_code":
            # 키가 아니라 이 머신의 Claude Code CLI 로그인 세션을 쓴다 — 여기서 검사할 키가 없다.
            # 로그인이 없으면 첫 호출이 실패하고 run_structured 가 경고로 남긴다.
            return True
        return bool(self.anthropic_api_key)

    @property
    def has_embed_key(self) -> bool:
        return bool(self.gms_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스당 한 번만 로드해 재사용."""

    _load_env_once()
    temp_raw = os.getenv("LLM_TEMPERATURE")      # 미설정이면 0.3 (판정 흔들림을 줄인다)
    tokens_raw = os.getenv("LLM_MAX_TOKENS")     # 미설정이면 4096 (토큰 비용 상한)
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        claude_cli=os.getenv("CLAUDE_CLI", "claude"),
        claude_code_model=os.getenv("CLAUDE_CODE_MODEL", "sonnet"),
        claude_code_model_light=os.getenv("CLAUDE_CODE_MODEL_LIGHT", "haiku"),
        llm_base_url=os.getenv(
            "LLM_BASE_URL", "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
        ),
        llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        llm_model_light=os.getenv("LLM_MODEL_LIGHT", "gpt-4.1-mini"),
        temperature=float(temp_raw) if temp_raw not in (None, "") else 0.3,
        max_output_tokens=int(tokens_raw) if tokens_raw not in (None, "") else 4096,
        model_version=os.getenv("MODEL_VERSION", "jarvis-0.1.0"),
        rag_provider=os.getenv("RAG_PROVIDER", "null"),
        embed_provider=os.getenv("EMBED_PROVIDER", "null"),
        gms_key=os.getenv("GMS_KEY", ""),
        embed_base_url=os.getenv(
            "EMBED_BASE_URL", "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
        ),
        embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
    )
