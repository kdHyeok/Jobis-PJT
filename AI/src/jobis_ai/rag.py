"""RAG 어댑터 계층 (부품 교체식 모듈화의 'RAG' 계층 — 오케스트레이터가 꽂는 자리).

이 프로젝트는 오케스트레이션과 RAG 를 병렬로 개발한다(핸드오프 문서).
따라서 오케스트레이터/워커 노드는 **RAG 내부 구현을 몰라야** 하고,
아래 `RagAdapter` 인터페이스(Protocol)만 호출한다.

- 지금 기본값은 `NullRagAdapter`: 검색 결과가 비어 있고 warning 만 남긴다. 절대 예외를 던지지 않는다.
  → RAG 가 아직 없어도 그래프는 최소 분석 결과를 낸다(핸드오프 문서 "RAG 실패도 전체 실패로 만들지 말 것").
- 나중에 RAG 담당자는 `RagAdapter` 를 구현한 클래스를 만들고,
  `get_rag_adapter()` 가 그것을 반환하도록 provider 분기만 추가하면 된다(노드 코드는 불변).

호출 지점(hook point): Gap Analyzer(기업 맥락), Alternative Path Finder(유사 공고),
company/insight fetch 등. 노드는 "언제 RAG 가 필요한지"만 판단하고 검색은 어댑터에 위임한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol, runtime_checkable

from jobis_ai.config import get_settings


@dataclass
class RagResult:
    """RAG 조회 결과 공통 형태.

    items   : 검색된 컨텍스트 조각들(각 dict 는 최소 {text, ...}). LLM 프롬프트에 주입.
    sources : 출처 메타(각 dict 는 {title, url, ...}). GraphState.sources 로 누적되어 추적성 확보.
    warnings: 실패/저신뢰/빈 결과 등. GraphState.warnings 로 누적.
    """

    items: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


@runtime_checkable
class RagAdapter(Protocol):
    """RAG 스택이 구현해야 할 최소 계약. 실패해도 예외 대신 RagResult 로 반환한다."""

    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        """기업 정보/인재상/기술문화 등 공고 판정에 도움이 되는 맥락을 조회한다."""
        ...

    def search(self, query: str, *, top_k: int = 5) -> RagResult:
        """범용 검색 훅(유사 공고, 후기, 통계 등). 아직 호출부가 적어도 계약은 열어 둔다."""
        ...


class NullRagAdapter:
    """RAG 미연결 기본 구현. 항상 빈 결과 + 안내 warning 을 돌려준다."""

    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        return RagResult(
            warnings=[
                {
                    "code": "rag_not_connected",
                    "message": (
                        f"RAG 미연결: '{company_name or '기업'}' 맥락 없이 프로필 근거만으로 판정합니다."
                    ),
                }
            ]
        )

    def search(self, query: str, *, top_k: int = 5) -> RagResult:
        return RagResult(
            warnings=[{"code": "rag_not_connected", "message": "RAG 미연결: 검색을 건너뜁니다."}]
        )


@lru_cache(maxsize=1)
def get_rag_adapter() -> RagAdapter:
    """설정(RAG_PROVIDER)에 맞는 어댑터를 반환한다. 기본은 Null(미연결).

    RAG 담당자는 여기 provider 분기 한 줄과 자신의 어댑터 클래스만 추가하면 된다.
    """

    provider = get_settings().rag_provider
    if provider in ("", "null", "none"):
        return NullRagAdapter()

    # 예: if provider == "chroma": from jobis_ai.rag_impl.chroma import ChromaRagAdapter; return ChromaRagAdapter()
    # 미지원 provider 는 조용히 Null 로 폴백(그래프를 죽이지 않는다).
    return NullRagAdapter()
