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


# 같은 공고가 채용 사이트마다 한 건씩 크롤돼 있다 — posting_id·URL·제목이 사이트별로 다르다.
# 실측(2026-08-03, 세션 c1470d00): 추천 5건이 실제로는 공고 3개였고(같은 posting_id 가 work24·
# saramin 로 2번), 대안 5건도 에버엑스·피트인이 각각 2번이었다("에버엑스㈜"/"에버엑스 주식회사",
# 제목 뒤 "(채용시 마감)" 만 다름). 사용자는 5개를 받았다고 믿는다.
# **후보를 만드는 자리는 여기 하나**이므로(job_recommend·_alternatives_from_rag·application_plan
# 이 전부 이 items 를 받는다) 중복 제거도 여기서 한 번만 한다.
_CORP_FORMS = ("주식회사", "(주)", "㈜", "(유)", "유한회사")
# 제목에 붙는 상태 표기만 지운다 — 괄호를 통째로 지우면 '백엔드(신입)'·'백엔드(경력)' 처럼
# 실제로 다른 공고가 하나로 합쳐진다.
_STATUS_MARKS = ("(채용시 마감)", "(상시채용)", "(수시채용)", "(채용마감)")


def _posting_identity(item: dict) -> tuple[str, str]:
    def norm(value: object, drops: tuple[str, ...]) -> str:
        text = str(value or "")
        for drop in drops:
            text = text.replace(drop, "")
        return "".join(text.split()).lower()

    return norm(item.get("companyName"), _CORP_FORMS), norm(item.get("title"), _STATUS_MARKS)


def dedupe_postings(items: list[dict]) -> list[dict]:
    """회사+직무가 같은 크롤 중복을 지운다. 먼저 온 것(=점수 높은 쪽)을 남긴다.

    결과 수가 top_k 보다 줄어들 수 있다 — 중복으로 자릿수를 채우는 것보다 낫다.
    """

    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for item in items:
        key = _posting_identity(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def company_context_unsupported(company_name: str) -> RagResult:
    """검색은 붙어 있으나 **기업 맥락**을 낼 소스가 없는 경우 — '미연결'과 구별한다.

    실측(2026-08-03, 세션 c1470d00): 실 RAG(HTTP)가 정상 동작해 공고를 찾고 있는데 분석
    경고에는 `rag_not_connected` "RAG 미연결"이 찍혔다. 공고 검색 어댑터들이 기업 맥락 조회를
    `NullRagAdapter` 로 위임해 **그쪽 사유 문구까지 함께 가져온** 탓이다. 붙어 있는데 미연결로
    적으면 다음 사람이 없는 장애를 좇는다 — 폴백이 사유를 삼키는 것(§2-6)의 거울상이다.

    사유는 여전히 남는다: 공고 검색 서비스는 인재상·기술문화를 대답할 소스가 아니다.
    """

    return RagResult(warnings=[{
        "code": "company_context_unsupported",
        "message": (f"'{company_name or '기업'}' 기업 맥락(인재상·기술문화)은 공고 검색으로 "
                    "답할 수 없어 조회하지 않았습니다 — 프로필 근거만으로 판정합니다."),
    }])


class LocalPostingsRagAdapter:
    """크롤링 공고 DB(postings_db) 기반 키워드 검색 — RAG 실구현 전까지의 실데이터 자리.

    Agent_Test 프로토타입의 search_postings Mock 을 이 어댑터 계약으로 이식한 것.
    RAG 팀 실구현(의미 검색)이 오면 get_rag_adapter 의 provider 분기로 교체되고,
    이 어댑터는 데이터만으로 도는 폴백으로 남는다. 반환 계약(RagResult)은 동일하다.
    """

    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        # 기업 맥락(인재상·기술문화)은 공고 DB 로 대답할 수 없다 — 빈 결과 + 사유.
        return company_context_unsupported(company_name)

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
        items = dedupe_postings(items)
        sources = [{"title": i["title"], "url": i["url"], "company": i["companyName"]}
                   for i in items]
        return RagResult(items=items, sources=sources)


class HttpRagAdapter:
    """실 RAG HTTP 서비스 어댑터(D89) — RAG 팀의 하이브리드 검색+리랭킹 서버를 부른다.

    계약: `RAG/RAG_입출력_명세서.md` — 입력 직업명(str) 또는 profile(JSON),
    출력 {"postings": [원본 공고 + score + match_reason]}. `evaluate=False` 로 CRAG
    평가자(LLM 채점)를 끈다 — 이 저장소의 LLM 은 Claude CLI 하나뿐이라는 규약 유지.

    실패는 삼키지 않는다(§2-6): 경고를 달고 LocalPostings(키워드 검색) 폴백으로 내려간다 —
    서버가 죽어도 그래프는 계속 돌고, 왜 키워드 결과인지가 warnings 에 남는다.
    """

    # 실측(2026-07-31 16:38): 대안 검색의 첫 무거운 쿼리(격차 포함 장문)가 30초를 넘겨
    # 클라이언트가 포기 → 키워드 폴백으로 강등됐는데, 서버는 결국 200을 냈다(로그 대조).
    # warm 2.2초는 짧은 쿼리 기준 — 리랭커의 첫 장문 쿼리를 감안해 여유를 둔다.
    _TIMEOUT_SEC = 90

    def __init__(self, base_url: str) -> None:
        self._base = (base_url or "").rstrip("/")

    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        # 기업 맥락(인재상·기술문화)은 공고 검색 서비스로 대답할 수 없다 — 빈 결과 + 사유.
        return company_context_unsupported(company_name)

    def search(self, query: str | dict, *, top_k: int = 5) -> RagResult:
        import json as json_mod
        import logging
        import time as time_mod
        import urllib.error
        import urllib.request

        body = json_mod.dumps({"input": query, "top_k": top_k, "evaluate": False},
                              ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base}/search", body, {"Content-Type": "application/json"})
        started = time_mod.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._TIMEOUT_SEC) as resp:
                data = json_mod.load(resp)
            elapsed = time_mod.perf_counter() - started
            if elapsed > 10:
                # 타임아웃 진단용 — 느린 검색이 얼마나 자주·얼마나 느린지 로그로 남긴다.
                logging.getLogger(__name__).warning(
                    "실 RAG 검색 지연 %.1f초 (query %d자)", elapsed, len(str(query)))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            fallback = LocalPostingsRagAdapter().search(
                query if isinstance(query, str) else "", top_k=top_k)
            fallback.warnings.insert(0, {
                "code": "rag_http_failed",
                "message": f"실 RAG 호출 실패({self._base}) — 키워드 검색으로 폴백: {exc}",
            })
            return fallback

        postings = data.get("postings") or []
        if not postings:
            return RagResult(warnings=[{
                "code": "rag_no_results",
                "message": f"실 RAG 검색 0건: '{str(query)[:60]}'",
            }])
        # 노드 소비 계약은 LocalPostings 와 동일 — 같은 크롤 스키마의 다른 검색 엔진이다.
        items = [{
            "text": str(p.get("detail_text") or ""),
            "title": str(p.get("title") or ""),
            "companyName": str(p.get("company") or ""),
            "jobPostingId": p.get("posting_id"),
            "url": str(p.get("url") or ""),
            "seniority": str(p.get("experience") or ""),
            "score": float(p.get("score") or 0.0),
            "matchReason": p.get("match_reason") or {},
        } for p in postings]
        items = dedupe_postings(items)
        sources = [{"title": i["title"], "url": i["url"], "company": i["companyName"]}
                   for i in items]
        return RagResult(items=items, sources=sources)


def warm_search_async(query: str) -> "object | None":
    """RAG 캐시 예열(D96) — **결과는 버린다.** 공고·이력서가 채워진 시점에 그 자산 기반
    쿼리를 한 번 쏘아, 실제 검색 시점(대안 공고·추천)의 첫 쿼리 지연(D95 실측: 콜드 30초+)
    을 미리 지불한다. DB 페이지 캐시는 "나중에 검색할 그 데이터 근처"를 만져야 데워지므로
    사용자 자산 기반 쿼리가 정확히 유효하다.

    HTTP provider 일 때만, 데몬 스레드로 비차단, 실패는 로그만 — 예열은 강화지 기능이
    아니라서 턴을 1초도 늦추면 안 된다. 반환값(Thread)은 테스트 동기화용.
    """

    import logging
    import threading

    adapter = get_rag_adapter()
    if not isinstance(adapter, HttpRagAdapter) or not (query or "").strip():
        return None

    def _run() -> None:
        try:
            adapter.search(query, top_k=3)
        except Exception as exc:   # noqa: BLE001 — 예열 실패는 기능 실패가 아니다
            logging.getLogger(__name__).info("RAG 예열 실패(무시): %s", exc)

    thread = threading.Thread(target=_run, daemon=True, name="rag-warm")
    thread.start()
    return thread


@lru_cache(maxsize=1)
def get_rag_adapter() -> RagAdapter:
    """설정(RAG_PROVIDER)에 맞는 어댑터를 반환한다.

    - 미지정("", null, none): 공고 DB 파일이 있으면 LocalPostings(실데이터 키워드 검색),
      없으면 Null(미연결). → 데이터팀 JSON 을 sample_data 에 넣기만 하면 바로 동작한다.
    - RAG 담당자는 여기 provider 분기 한 줄과 자신의 어댑터 클래스만 추가하면 된다.
      예: if provider == "chroma": from ...chroma import ChromaRagAdapter; return ChromaRagAdapter()
    """

    provider = get_settings().rag_provider
    if provider == "http":
        return HttpRagAdapter(get_settings().rag_search_url)
    if provider == "local_postings":
        return LocalPostingsRagAdapter()
    if provider in ("", "null", "none"):
        from jobis_ai.postings_db import db_available

        return LocalPostingsRagAdapter() if db_available() else NullRagAdapter()

    # 미지원 provider 는 조용히 Null 로 폴백(그래프를 죽이지 않는다).
    return NullRagAdapter()
