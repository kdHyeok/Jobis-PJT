"""파서 정규화/검증 헬퍼와 RAG 어댑터 seam 유닛 테스트."""

from jobis_ai.contracts.domain import NormalizedJobPosting, NormalizedUserProfile, Requirement
from jobis_ai.graph.nodes import (
    _build_alternative_query,
    _filter_grounded_evidence,
    _normalize_job_schema,
    _normalize_profile_schema,
    _validate_job_posting,
    find_alternatives,
    parse_job_posting,
)
from jobis_ai.rag import NullRagAdapter, get_rag_adapter
from jobis_ai.roadmap_scheduler import PlannedItem, schedule


# --- 파서 정규화 ---------------------------------------------------------
def test_normalize_reindexes_requirement_ids():
    posting = NormalizedJobPosting(
        jobTitle="백엔드",
        requiredRequirements=[
            Requirement(requirementId="x", text="A"),
            Requirement(requirementId="y", text="B"),
        ],
        preferredRequirements=[Requirement(requirementId="z", text="C")],
    )
    _normalize_job_schema(posting)

    assert [r.requirementId for r in posting.requiredRequirements] == ["req-1", "req-2"]
    assert [r.requirementId for r in posting.preferredRequirements] == ["pref-1"]
    assert posting.preferredRequirements[0].type == "preferred"


def test_normalize_dedups_tech_stack_case_insensitive():
    posting = NormalizedJobPosting(techStack=["Java", "java", "Spring", " Spring "])
    _normalize_job_schema(posting)
    assert posting.techStack == ["Java", "Spring"]


def test_validate_flags_missing_fields():
    posting = NormalizedJobPosting()  # 전부 비어 있음
    codes = {w["code"] for w in _validate_job_posting(posting)}
    assert {"missing_job_title", "no_required_requirements", "empty_tech_stack"} <= codes


def test_filter_grounded_evidence_drops_hallucinated_sentence():
    resume_text = "Spring Boot와 JPA로 REST API 27종을 설계했다.\nMySQL 인덱스 튜닝을 진행했다."
    profile = NormalizedUserProfile(
        evidenceMap=[
            {"evidenceId": "ev-9", "source": "prj-1", "text": "Spring Boot와 JPA로 REST API 27종을 설계했다."},
            {"evidenceId": "ev-9", "source": "prj-1", "text": "Kafka 로 실시간 이벤트 파이프라인을 구축했다."},
        ],
    )
    hallucinated = _filter_grounded_evidence(profile, resume_text)

    assert hallucinated == 1
    assert len(profile.evidenceMap) == 1
    assert profile.evidenceMap[0]["text"] == "Spring Boot와 JPA로 REST API 27종을 설계했다."


def test_filter_grounded_evidence_ignores_whitespace_differences():
    resume_text = "Spring   Boot와  JPA로\nREST API 27종을 설계했다."
    profile = NormalizedUserProfile(
        evidenceMap=[
            {"evidenceId": "ev-1", "text": "Spring Boot와 JPA로 REST API 27종을 설계했다."},
        ],
    )
    hallucinated = _filter_grounded_evidence(profile, resume_text)

    assert hallucinated == 0
    assert len(profile.evidenceMap) == 1


def test_normalize_profile_schema_warns_and_reindexes_after_dropping_hallucination():
    resume_text = "Spring Boot와 JPA로 REST API 27종을 설계했다."
    profile = NormalizedUserProfile(
        evidenceMap=[
            {"evidenceId": "ev-9", "text": "Spring Boot와 JPA로 REST API 27종을 설계했다."},
            {"evidenceId": "ev-9", "text": "원문에 없는 지어낸 문장이다."},
        ],
    )
    warnings = _normalize_profile_schema(profile, resume_text)

    assert {w["code"] for w in warnings} >= {"hallucinated_evidence"}
    assert [e["evidenceId"] for e in profile.evidenceMap] == ["ev-1"]


def test_validate_clean_posting_has_no_warnings():
    posting = NormalizedJobPosting(
        jobTitle="백엔드 개발자",
        requiredRequirements=[Requirement(requirementId="req-1", text="A")],
        techStack=["Java"],
    )
    assert _validate_job_posting(posting) == []


# --- RAG seam ------------------------------------------------------------
def test_null_rag_adapter_returns_empty_with_warning_never_raises():
    adapter = NullRagAdapter()
    res = adapter.fetch_company_context("㈜테스트", [])
    assert res.items == []
    assert res.sources == []
    assert any(w["code"] == "rag_not_connected" for w in res.warnings)

    search = adapter.search("query")
    assert search.items == []


def test_get_rag_adapter_defaults_to_null():
    assert isinstance(get_rag_adapter(), NullRagAdapter)


# --- Roadmap 예산 재적합 --------------------------------------------------
# `_refit_roadmap_to_budget` 는 roadmap_scheduler.schedule 로 정식화됐다(설계 §3.6).
# 예산 재적합에 더해 주차 배치까지 하므로, 배치 결과(RoadmapItem)로 검증한다.
def _item(title, hours, priority):
    return PlannedItem(title=title, goal="g", tasks=["t"], doneCriteria="x",
                       priority=priority, relatedRequirementIds=[], estimatedHours=hours)


def _schedule(items, *, weeks, weekly):
    return schedule(items, start_date="2026-08-01", total_weeks=weeks, weekly_hours=weekly)


def test_refit_drops_lowest_priority_until_within_budget():
    items = [_item("A", 100, "high"), _item("B", 80, "medium"), _item("C", 60, "low")]
    plan = _schedule(items, weeks=18, weekly=10)  # 예산 180h, 합 240h
    assert plan.planned_hours <= 180
    assert "C" in plan.dropped, "가장 낮은 우선순위부터 제외"
    assert any(i.title == "A" for i in plan.items), "높은 우선순위는 유지"


def test_refit_within_budget_is_unchanged():
    items = [_item("A", 100, "high"), _item("B", 50, "medium")]
    plan = _schedule(items, weeks=20, weekly=10)  # 예산 200h, 합 150h
    assert plan.dropped == [] and len(plan.items) == 2


def test_refit_caps_single_oversized_item():
    items = [_item("A", 500, "high")]
    plan = _schedule(items, weeks=18, weekly=10)  # 예산 180h
    assert len(plan.items) == 1 and plan.items[0].estimatedHours == 180, \
        "최소 1개는 남기되 예산으로 캡"


def test_schedule_places_items_sequentially_without_overlap():
    items = [_item("A", 20, "high"), _item("B", 20, "high")]
    plan = _schedule(items, weeks=8, weekly=10)
    assert len(plan.items) == 2
    assert plan.items[0].endDate < plan.items[1].startDate, "항목 기간이 겹치지 않아야 한다"


def test_schedule_drops_items_that_cannot_finish_within_horizon():
    """기간 지평을 넘기는 항목은 배치하지 않는다 — 못 지킬 일정을 적어 주는 건 거짓말이다."""
    # 예산(2주x40h=80h)은 넉넉하지만 주당 10h 로는 8주가 필요해 2주 안에 못 끝낸다
    items = [_item("A", 80, "high")]
    plan = schedule(items, start_date="2026-08-01", total_weeks=2, weekly_hours=40)
    for item in plan.items:
        assert item.endDate <= "2026-08-14", "지평(2주) 안에만 배치돼야 한다"


# --- Alternative Path Finder + RAG hook ----------------------------------
def test_build_alternative_query_combines_job_and_gaps():
    posting = {"jobTitle": "백엔드 개발자", "roleCategory": "web-backend",
               "techStack": ["Java", "Spring"]}
    gap = {"gaps": [{"requirementId": "req-2"}]}
    query = _build_alternative_query(posting, gap)
    assert "백엔드 개발자" in query and "Java" in query and "req-2" in query


def test_llm_call_failure_returns_honest_empty_not_fake(monkeypatch):
    """키는 있는데 호출이 실패하면(개발 모드 아님) 가짜 샘플 대신 빈 결과 + generation_failed 경고.

    이 테스트는 원래 find_alternatives 를 대상으로 했으나, 그 노드가 결정론으로 바뀌어
    LLM 을 호출하지 않게 되면서(설계 §3.7) 전제가 사라졌다. 원칙 자체는 여전히 중요하므로
    아직 LLM 을 쓰는 읽기 계층 노드(parse_job_posting)로 대상을 옮겼다.
    """
    import jobis_ai.structured as st

    class BoomLLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            raise RuntimeError("시뮬레이션: 일시적 API 오류")

    monkeypatch.setattr(st, "get_llm", lambda: BoomLLM())   # autouse 폴백보다 우선
    monkeypatch.setattr(st, "_RETRY_BACKOFF_SEC", 0)        # 재시도 대기 없이 빠르게

    out = parse_job_posting({
        "jobPostingInput": {"sourceType": "text", "value": "백엔드 개발자 채용. Java 경험 필요."}
    })

    posting = out["normalizedJobPosting"]
    assert posting["requiredRequirements"] == [], "호출 실패 시 가짜 요구사항을 지어내지 않는다"
    assert posting["jobTitle"] == ""
    codes = {w["code"] for w in out["warnings"]}
    assert "llm_call_failed" in codes and "generation_failed" in codes


def test_find_alternatives_never_calls_llm(monkeypatch):
    """대체 경로 판단은 결정론이다(설계 §3.7 / §4.1).

    LLM 이 죽어 있어도 정상 동작해야 한다 — 호출 자체를 하지 않기 때문이다.
    이 테스트가 깨지면 판단 계층에 LLM 이 다시 들어왔다는 뜻이고, 그건 설계 위반이다.
    """
    import jobis_ai.structured as st

    def _boom():
        raise AssertionError("판단 계층(find_alternatives)이 LLM 을 호출했다 — 설계 위반")

    monkeypatch.setattr(st, "get_llm", _boom)

    state = {
        "normalizedJobPosting": {"jobTitle": "백엔드 개발자", "roleCategory": "backend",
                                 "seniority": "senior", "techStack": ["Java"]},
        "gapAnalysisResult": {"gaps": [{"requirementId": "req-2", "severity": "high"}],
                              "strengths": []},
        "normalizedUserProfile": {},
    }
    out = find_alternatives(state)
    assert out["alternativeJobs"], "LLM 없이도 career_graph 로 경로를 낸다"


def test_find_alternatives_calls_rag_and_stays_honest_when_unconnected(monkeypatch):
    """RAG 미연결(Null)이면 rag_not_connected warning + 구체 공고 미확정(sourceJobPostingId=None)."""

    called = {"search": 0}
    real = get_rag_adapter().search

    def spy_search(query, *, top_k=5):
        called["search"] += 1
        return real(query, top_k=top_k)

    monkeypatch.setattr(get_rag_adapter(), "search", spy_search)

    state = {
        "normalizedJobPosting": {"jobTitle": "백엔드 개발자", "techStack": ["Java"]},
        "gapAnalysisResult": {"gaps": [{"requirementId": "req-2"}], "strengths": []},
    }
    out = find_alternatives(state)

    assert called["search"] == 1, "후보 검색을 RAG 어댑터에 위임해야 한다"
    assert any(w["code"] == "rag_not_connected" for w in out["warnings"])
    assert out["alternativeJobs"], "폴백이라도 경로 제안은 있어야 한다"
    assert all(j["sourceJobPostingId"] is None for j in out["alternativeJobs"]), \
        "RAG 미연결이면 구체 공고 id 를 지어내지 않는다"
