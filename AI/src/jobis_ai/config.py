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

    llm_provider: str          # openai | anthropic | claude_code | codex(OAuth) | codex_cli(호환)
    anthropic_api_key: str
    anthropic_model: str          # anthropic 고급 티어 모델 (API 직접 호출)
    anthropic_model_light: str    # anthropic 경량 티어 모델 (빈 값이면 고급 티어)
    anthropic_model_router: str   # anthropic 라우터 티어 모델 (빈 값이면 고급 티어, D74)
    claude_cli: str            # Claude Code CLI 명령 (기본 "claude", 예: "wsl claude")
    claude_code_model: str        # claude_code 고급 티어 모델 별칭 (sonnet 등)
    claude_code_model_light: str  # claude_code 경량 티어 모델 별칭 (haiku 등)
    # 라우팅 판정 티어(플래너 등 "무엇을 실행할지"를 정하는 호출) 전용 모델 (D74).
    # 비어 있으면 고급 티어로 폴백 — 라우팅 오판은 턴 전체를 엉뚱한 일에 쓰게 하므로
    # 가장 강한 모델을 쓸 가치가 있는 유일한 자리다.
    claude_code_model_router: str
    codex_cli: str                # 기존 로컬 Codex CLI 실행 경로(전환 기간 호환)
    codex_model: str              # codex 고급 티어 모델
    codex_model_light: str        # codex 경량 티어 모델
    codex_model_router: str       # codex 라우터 티어 모델(빈 값이면 고급 티어)
    codex_reasoning_effort: str   # minimal~ultra
    codex_timeout_sec: float      # Codex Responses 요청 제한시간
    codex_effort: str             # 기존 codex_cli reasoning effort(전환 기간 호환)
    llm_base_url: str          # GMS 경유 챗 엔드포인트 base URL (llm_provider="openai" 일 때)
    llm_model: str             # GMS 로 호출할 모델명 — 고급 티어(추출·생성)
    llm_model_light: str       # 경량 티어 모델명 — 분류·이진판정·요약
    temperature: float | None  # None 이면 모델 기본값 사용(일부 모델은 temperature 미지원)
    max_output_tokens: int | None  # 응답 토큰 상한. None 이면 모델 기본값
    model_version: str         # 응답 meta.modelVersion 에 기록
    rag_provider: str          # "null"(미연결, 기본) | "http"(실 RAG 서비스, D89) | "local_postings"
    rag_search_url: str        # 실 RAG HTTP 서비스 주소 (rag_provider="http" 일 때)
    embed_provider: str        # "null"(미연결, 기본) | "openai" (GMS 경유 OpenAI 임베딩)
    gms_key: str               # SSAFY GMS(API 게이트웨이) 발급 키. LLM/임베딩 호출 공용
    embed_base_url: str        # GMS 경유 임베딩 엔드포인트 base URL
    embed_model: str           # 임베딩 모델명 (예: text-embedding-3-small)
    jina_api_key: str          # jina.ai reader 키 (선택 — 없으면 무키 저율 호출)
    clova_api_key: str         # Clova Studio 키 (이미지 공고 VLM, feat_url/)
    clova_vlm_url: str         # Clova VLM 챗 엔드포인트 전체 URL

    def active_model(self, tier: str = "default") -> str:
        """**지금 프로바이더가 실제로 부르는 모델명.** provenance 와 런타임의 단일 출처다.

        이게 없던 동안 하네스가 `llm_model`(=GMS 모델명)을 프로바이더와 무관하게 기록해,
        Claude CLI 로 돌린 baseline 에 `"model": "gpt-4.1-mini"` 가 박혔다
        (`planner_harness.py` 오귀속 — 평가 리포트 §4-3). 어느 모델로 잰 수치인지 파일이
        말하지 못하면 그 baseline 은 비교 근거가 못 된다.

        `get_llm` 이 모델을 고르는 분기와 **같은 사전을 쓰게** 여기 한 곳에 둔다 —
        지표와 런타임이 갈라지지 못하게 하는 것이 이 코드베이스의 방식이다(D52·§4-3).
        """

        if self.llm_provider == "openai":
            # openai(GMS) 경로는 router 전용 모델 미분리 — 고급 티어로 폴백.
            return self.llm_model_light if tier == "light" else self.llm_model
        if self.llm_provider == "claude_code":
            if tier == "router" and self.claude_code_model_router:
                return self.claude_code_model_router
            return self.claude_code_model_light if tier == "light" else self.claude_code_model
        if self.llm_provider in {"codex", "gpt", "codex_cli"}:
            if tier == "router" and self.codex_model_router:
                return self.codex_model_router
            return self.codex_model_light if tier == "light" else self.codex_model
        # anthropic — claude_code 와 같은 3티어 구성 (API 직접 호출)
        if tier == "router" and self.anthropic_model_router:
            return self.anthropic_model_router
        if tier == "light" and self.anthropic_model_light:
            return self.anthropic_model_light
        return self.anthropic_model

    @property
    def has_llm_key(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.gms_key)
        if self.llm_provider == "claude_code":
            # 키가 아니라 이 머신의 Claude Code CLI 로그인 세션을 쓴다 — 여기서 검사할 키가 없다.
            # 로그인이 없으면 첫 호출이 실패하고 run_structured 가 경고로 남긴다.
            return True
        if self.llm_provider in {"codex", "gpt", "codex_cli"}:
            # 명시한 OAuth 상태를 쓴다. 토큰 유효성은 provider가 갱신/검증한다.
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
        llm_provider=os.getenv("LLM_PROVIDER", "codex_cli"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        anthropic_model_light=os.getenv("ANTHROPIC_MODEL_LIGHT", ""),
        anthropic_model_router=os.getenv("ANTHROPIC_MODEL_ROUTER", ""),
        claude_cli=os.getenv("CLAUDE_CLI", "claude"),
        claude_code_model=os.getenv("CLAUDE_CODE_MODEL", "sonnet"),
        claude_code_model_light=os.getenv("CLAUDE_CODE_MODEL_LIGHT", "haiku"),
        claude_code_model_router=os.getenv("CLAUDE_CODE_MODEL_ROUTER", ""),
        codex_cli=os.getenv("CODEX_CLI", "codex"),
        codex_model=os.getenv("CODEX_MODEL", "gpt-5.4"),
        codex_model_light=os.getenv(
            "CODEX_MODEL_LIGHT", os.getenv("CODEX_MODEL", "gpt-5.4")
        ),
        codex_model_router=os.getenv("CODEX_MODEL_ROUTER", ""),
        codex_reasoning_effort=os.getenv("CODEX_REASONING_EFFORT", "medium"),
        codex_timeout_sec=float(os.getenv("CODEX_TIMEOUT_SEC", "200")),
        codex_effort=os.getenv("CODEX_EFFORT", "low"),
        llm_base_url=os.getenv(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        ),
        llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        llm_model_light=os.getenv("LLM_MODEL_LIGHT", "gpt-4.1-mini"),
        temperature=float(temp_raw) if temp_raw not in (None, "") else 0.3,
        max_output_tokens=int(tokens_raw) if tokens_raw not in (None, "") else 4096,
        model_version=os.getenv("MODEL_VERSION", "jarvis-0.1.0"),
        rag_provider=os.getenv("RAG_PROVIDER", "null"),
        rag_search_url=os.getenv("RAG_SEARCH_URL", "http://127.0.0.1:8765"),
        embed_provider=os.getenv("EMBED_PROVIDER", "null"),
        gms_key=os.getenv("GMS_KEY", ""),
        embed_base_url=os.getenv(
            "EMBED_BASE_URL", "https://api.openai.com/v1"
        ),
        embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
        jina_api_key=os.getenv("JINA_API_KEY", ""),
        clova_api_key=os.getenv("CLOVA_API_KEY", ""),
        clova_vlm_url=os.getenv(
            "CLOVA_VLM_URL",
            "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005",
        ),
    )
