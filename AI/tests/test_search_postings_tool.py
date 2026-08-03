"""공고 검색 도구 — 자기 루프가 바깥 세계에 닿는 유일한 통로 (`_common.search_postings_tool`).

루프 하네스는 전부터 있었지만 등록된 도구가 세션 내부 데이터뿐이라 루프가 돌 자리가 없었다
(`posting_analysis` 는 read_posting·save_plan 둘). 이 도구가 그 자리를 연다.

여기서 검사하는 것은 검색 품질이 아니라 **ToolSpec 계약**이다: 관찰은 사실만, 실패는 예외
대신 관찰 문자열(루프를 죽이지 않는다), RAG 경고를 삼키지 않는다(§2-6 폴백 이유 보존).
"""

from __future__ import annotations

from jobis_ai.agents._common import search_postings_tool
from jobis_ai.agents.agent_loop import TOOL_WARNINGS_KEY
from jobis_ai.rag import RagResult


class _StubAdapter:
    def __init__(self, result: RagResult | None = None, boom: Exception | None = None):
        self._result = result or RagResult()
        self._boom = boom
        self.queries: list[str] = []

    def fetch_company_context(self, company_name, requirements):   # pragma: no cover
        return RagResult()

    def search(self, query: str, *, top_k: int = 5) -> RagResult:
        self.queries.append(query)
        if self._boom:
            raise self._boom
        return self._result


def _patch(monkeypatch, adapter: _StubAdapter) -> None:
    # 임포트한 모듈 쪽 이름을 바꾼다(test_improvements 와 같은 관례) — `jobis_ai.rag` 의
    # 원본을 갈아치우면 conftest 의 lru_cache 정리(cache_clear)가 깨진다.
    monkeypatch.setattr("jobis_ai.agents._common.get_rag_adapter", lambda: adapter)


def test_empty_query_does_not_call_rag(monkeypatch):
    """검색어가 없으면 부르지 않는다 — 빈 질의로 무의미한 결과를 관찰에 들이지 않는다."""

    adapter = _StubAdapter()
    _patch(monkeypatch, adapter)
    observation, data = search_postings_tool().run({}, "   ")
    assert adapter.queries == []
    assert "검색어가 비어" in observation
    assert data == {}


def test_hit_reports_company_and_title(monkeypatch):
    adapter = _StubAdapter(RagResult(items=[
        {"companyName": "가나테크", "title": "백엔드 엔지니어", "seniority": "3년 이상",
         "url": "https://example.test/1", "text": "Kafka 기반 이벤트 처리 경험"},
    ]))
    _patch(monkeypatch, adapter)
    observation, _ = search_postings_tool().run({}, "백엔드 Kafka")
    assert adapter.queries == ["백엔드 Kafka"]
    assert "가나테크" in observation
    assert "백엔드 엔지니어" in observation
    assert "Kafka 기반 이벤트 처리" in observation


def test_empty_result_says_so_instead_of_staying_silent(monkeypatch):
    """빈 관찰을 주면 LLM 이 그 자리를 사전지식으로 채운다(§2-5) — 없다고 말해야 한다."""

    _patch(monkeypatch, _StubAdapter(RagResult()))
    observation, _ = search_postings_tool().run({}, "존재하지 않는 직무")
    assert "찾은 공고가 없습니다" in observation


def test_rag_warnings_are_raised_not_swallowed(monkeypatch):
    """키워드 폴백으로 찾은 결과인지를 호출부가 알아야 사용자에게 명시할 수 있다(D90)."""

    warning = {"code": "rag_http_failed", "message": "RAG 서버 연결 실패 — 키워드 폴백"}
    _patch(monkeypatch, _StubAdapter(RagResult(
        items=[{"companyName": "다라소프트", "title": "서버 개발", "text": "Spring"}],
        warnings=[warning],
    )))
    _, data = search_postings_tool().run({}, "서버")
    assert data[TOOL_WARNINGS_KEY] == [warning]


def test_adapter_exception_becomes_an_observation(monkeypatch):
    """도구 실패가 턴을 죽이지 않는다 — 예외 대신 관찰로 알린다(ToolSpec 계약)."""

    _patch(monkeypatch, _StubAdapter(boom=RuntimeError("연결 끊김")))
    observation, data = search_postings_tool().run({}, "백엔드")
    assert "공고 검색 실패" in observation
    assert "연결 끊김" in observation
    assert data == {}


def test_observation_is_capped(monkeypatch):
    """관찰이 루프 payload 를 삼키지 않게 자른다(grep_source_lines 와 같은 이유)."""

    _patch(monkeypatch, _StubAdapter(RagResult(items=[
        {"companyName": f"회사{i}", "title": "백엔드", "text": "가" * 5_000}
        for i in range(20)
    ])))
    observation, _ = search_postings_tool().run({}, "백엔드")
    assert len(observation) <= 1_600
