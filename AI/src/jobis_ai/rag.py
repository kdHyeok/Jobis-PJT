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


class LocalPostingsRagAdapter:
    """크롤링 공고 DB(postings_db) 기반 키워드 검색 — RAG 실구현 전까지의 실데이터 자리.

    Agent_Test 프로토타입의 search_postings Mock 을 이 어댑터 계약으로 이식한 것.
    RAG 팀 실구현(의미 검색)이 오면 get_rag_adapter 의 provider 분기로 교체되고,
    이 어댑터는 데이터만으로 도는 폴백으로 남는다. 반환 계약(RagResult)은 동일하다.
    """

    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        # 기업 맥락(인재상·기술문화)은 공고 DB 로 대답할 수 없다 — 정직하게 Null 동작.
        return NullRagAdapter().fetch_company_context(company_name, requirements)

    def search(self, query: str, *, top_k: int = 5) -> RagResult:
        from jobis_ai.postings_db import search_postings

        hits = search_postings((query or "").split(), top_k=top_k)
        if not hits:
            return RagResult(warnings=[{
                "code": "rag_no_results",
                "message": f"공고 DB 검색 0건: '{query[:60]}'",
            }])
        # 노드 소비 계약(_alternatives_from_rag / _recommend_from_candidates):
        # items = [{text, title, companyName, jobPostingId, score, ...}]
        items = [{
            "text": str(p.get("detail_text") or ""),
            "title": str(p.get("title") or ""),
            "companyName": str(p.get("company") or ""),
            "jobPostingId": p.get("posting_id"),
            "url": str(p.get("url") or ""),
            # 공고의 연차 표기 원문('신입'·'경력 3-8년' 등). 소비자(job_recommend)가
            # experience_floor_years 로 해석해 사용자 연차와 안 맞는 공고를 걸러낸다.
            # 실 RAG provider 가 이 값을 안 주면 빈 문자열 → 해석 불가 → 거르지 않는다.
            "seniority": str(p.get("experience") or ""),
            "score": float(p.get("score") or 0.0),
            "matchReason": p.get("match_reason") or {},
        } for p in hits]
        sources = [{"title": i["title"], "url": i["url"], "company": i["companyName"]}
                   for i in items]
        return RagResult(items=items, sources=sources)


@lru_cache(maxsize=1)
def get_rag_adapter() -> RagAdapter:
    """설정(RAG_PROVIDER)에 맞는 어댑터를 반환한다.

    - 미지정("", null, none): 공고 DB 파일이 있으면 LocalPostings(실데이터 키워드 검색),
      없으면 Null(미연결). → 데이터팀 JSON 을 sample_data 에 넣기만 하면 바로 동작한다.
    - RAG 담당자는 여기 provider 분기 한 줄과 자신의 어댑터 클래스만 추가하면 된다.
      예: if provider == "chroma": from ...chroma import ChromaRagAdapter; return ChromaRagAdapter()
    """

    provider = get_settings().rag_provider
    if provider == "local_postings":
        return LocalPostingsRagAdapter()
    if provider in ("", "null", "none"):
        from jobis_ai.postings_db import db_available

        return LocalPostingsRagAdapter() if db_available() else NullRagAdapter()

    # 미지원 provider 는 조용히 Null 로 폴백(그래프를 죽이지 않는다).
    return NullRagAdapter()
