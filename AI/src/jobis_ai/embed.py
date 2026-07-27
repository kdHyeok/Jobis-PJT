"""임베딩 어댑터 계층 (부품 교체식 모듈화의 '임베딩' 계층).

`gap_matcher` 의 2차 유사도 매칭(§3.5)과 프로필의 유사 스킬 병합(§3.2)이 쓴다.
`rag.py` 와 같은 원칙: **호출부는 내부 구현을 모른다.** 아래 `Embedder` 계약만 호출한다.

- 기본값은 `NullEmbedder`: 벡터를 내지 않고 `similarity()` 가 **None** 을 돌려준다.
  None 은 "0.0(안 닮았다)"이 아니라 **"모른다"**다. 이 구분이 중요하다 —
  0.0 을 돌려주면 gap_matcher 가 "유사도 0 = 미충족"으로 **잘못 판정**한다.
  None 이면 gap_matcher 는 2차 매칭을 건너뛰고 1차 룰 결과만 쓴다(§3.5 폴백).
- 임베딩 담당자는 `Embedder` 를 구현한 클래스를 만들고 `get_embedder()` 에 provider
  분기 한 줄만 추가하면 된다. **노드/매처 코드는 불변.**

절대 규칙(rag.py 와 동일): **예외를 던지지 말 것.** 실패해도 warnings 를 담아 정상 반환한다.
임베딩 실패가 전체 분석 실패가 되면 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol, runtime_checkable

from jobis_ai.config import get_settings


@dataclass
class EmbedResult:
    """임베딩 조회 결과.

    vectors : 입력 순서와 1:1 대응하는 벡터들. 실패 시 빈 리스트.
    warnings: 실패/미연결 등. GraphState.warnings 로 누적.
    """

    vectors: list[list[float]] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.vectors)


@runtime_checkable
class Embedder(Protocol):
    """임베딩 스택이 구현해야 할 최소 계약."""

    def embed(self, texts: list[str]) -> EmbedResult:
        """텍스트 목록 → 벡터 목록. 실패해도 예외 대신 EmbedResult(warnings=[...])."""
        ...

    def similarity(self, left: str, right: str) -> float | None:
        """두 텍스트의 의미 유사도 0~1. **모르면 None**(0.0 아님)."""
        ...

    def similarity_matrix(
        self, lefts: list[str], rights: list[str]
    ) -> list[list[float]] | None:
        """lefts × rights 유사도 행렬. 모르면 None.

        gap_matcher 는 requirement × skill 을 전부 비교하므로, 한 쌍씩 호출하면
        API 왕복이 N×M 번 난다. 배치로 한 번에 받기 위한 메서드.
        """
        ...


class NullEmbedder:
    """임베딩 미연결 기본 구현. 벡터 없음 + '모른다'(None) 를 돌려준다.

    이 상태에서 gap_matcher 는 1차 룰(정확/동의어) 매칭만으로 동작한다 — 재현율은
    낮아지지만 **틀린 판정을 내지는 않는다.** 조용히 0.0 을 주는 것보다 안전하다.
    """

    def embed(self, texts: list[str]) -> EmbedResult:
        return EmbedResult(warnings=[{
            "code": "embed_not_connected",
            "message": "임베딩 미연결: 벡터를 생성하지 않습니다.",
        }])

    def similarity(self, left: str, right: str) -> float | None:
        return None

    def similarity_matrix(
        self, lefts: list[str], rights: list[str]
    ) -> list[list[float]] | None:
        return None


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """설정(EMBED_PROVIDER)에 맞는 임베더를 반환한다. 기본은 Null(미연결).

    담당자는 여기 provider 분기 한 줄과 자신의 구현 클래스만 추가하면 된다. 예:
        if provider == "voyage":
            from jobis_ai.embed_impl.voyage import VoyageEmbedder
            return VoyageEmbedder()
    미지원 provider 는 조용히 Null 로 폴백한다(그래프를 죽이지 않는다).
    """

    provider = get_settings().embed_provider
    if provider in ("", "null", "none"):
        return NullEmbedder()

    if provider == "openai":
        # SSAFY GMS(API 게이트웨이) 경유 OpenAI 임베딩. 엔드포인트/키는 환경변수
        # (EMBED_BASE_URL/GMS_KEY)에서만 읽는다 — 하드코딩 금지.
        from jobis_ai.embed_impl.gms_openai import GmsOpenAIEmbedder
        return GmsOpenAIEmbedder()

    return NullEmbedder()
