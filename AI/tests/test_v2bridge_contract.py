"""v2 HTTP 계약(엔드포인트·인증·오류 코드) 검증.

엔진은 monkeypatch 로 대체한다(LLM 없이 1초대). 여기서 지키는 것:
  · 인증: 헤더 없으면 422, 틀리면 401 (백엔드 RestClient 가 이 코드로 실패를 구분한다)
  · 오류 코드: 공급자 장애 / 직무 확인 필요 / 계약 오류 / 내부 오류를 서로 구분한다
  · 응답 직렬화: camelCase(alias) 로 나간다
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from jobis_ai.v2bridge import service
import jobis_ai.v2bridge.app as app_module
from jobis_ai.v2bridge.app import app
from jobis_ai.v2bridge.models import (
    AnalysisQuestion,
    AnalysisResponse,
    AnalyzedCompetency,
    AnalyzedRequirement,
    CareerExtractionResponse,
    CareerFragmentSuggestion,
    ChangeProposal,
    ChatResponse,
    CompetencyProposal,
    Evaluation,
    EvidenceVerificationResponse,
    JobContext,
    ProposedNode,
    ProposedRequirement,
    SuggestedAction,
    TargetProjectBrief,
)

client = TestClient(app)
HEADERS = {"X-JOBISS-AI-SECRET": "local-ai-secret"}


def analysis_request() -> dict:
    return {
        "analysisJobId": str(uuid4()),
        "posting": {"id": str(uuid4()), "sourceType": "TEXT",
                    "rawText": "백엔드 개발자를 채용합니다."},
        "career": {"graphId": str(uuid4()), "version": 1, "nodes": []},
    }


def chat_request() -> dict:
    return {
        "conversationId": str(uuid4()),
        "displayName": "테스터",
        "messages": [{"role": "USER", "content": "무엇부터 준비할까요?"}],
        "career": {},
    }


def competency_proposal() -> CompetencyProposal:
    """COMPLETED 응답의 필수 산출물 — 백엔드는 이걸로 로드맵을 그린다."""

    return CompetencyProposal(
        competencies=[AnalyzedCompetency(
            ref="java", canonical_key="skill.java", title="Java",
            domain="BACKEND", kind="TECHNOLOGY", stage="LANGUAGE",
            scope_definition="Java 로 서버 로직을 구현한다.", required_level=3,
            roadmap_eligible=True,
            verification_method="저장소와 테스트 결과로 확인한다.")],
        requirements=[AnalyzedRequirement(
            competency_ref="java", relation="REQUIRED",
            source_text="Java 경험", confidence="0.9")],
        target_project=TargetProjectBrief(
            title="예시 백엔드 검증 과제", objective="필수 역량을 하나의 결과물로 증명한다.",
            domain_context="사내 서비스", required_competency_refs=["java"],
            deliverables=["실행 가능한 저장소"], acceptance_criteria=["테스트 통과"]),
    )


def completed_analysis() -> AnalysisResponse:
    return AnalysisResponse(
        status="COMPLETED",
        job=JobContext(company_name="예시", role_title="백엔드", primary_track="BACKEND"),
        evaluation=Evaluation(verdict="STRENGTHEN_THEN_APPLY",
                              summary="보완 후 지원", reasons=["요건 미충족"]),
        competency_proposal=competency_proposal(),
        change_proposal=ChangeProposal(
            base_graph_version=1,
            nodes=[ProposedNode(
                ref="java", action="CREATE", canonical_key="skill.java",
                title="Java", domain="BACKEND", kind="SKILL",
                scope_definition="Java 로 서버 로직을 구현한다.", level=2, rank=1)],
            edges=[],
            requirements=[ProposedRequirement(node_ref="java", kind="REQUIRED",
                                              source_text="Java 경험", confidence=0.9)],
        ),
    )


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------
def test_missing_secret_header_is_401():
    assert client.post("/v1/analyses", json=analysis_request()).status_code == 401


def test_wrong_secret_is_401():
    response = client.post("/v1/analyses", json=analysis_request(),
                           headers={"X-JOBISS-AI-SECRET": "wrong"})
    assert response.status_code == 401


def test_shared_secret_can_use_backend_env_name(monkeypatch):
    monkeypatch.delenv("JOBISS_AI_SHARED_SECRET", raising=False)
    monkeypatch.setenv("AI_SHARED_SECRET", "shared-production-secret")

    assert app_module._shared_secret() == "shared-production-secret"


def test_ai_specific_secret_takes_precedence(monkeypatch):
    monkeypatch.setenv("AI_SHARED_SECRET", "shared-production-secret")
    monkeypatch.setenv("JOBISS_AI_SHARED_SECRET", "ai-specific-secret")

    assert app_module._shared_secret() == "ai-specific-secret"


def test_health_reports_provider():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and "provider" in body


# ---------------------------------------------------------------------------
# 오류 코드 — 백엔드 워커의 재시도 판단 기준
# ---------------------------------------------------------------------------
def test_unconfigured_engine_never_returns_fake_success(monkeypatch):
    def _raise(request):
        raise service.EngineNotConfigured("LLM 미설정")
    monkeypatch.setattr(service, "analyze", _raise)

    response = client.post("/v1/analyses", json=analysis_request(), headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


def test_engine_failure_is_retryable_503(monkeypatch):
    def _raise(request):
        raise service.EngineFailed("판정에 이르지 못함")
    monkeypatch.setattr(service, "chat", _raise)

    response = client.post("/v1/chat", json=chat_request(), headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_PROVIDER_UNAVAILABLE"


def test_role_resolution_failure_is_not_reported_as_provider_outage(monkeypatch):
    def _raise(request):
        raise service.RoleResolutionRequired("분석 기준 직무를 선택해 주세요")
    monkeypatch.setattr(service, "analyze", _raise)

    response = client.post("/v1/analyses", json=analysis_request(), headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ROLE_RESOLUTION_REQUIRED"


def test_unexpected_failure_is_internal_error_not_provider_outage(monkeypatch):
    def _raise(request):
        raise RuntimeError("programming defect")
    monkeypatch.setattr(service, "chat", _raise)

    response = client.post("/v1/chat", json=chat_request(), headers=HEADERS)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "INTERNAL_ERROR"


def test_contract_violation_is_502(monkeypatch):
    def _raise(request):
        # 계약 위반 산출물 — NEEDS_INPUT 인데 질문이 없어 ValidationError 가 난다.
        AnalysisResponse(status="NEEDS_INPUT", question=None)
    monkeypatch.setattr(service, "analyze", _raise)

    response = client.post("/v1/analyses", json=analysis_request(), headers=HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "INVALID_AI_RESPONSE"


# ---------------------------------------------------------------------------
# 성공 직렬화 — camelCase 로 나간다
# ---------------------------------------------------------------------------
def test_completed_analysis_serializes_by_alias(monkeypatch):
    monkeypatch.setattr(service, "analyze", lambda request: completed_analysis())

    response = client.post("/v1/analyses", json=analysis_request(), headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["changeProposal"]["baseGraphVersion"] == 1
    assert body["changeProposal"]["nodes"][0]["canonicalKey"] == "skill.java"
    assert body["evaluation"]["verdict"] == "STRENGTHEN_THEN_APPLY"


def test_needs_input_carries_exactly_one_question(monkeypatch):
    question = AnalysisQuestion(
        key="target_track", text="어느 직무로 지원하나요?",
        reason="직무에 따라 결과가 달라져요.",
        options=[{"value": "backend", "label": "백엔드", "description": "백엔드 기준 분석"},
                 {"value": "frontend", "label": "프론트엔드", "description": "프론트 기준 분석"}],
    )
    monkeypatch.setattr(service, "analyze",
                        lambda request: AnalysisResponse(status="NEEDS_INPUT", question=question))

    body = client.post("/v1/analyses", json=analysis_request(), headers=HEADERS).json()
    assert body["status"] == "NEEDS_INPUT"
    assert body["question"]["key"] == "target_track"
    assert body["job"] is None and body["evaluation"] is None


def test_chat_response_contract(monkeypatch):
    monkeypatch.setattr(service, "chat", lambda request: ChatResponse(
        message="공고를 첨부하면 적합도를 볼 수 있어요.",
        intent="POSTING_ANALYSIS",
        should_request_posting=True,
        suggested_actions=[SuggestedAction(action="ATTACH_POSTING", label="공고 첨부하기")],
    ))

    body = client.post("/v1/chat", json=chat_request(), headers=HEADERS).json()
    assert body["intent"] == "POSTING_ANALYSIS"
    assert body["shouldRequestPosting"] is True
    assert body["suggestedActions"][0]["action"] == "ATTACH_POSTING"


def test_career_extraction_contract(monkeypatch):
    monkeypatch.setattr(service, "extract_career", lambda request: CareerExtractionResponse(
        summary="기술 1건을 분리했어요.",
        fragments=[CareerFragmentSuggestion(kind="SKILL", title="Python",
                                            canonical_key="skill.python")],
    ))

    body = client.post("/v1/career-extractions", headers=HEADERS, json={
        "sourceId": str(uuid4()), "sourceType": "TEXT", "title": "이력서",
        "rawText": "Python 백엔드 개발을 3년 했습니다.",
    }).json()
    assert body["fragments"][0]["canonicalKey"] == "skill.python"


def test_evidence_verification_contract(monkeypatch):
    monkeypatch.setattr(service, "verify_evidence", lambda request: EvidenceVerificationResponse(
        verdict="NEEDS_WORK", confidence=0.6, summary="근거 보완이 필요해요.",
        strengths=["프로젝트 설명이 있다"], gaps=["코드 근거 없음"], next_actions=["커밋 설명 추가"],
    ))

    body = client.post("/v1/evidence-verifications", headers=HEADERS, json={
        "evidence": {"id": str(uuid4()), "evidenceType": "PROJECT", "title": "게시판",
                     "content": {"description": "테스트 코드를 작성했습니다."}},
        "node": {"id": str(uuid4()), "title": "Spring 테스트", "domain": "BACKEND",
                 "kind": "SKILL", "scopeDefinition": "JUnit 으로 검증한다.", "level": 2},
    }).json()
    assert body["verdict"] == "NEEDS_WORK"
    assert body["nextActions"] == ["커밋 설명 추가"]


# ---------------------------------------------------------------------------
# 대화창 공고 붙여넣기 승격 — 구 브릿지(webbridge)와 같은 기준
# ---------------------------------------------------------------------------
def test_pasted_posting_is_promoted_to_attachment():
    posting = (
        "백엔드 개발자 채용\n\n담당 업무\n- Spring Boot 기반 커머스 주문/결제 API 개발과 운영\n"
        "- 대용량 트래픽 처리와 장애 대응, 성능 개선\n- 도메인 모델링과 코드 리뷰\n\n"
        "자격 요건\n- Java 또는 Kotlin 백엔드 개발 경험 2년 이상\n- RDBMS(MySQL/PostgreSQL) 설계·튜닝 경험\n"
        "- REST API 설계 경험\n\n우대 사항\n- Docker, Kubernetes, AWS 운영 경험\n"
        "- 대규모 서비스 운영 경험이 있으신 분\n- 코드 리뷰 문화에 익숙하신 분"
    )
    assert len(posting) >= 180   # 판별 기준(_POSTING_MIN_CHARS) 위에서 시험한다
    message, attachments = service.promote_pasted_posting(posting)
    assert message == ""   # 중립 발화 합성은 handle_chat 의 몫
    assert len(attachments) == 1
    assert attachments[0].kind == "job_posting"
    assert attachments[0].value == posting


def test_posting_url_is_promoted_with_url_source():
    message, attachments = service.promote_pasted_posting("https://example.com/jobs/123")
    assert message == ""
    assert attachments[0].sourceType.value == "url"


def test_ordinary_chat_is_not_promoted():
    message, attachments = service.promote_pasted_posting("백엔드 직군에 가려면 어떤걸 해야 하나요?")
    assert message and attachments == []


def test_pasted_resume_is_promoted_as_resume_not_posting():
    """이력서에도 '주요 업무' 같은 공고 어휘가 있다 — 내용 분류가 kind 를 정해야
    "공고가 아니라 이력서로 보여서…" 같은 정정 문구가 사용자에게 나가지 않는다(실측)."""

    resume = (
        "자기소개\n저는 React 와 TypeScript 로 웹 서비스를 만드는 프론트엔드 개발자입니다.\n\n"
        "프로젝트 경험\n① 마인드맵 웹 앱 (4인 팀)\n담당 역할: 프론트엔드 (기여도 50%)\n"
        "주요 업무 및 성과: 드래그 앤 드롭 카드 UI, 상태 관리 최적화\n\n"
        "링크\ngithub.com/example · 기술 블로그 운영\n\n"
        "학력\nOO대학교 컴퓨터공학과 졸업 예정 · 포트폴리오 별첨"
    )
    assert len(resume) >= 180
    message, attachments = service.promote_pasted_posting(resume)
    assert message == ""
    assert attachments and attachments[0].kind == "resume"


def test_pasted_resume_without_posting_markers_is_promoted():
    """공고 표지어("주요 업무" 등)가 없는 이력서 — 표지어 판별(_posting_in_message)에 안
    걸려 일반 대화로 흘렀고, career_chat 이 이력서 원문 위에서 즉흥 조언·판정을 만들었다
    (2026-07-31 실측). 결정론 분류(detect_kind)가 확신하면 승격해야 한다."""

    resume = (
        "자기소개\n저는 SSAFY 에서 AI 서비스를 만든 개발자입니다. 멀티에이전트 오케스트레이션과 "
        "RAG 파이프라인 설계를 맡았고, 팀 프로젝트 기여도 40% 로 백엔드 연동까지 구현했습니다.\n\n"
        "프로젝트 경험\n① 취업 지원 멀티에이전트 서비스 (6인 팀)\n"
        "- Stateful Multi-Agent 워크플로우 설계, LLM 판정 하네스 구축\n"
        "- 평가셋 재현성 측정과 회귀 테스트 정비\n\n"
        "링크\ngithub.com/example · 기술 블로그 운영\n\n학력\nOO대학교 컴퓨터공학과 졸업"
    )
    assert len(resume) >= 180
    message, attachments = service.promote_pasted_posting(resume)
    assert message == ""
    assert attachments and attachments[0].kind == "resume"


def test_career_summary_does_not_clobber_pasted_resume(monkeypatch):
    """M7: 백엔드가 매 요청 싣는 커리어 요약이, 사용자가 붙여넣은 이력서 **원문**을 덮지
    않는다(원천 우선순위: 원문 > 요약). 요약끼리(origin 표식)는 최신으로 갱신된다."""

    from uuid import uuid4 as _uuid4

    from jobis_ai.contracts.api import ChatResponse as EngineChatResponse
    from jobis_ai.orchestrator import session as session_mod
    from jobis_ai.orchestrator.session import SessionStore
    from jobis_ai.v2bridge.models import CareerSummary, ChatMessage
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    monkeypatch.setattr(
        "jobis_ai.orchestrator.chat.handle_chat",
        lambda req: EngineChatResponse(sessionId=req.sessionId, reply="네, 확인했어요."))

    conv = _uuid4()
    session_id = f"v2-chat-{conv}"
    request = V2ChatRequest(
        conversation_id=conv, display_name="신율",
        messages=[ChatMessage(role="USER", content="안녕하세요")],
        career=CareerSummary(completed_nodes=["Python 기초"]))

    # 붙여넣은 원문이 있으면 요약이 덮지 않는다
    store.update(session_id, {"resume": {"sourceType": "text", "value": "붙여넣은 이력서 원문"}})
    service.chat(request)
    assert store.get(session_id)["resume"]["value"] == "붙여넣은 이력서 원문"

    # 요약끼리는 최신으로 갱신된다
    store.update(session_id, {"resume": {
        "sourceType": "text", "value": "옛 요약", "origin": "career_summary"}})
    service.chat(request)
    assert "Python 기초" in store.get(session_id)["resume"]["value"]


def test_chat_events_streams_progress_then_result(monkeypatch):
    """D75: chat_events 는 trace 이벤트를 진행 단계로 즉시 내보내고 마지막에 result 한 건을
    낸다. 단건 chat() 은 같은 제너레이터를 소진하므로 두 경로의 처리가 갈리지 않는다."""

    from uuid import uuid4 as _uuid4

    from jobis_ai.contracts.api import ChatResponse as EngineChatResponse
    from jobis_ai.orchestrator import session as session_mod
    from jobis_ai.orchestrator.session import SessionStore
    from jobis_ai.v2bridge.models import ChatMessage
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    monkeypatch.setattr(session_mod, "_STORE", SessionStore())

    def fake_handle_chat(req):
        assert req.analysisOwner == "UNIFIED"
        from jobis_ai import trace
        trace.emit("agent_start", "공고 분석 실행 시작", {"agent": "posting_analysis"})
        trace.emit("agent_end", "공고 분석 실행 종료",
                   {"agent": "posting_analysis", "warnings": []})
        return EngineChatResponse(sessionId=req.sessionId, reply="정리했어요.",
                                  dispatched=["posting_analysis"])

    monkeypatch.setattr("jobis_ai.orchestrator.chat.handle_chat", fake_handle_chat)
    request = V2ChatRequest(conversation_id=_uuid4(), display_name="신율",
                            messages=[ChatMessage(role="USER", content="공고 분석해줘")])

    items = list(service.chat_events(request))
    assert [i["type"] for i in items] == ["progress", "progress", "result"]
    assert items[0]["step"] == "start:posting_analysis"      # 실행 중… (실시간 전용)
    assert items[1]["step"] == "posting_analysis"            # 완료
    response = items[-1]["response"]
    assert response.message == "정리했어요."
    # 사후 타임라인에는 start:* 를 싣지 않는다
    assert [s.step for s in response.progress] == ["posting_analysis"]

    # 단건 계약도 같은 결과
    assert service.chat(request).message == "정리했어요."


def test_chat_stream_endpoint_emits_ndjson(monkeypatch):
    """스트림 엔드포인트는 NDJSON 줄 단위로 진행·결과를 내보낸다 (기존 /v1/chat 불변)."""

    import json as json_mod

    def fake_events(request):
        yield {"type": "progress", "step": "planner", "label": "계획 수립",
               "detail": "선택: 공고 분석", "elapsedMs": 10}
        from jobis_ai.v2bridge.models import ChatResponse as V2ChatResponse
        yield {"type": "result", "response": V2ChatResponse(
            message="정리했어요.", intent="POSTING_ANALYSIS")}

    monkeypatch.setattr(service, "chat_events", fake_events)
    with client.stream("POST", "/v1/chat/stream", json=chat_request(), headers=HEADERS) as res:
        lines = [json_mod.loads(line) for line in res.iter_lines() if line]
    assert lines[0]["type"] == "progress" and lines[0]["label"] == "계획 수립"
    assert lines[1]["type"] == "result"
    assert lines[1]["response"]["message"] == "정리했어요."


def test_chat_stream_classifies_unexpected_failure_as_internal_error(monkeypatch):
    import json as json_mod

    def fake_events(request):
        raise RuntimeError("programming defect")
        yield  # pragma: no cover - generator shape only

    monkeypatch.setattr(service, "chat_events", fake_events)
    with client.stream("POST", "/v1/chat/stream", json=chat_request(), headers=HEADERS) as res:
        lines = [json_mod.loads(line) for line in res.iter_lines() if line]

    assert lines[0]["type"] == "ERROR"
    assert lines[0]["errorCode"] == "INTERNAL_ERROR"


def _run_chat_turn(monkeypatch, request):
    """엔진을 즉답 목으로 바꾸고 한 턴을 돌린 뒤 세션 상태를 돌려준다."""

    from jobis_ai.contracts.api import ChatResponse as EngineChatResponse
    from jobis_ai.orchestrator import session as session_mod
    from jobis_ai.orchestrator.session import SessionStore, get_session_store

    monkeypatch.setattr(session_mod, "_STORE", SessionStore())

    def fake_handle_chat(req):
        return EngineChatResponse(sessionId=req.sessionId, reply="확인했어요")

    monkeypatch.setattr("jobis_ai.orchestrator.chat.handle_chat", fake_handle_chat)
    list(service.chat_events(request))
    return get_session_store().get(f"v2-chat-{request.conversation_id}")


def test_posting_library_refreshes_from_db_each_turn(monkeypatch):
    """공고 라이브러리는 매 턴 DB 분으로 갱신된다 — 워크스페이스 스냅샷이 라이브러리를
    되살리므로 '없을 때만 시딩'이면 첫 턴 이후 추가·분석된 공고를 AI 가 영영 못 본다."""

    from uuid import uuid4 as _uuid4

    from jobis_ai.v2bridge.models import CareerSummary, ChatMessage, StoredPosting
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    request = V2ChatRequest(
        conversation_id=_uuid4(),
        display_name="신율",
        messages=[ChatMessage(role="USER", content="저장한 공고 알려줘")],
        career=CareerSummary(postings=[StoredPosting(
            raw_text="백엔드 개발자 채용 공고 본문",
            parsed_data={"companyName": "프레시컴퍼니"},
        )]),
        # 지난 턴 스냅샷: 세션에만 있던 공고는 뒤에 보존돼야 한다.
        workspace_state={"posting_library": [
            {"companyName": "붙여넣기컴퍼니", "_sourceHash": "paste-only"},
        ]},
    )
    session = _run_chat_turn(monkeypatch, request)
    library = session.get("posting_library") or []
    assert library[0]["companyName"] == "프레시컴퍼니"
    assert any(e.get("_sourceHash") == "paste-only" for e in library)


def test_roadmap_refreshes_from_backend_each_turn(monkeypatch):
    """커리어 지도는 PostgreSQL 이 정본(models.py workspace_state 계약) — 세션의 낡은 사본이 매 턴 실려 오는
    정본을 가리면 안 된다."""

    from uuid import uuid4 as _uuid4

    from jobis_ai.v2bridge.models import CareerSummary, ChatMessage
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    request = V2ChatRequest(
        conversation_id=_uuid4(),
        display_name="신율",
        messages=[ChatMessage(role="USER", content="내 지도 상태 알려줘")],
        career=CareerSummary(roadmap={"nodes": [{"id": "fresh-node"}]}),
        workspace_state={"roadmap": [{"id": "stale-node"}]},
    )
    session = _run_chat_turn(monkeypatch, request)
    assert session.get("roadmap") == [{"id": "fresh-node"}]


def test_empty_backend_roadmap_clears_stale_session_copy(monkeypatch):
    from uuid import uuid4 as _uuid4

    from jobis_ai.v2bridge.models import CareerSummary, ChatMessage
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    request = V2ChatRequest(
        conversation_id=_uuid4(),
        display_name="신율",
        messages=[ChatMessage(role="USER", content="내 지도 상태 알려줘")],
        career=CareerSummary(roadmap={"nodes": []}),
        workspace_state={"roadmap": [{"id": "stale-node"}]},
    )

    session = _run_chat_turn(monkeypatch, request)
    assert session.get("roadmap") == []


def test_roadmap_query_gets_open_map_action_from_dispatched_agent(monkeypatch):
    from uuid import uuid4 as _uuid4

    from jobis_ai.contracts.api import ChatResponse as EngineChatResponse
    from jobis_ai.orchestrator import session as session_mod
    from jobis_ai.orchestrator.session import SessionStore
    from jobis_ai.v2bridge.models import ChatMessage
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    monkeypatch.setattr(session_mod, "_STORE", SessionStore())
    monkeypatch.setattr(
        "jobis_ai.orchestrator.chat.handle_chat",
        lambda req: EngineChatResponse(
            sessionId=req.sessionId,
            reply="현재 지도를 확인해 주세요.",
            dispatched=["roadmap_manager"],
        ),
    )
    response = service.chat(V2ChatRequest(
        conversation_id=_uuid4(),
        display_name="신율",
        messages=[ChatMessage(role="USER", content="현재 로드맵 보여줘")],
    ))

    assert [action.action for action in response.suggested_actions] == ["OPEN_MAP"]


def test_career_summary_reaches_session_even_with_resume(monkeypatch):
    """확정 커리어 요약(증빙 조각·지도 항목)은 이력서와 병렬 사실이다 — 이력서가
    있다는 이유로 조각이 통째로 빠지면 안 된다."""

    from uuid import uuid4 as _uuid4

    from jobis_ai.v2bridge.models import CareerSummary, ChatMessage, StoredResume
    from jobis_ai.v2bridge.models import ChatRequest as V2ChatRequest

    request = V2ChatRequest(
        conversation_id=_uuid4(),
        display_name="신율",
        messages=[ChatMessage(role="USER", content="내 증빙 뭐 있지?")],
        career=CareerSummary(
            resumes=[StoredResume(title="저장소 이력서", raw_text="이력서 원문입니다")],
            saved_evidence=["프로젝트 · 백엔드 API 서버"],
        ),
    )
    session = _run_chat_turn(monkeypatch, request)
    resume_asset = session.get("resume") or {}
    assert "이력서 원문입니다" in resume_asset.get("value", "")
    assert "백엔드 API 서버" in resume_asset.get("value", "")


def test_progress_steps_maps_trace_timeline():
    """trace 이벤트 → 진행 과정 타임라인: 플래너 선택·실행 계획·에이전트별 소요시간·판정 노드가
    사용자 라벨로 옮겨진다(재판정 없음 — 기록의 번역)."""

    from jobis_ai.v2bridge.mapping import progress_steps

    events = [
        {"kind": "resume_intake", "label": "발화의 이력서 원문을 자산으로 등록",
         "detail": {"chars": 900}, "elapsedMs": 5},
        {"kind": "planner", "detail": {"selectedAgents": ["fit_analysis"], "confidence": 0.85},
         "elapsedMs": 1200},
        {"kind": "dispatch", "detail": {"agents": ["posting_analysis", "fit_analysis"]},
         "elapsedMs": 1210},
        {"kind": "agent_start", "detail": {"agent": "fit_analysis"}, "elapsedMs": 1300},
        {"kind": "node", "detail": {"node": "match_requirements", "durationMs": 800},
         "elapsedMs": 9000},
        {"kind": "agent_end", "detail": {"agent": "fit_analysis", "warnings": []},
         "elapsedMs": 15300},
        {"kind": "observe", "detail": {"rule": "none"}, "elapsedMs": 15310},
        {"kind": "llm_usage", "detail": {"calls": 6, "inputTokens": 1000, "outputTokens": 400},
         "elapsedMs": 15400},
    ]
    steps = progress_steps(events)
    labels = [s["label"] for s in steps]
    assert labels == ["자료 접수", "계획 수립", "실행 계획", "판정 노드 · match_requirements",
                      "적합도 분석", "LLM 사용량"]   # observe(변경 없음)는 숨긴다
    assert "확신 0.85" in steps[1]["detail"]
    assert "공고 분석 → 적합도 분석" == steps[2]["detail"]
    assert "14.0초" in steps[4]["detail"]             # agent_start→end 소요시간
    assert steps[5]["detail"] == "LLM 콜 6건 · 토큰 1000→400"


def test_progress_shows_loop_steps_delegation_and_data_flow():
    """D93: 루프 스텝(도구 호출·관찰), 에이전트 간 위임(누가→누구·받은 데이터),
    입력 자산·세션 갱신(무엇을 보고 무엇을 넘겼나)이 전부 진행 로그에 실린다."""

    from jobis_ai.v2bridge.mapping import ProgressMapper

    mapper = ProgressMapper()
    start = mapper.map({"kind": "agent_start", "elapsedMs": 10, "detail": {
        "agent": "coverletter_draft", "sessionAssets": ["analysis", "resume"]}})
    assert "입력: analysis, resume" in start["detail"]

    step = mapper.map({"kind": "agent_step", "elapsedMs": 20, "detail": {
        "agent": "coverletter_draft", "step": 2, "action": "use_tool",
        "tool": "ask_agent", "observation": "빈약 항목: 수상"}})
    assert step["label"] == "자소서 초안 루프"
    assert "도구 ask_agent 호출" in step["detail"] and "빈약 항목" in step["detail"]

    delegate = mapper.map({"kind": "delegate", "elapsedMs": 25, "detail": {
        "from": "application_plan", "target": "job_recommend", "results": 3}})
    assert delegate["label"] == "에이전트 위임"
    assert "application_plan → job_recommend" in delegate["detail"]
    assert "결과 3건" in delegate["detail"]

    refused = mapper.map({"kind": "delegate_refused", "elapsedMs": 26, "detail": {
        "target": "job_recommend", "reason": "preconditions_not_met"}})
    assert refused["label"] == "위임 거부"

    end = mapper.map({"kind": "agent_end", "elapsedMs": 5010, "detail": {
        "agent": "coverletter_draft", "warnings": [],
        "sessionUpdates": ["coverletter"]}})
    assert "넘김: coverletter" in end["detail"]                   # 오케스트레이터로의 상태 전이

    # 화자 키 — 웹이 이걸로 에이전트별 색·로고를 고른다. 에이전트가 한 일은 그 에이전트
    # 이름으로, 에이전트를 고르는 쪽(플래너·실행 계획)은 orchestrator 로 나간다.
    assert [start["agent"], step["agent"], end["agent"]] == ["coverletter_draft"] * 3
    assert delegate["agent"] == "application_plan"                # 위임의 화자는 묻는 쪽
    assert mapper.map({"kind": "planner", "elapsedMs": 1, "detail": {
        "selectedAgents": ["fit_analysis"], "confidence": 0.9}})["agent"] == "orchestrator"


def test_progress_labels_distinguish_recall_from_analysis():
    """D83: 저장된 분석을 본 턴은 '공고 분석'이 아니라 '분석 자료 검토'로, 저장 정보를 대화
    근거로 쓴 턴은 '이전 대화 검토'로 표시된다 — 로그가 실제 일과 일치해야 한다."""

    from jobis_ai.v2bridge.mapping import progress_steps

    steps = progress_steps([
        {"kind": "agent_end", "detail": {"agent": "posting_analysis", "warnings": [],
                                         "data": {"fromCache": True}}, "elapsedMs": 6400},
        {"kind": "recall", "label": "저장된 공고 정리에서 물은 항목만 조회",
         "detail": {}, "elapsedMs": 6500},
    ])
    assert steps[0]["label"] == "분석 자료 검토"
    assert "저장된 공고 정리에서 조회" in steps[0]["detail"]
    assert steps[1]["label"] == "이전 대화 검토"


def test_mixed_url_and_resume_message_is_left_to_engine():
    """URL + 이력서 + 요청 문장이 섞인 메시지는 브릿지가 통째로 첨부하지 않는다 —
    통째 승격은 URL(공고)과 요청 문장을 첨부 속으로 삼킨다(실측 2026-07-31).
    엔진이 URL/이력서를 각각 발화에서 승격하고 요청 문장은 플래너 입력으로 남긴다."""

    mixed = (
        "https://example.com/jobs/123 이게 내 목표공고이고, "
        "자기소개\n저는 SSAFY 에서 AI 서비스를 만든 개발자입니다. 멀티에이전트 오케스트레이션과 "
        "RAG 파이프라인 설계를 맡았고, 팀 프로젝트 기여도 40% 로 백엔드 연동까지 구현했습니다. "
        "github.com/example · OO대학교 졸업 · 포트폴리오 별첨. "
        "이게 내 이력서야. 공고와 이력서 각각 분석하고 적합도 분석 진행해줘"
    )
    assert len(mixed) >= 180
    message, attachments = service.promote_pasted_posting(mixed)
    assert message == mixed and attachments == []


def test_long_ambiguous_chat_is_not_promoted():
    """긴 발화라도 신호 어휘가 확실하지 않으면 대화로 남는다 — 애매한 글을 자산으로
    승격하면 일반 상담 글이 이력서로 저장된다(보수 기준 유지)."""

    long_chat = (
        "요즘 백엔드 직군 준비를 하면서 고민이 많습니다. 스프링을 먼저 깊게 파야 할지, "
        "아니면 CS 기초(운영체제, 네트워크, 데이터베이스)를 다시 정리해야 할지 순서를 못 정하겠어요. "
        "주변에서는 프로젝트를 하나 더 하라고 하는데 시간이 부족하고, 코딩 테스트 준비도 병행해야 해서 "
        "하루를 어떻게 나눠 써야 할지 모르겠습니다. 지금 상황에서 무엇부터 하는 게 좋을까요?"
    )
    assert len(long_chat) >= 180
    message, attachments = service.promote_pasted_posting(long_chat)
    assert message and attachments == []


def test_pasted_posting_keeps_trailing_request_as_utterance():
    """자료 뒤에 붙은 **요청 문장은 발화로 남는다**(D100).

    실측(2026-08-01): 공고 원문 끝에 "이 공고 기준으로 어떤 스택을 공부하고 어떤 프로젝트를
    만들면 좋을까요?" 를 붙여 보냈는데, 통째로 첨부되고 발화가 비워져 `handle_chat` 이 중립
    발화를 합성했다 — 플래너도 에이전트 루프도 사용자가 무엇을 물었는지 모른 채 요약만 냈다.
    D69 가 URL 혼합 메시지에 한 보존을 붙여넣기 경로에도 한다.
    """

    posting = (
        "AI/Agent 엔지니어 채용\n\n담당업무\n- LLM 기반 에이전트 파이프라인 설계 및 운영\n"
        "- 상담 데이터 수집·정제 ETL 파이프라인 구축\n\n자격요건\n"
        "- 데이터 엔지니어링 또는 ML 엔지니어링 경력 3~7년\n- Python 기반 데이터 처리 실무 경험\n"
        "- Airflow / Dagster / Prefect 중 하나 이상 운영 경험\n\n우대사항\n"
        "- LangChain 또는 LlamaIndex 활용 경험\n- AWS / GCP / Azure 중 하나의 운영 경험"
    )
    request = "이 공고 기준으로 제가 어떤 스택을 공부하고 어떤 프로젝트를 만들면 좋을까요?"

    message, attachments = service.promote_pasted_posting(f"{posting}\n\n{request}")
    assert message == request, "요청 문장이 첨부 속으로 삼켜지면 안 된다"
    assert len(attachments) == 1 and attachments[0].kind == "job_posting"
    # 첨부는 자르지 않는다 — 자료 본문을 잃는 것이 꼬리 한 줄이 남는 것보다 나쁘다.
    assert request in attachments[0].value

    # 요청 없이 자료만 온 턴은 그대로 비운다(중립 발화 합성은 handle_chat 의 몫).
    message, attachments = service.promote_pasted_posting(posting)
    assert message == "" and len(attachments) == 1


def test_posting_body_lines_are_not_mistaken_for_a_request():
    """자료 본문 줄을 요청으로 오인해 발화로 새어 나가면 안 된다(보수 기준)."""

    from jobis_ai.v2bridge.service import _trailing_request

    # 개조식 공고 본문 — 요청 표지가 없다.
    assert _trailing_request("자격요건\n- Python 3년\n- SQL 능숙") == ""
    # 표지가 있어도 공고 표지어가 같은 줄에 있으면 본문으로 본다.
    assert _trailing_request("경력 3년\n우대사항: 코드 리뷰 문화에 익숙하신 분이면 좋을까요?") == ""
    # 물음표로 끝나는 짧은 꼬리는 요청이다.
    assert _trailing_request("경력 3년\n\n분석해 주세요") == "분석해 주세요"


# ---------------------------------------------------------------------------
# 세션 상태 조회 (D128 — 프로토타입 2.0.0 GET /session 이식)
# ---------------------------------------------------------------------------
def test_session_state_requires_secret():
    assert client.get("/v1/sessions/abc").status_code == 401
    assert client.get("/v1/sessions/abc",
                      headers={"X-JOBISS-AI-SECRET": "wrong"}).status_code == 401


def test_session_state_summarizes_assets():
    """세션에 쌓인 자산의 목록·개수를 그대로 옮겨 적는다 — 판단 없음, 읽기 전용."""

    from jobis_ai.orchestrator.session import get_session_store

    store = get_session_store()
    store.update("v2-chat-conv1", {
        "resume": {"sourceType": "text", "value": "이력서", "origin": "career_summary"},
        "resume_library": [{"_label": "커리어 저장소"}],
        "posting_library": [{"companyName": "가나다", "jobTitle": "백엔드"}],
        "recommendations": [{"companyName": "라마바", "title": "프론트엔드",
                             "url": "https://x.test/2"}],
        "analysis": {"fitGrade": "중"},
        "history": [{"role": "user", "content": "안녕"},
                    {"role": "assistant", "content": "안녕하세요"}],
    })
    body = client.get("/v1/sessions/conv1", headers=HEADERS).json()
    assert body["exists"] is True
    assert body["activeResume"] == "커리어 저장소"
    assert body["resumeLibrary"] == ["커리어 저장소"]
    assert body["postingLibrary"] == [{"company": "가나다", "title": "백엔드"}]
    assert body["recommendations"] == [{"company": "라마바", "title": "프론트엔드",
                                        "url": "https://x.test/2"}]
    assert body["analysisGrade"] == "중"
    assert body["historyTurns"] == 2


def test_session_state_for_unknown_session_is_empty_not_error():
    """없는 세션은 404 가 아니라 빈 요약이다 — 백엔드가 폴링해도 오류 로그가 쌓이지 않게."""

    body = client.get("/v1/sessions/no-such", headers=HEADERS).json()
    assert body["exists"] is False
    assert body["historyTurns"] == 0


def test_degraded_reason_marks_deterministic_fallback():
    """LLM 호출 실패로 나간 답변은 **사용자에게 폴백이라고 알린다**(08-03 사고).

    폴백 문장이 그럴듯해서 사용자가 요약본을 분석 결과로 읽었다. 판정하지 않고
    `llm_call_failed` 경고가 달렸다는 사실만 옮긴다 — 그 경고는 재시도를 소진했을 때만 붙는다.
    """

    from jobis_ai.v2bridge.mapping import degraded_reason

    reason = degraded_reason([
        {"code": "llm_call_failed",
         "message": "posting_analysis: LLM 호출 3회 재시도 후 실패 — Invalid JSON"},
        {"code": "loop_reply_rewritten", "message": "career_chat: 금지표현"},
    ])
    assert "공고 분석" in reason            # 노드 키가 아니라 사람이 읽는 이름
    assert "분석 결과가 아닙니다" in reason
    assert len(reason) <= 300               # ChatResponse.degraded_reason 상한

    # 재시도로 흡수된 턴·정상 턴은 표식이 없다 — 있는 실패만 말한다.
    assert degraded_reason([{"code": "loop_reply_rewritten", "message": "career_chat: x"}]) == ""
    assert degraded_reason([]) == ""


# ---------------------------------------------------------------------------
# 대화로 확보한 자산의 백엔드 적재 (D141)
# ---------------------------------------------------------------------------
def _collected(session: dict, attachment_kinds: tuple[str, ...], dispatched: tuple[str, ...],
               monkeypatch):
    class _Att:
        def __init__(self, kind): self.kind = kind

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store",
                        lambda: type("S", (), {"get": lambda _s, _sid: session})())
    # outputs_before=세션 그대로 — 이 턴에 산출물·블롭이 안 바뀐 상황을 본다(블롭은 ⓐ 이후
    # 무엇이든 바뀌면 통째로 실리므로, 여기 관심사인 posting/resume 칸만 남게 고정한다).
    return service._collected_assets(
        "v2-chat-x", [_Att(k) for k in attachment_kinds], list(dispatched),
        outputs_before=session)


def test_collected_carries_the_fetched_body_not_the_url(monkeypatch):
    """**URL 로 받은 공고도 원문이 실려 나간다** — 백엔드가 그것으로 채용공고 행을 만든다.

    실측(2026-08-03): 채팅에 URL 을 붙이면 AI 는 수집·파싱·판정까지 하는데 백엔드는 그 공고를
    모른다(`ConversationService` 는 첨부 UI 경로에서만 공고를 만들고 `ChatRequest` 는
    role·content 만 싣는다). 세션 `v2-chat-c1470d00` 의 공고가 `job_postings` 에 없었고,
    그래서 사이드바 채용공고 페이지도 커리어지도도 그 공고를 볼 수 없었다.
    """

    session = {
        "job_posting": {"sourceType": "text", "value": "가나테크 백엔드 개발자\n자격요건\n- Java 3년",
                        "sourceUrl": "https://example.test/jobs/1"},
        "posting_summary": {"companyName": "가나테크", "jobTitle": "백엔드 개발자",
                            "yearsEvidence": "경력 3년 이상", "requiredRequirements": ["Java 3년"]},
    }
    collected = _collected(session, (), ("posting_fetch", "fit_analysis"), monkeypatch)
    assert collected is not None and collected.posting is not None
    assert collected.posting.source_type == "URL"
    assert collected.posting.source_url == "https://example.test/jobs/1"
    assert "자격요건" in collected.posting.raw_text, "주소가 아니라 수집한 원문이어야 한다"
    # 파싱 결과는 싣지 않는다 — `company_name`·`parsed_data` 의 writer 는
    # `AnalysisWorker.complete` 하나다. 여기서 또 내면 같은 열을 둘이 쓴다.
    assert not hasattr(collected.posting, "parsed_data")


def test_collected_is_absent_when_nothing_was_captured_this_turn(monkeypatch):
    """자산이 세션에 있다는 것만으로 싣지 않는다 — 턴마다 보내면 같은 공고가 계속 다시 만들어진다."""

    session = {"job_posting": {"sourceType": "text", "value": "가나테크 백엔드 자격요건 Java"}}
    assert _collected(session, (), ("career_chat",), monkeypatch) is None


def test_collected_never_ships_a_bare_url_as_the_body(monkeypatch):
    """수집이 실패해 주소만 남았으면 싣지 않는다 — 주소를 원문 칸에 넣는 그 사고를 되풀이하지 않는다."""

    session = {"job_posting": {"sourceType": "url", "value": "https://example.test/jobs/1"}}
    assert _collected(session, ("job_posting",), ("posting_fetch",), monkeypatch) is None


def test_collected_does_not_echo_the_backend_career_summary(monkeypatch):
    """백엔드가 실어 보낸 확정 요약은 되돌려주지 않는다 — 자기가 준 것을 다시 적재하게 된다."""

    session = {"resume": {"sourceType": "text", "value": "[보유 증빙]\n- SKILL · Java",
                          "origin": "career_summary"}}
    assert _collected(session, ("resume",), (), monkeypatch) is None

    session["resume"] = {"sourceType": "text", "value": "저는 백엔드 개발자입니다. Java 3년."}
    collected = _collected(session, ("resume",), (), monkeypatch)
    assert collected is not None and collected.resume is not None
    assert collected.resume.raw_text.startswith("저는 백엔드")


def test_collected_ships_preferences_and_facts_only_when_they_change(monkeypatch):
    """선호·지속 사실도 백엔드 테이블에 적재된다 (D141) — 단, **이번 턴에 바뀐 경우만.**

    전에는 이 둘이 AI 세션에만 있었다: 대화가 끝나거나 세션이 지워지면 사라진다.
    턴마다 실어 보내면 payload 만 커지므로 턴 시작 전 상태와 비교한다 — 백엔드가 무엇을
    갖고 있는지 우리는 모르므로(요청의 career 에 선호·사실이 없다) 기준점은 우리 직전 상태다.
    """

    session = {"preferences": {"roles": ["백엔드"], "domains": []},
               "user_facts": ["백엔드 개발자로 취업이 목표", "SSAFY 수료"]}

    def collected(before):
        monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store",
                            lambda: type("S", (), {"get": lambda _s, _sid: session})())
        return service._collected_assets("v2-chat-x", [], ["preference_intake"], before,
                                         outputs_before=session)

    # 선호가 바뀌고 사실이 늘었다 → 둘 다 싣는다(사실은 누적 전량 — upsert 는 멱등이다)
    got = collected(({}, 0))
    assert got is not None
    assert got.preferences == {"roles": ["백엔드"], "domains": []}
    assert got.facts == ["백엔드 개발자로 취업이 목표", "SSAFY 수료"]

    # 아무것도 안 바뀐 턴 → 싣지 않는다
    assert collected(({"roles": ["백엔드"], "domains": []}, 2)) is None

    # 사실만 늘어난 턴 → 사실만
    only_facts = collected(({"roles": ["백엔드"], "domains": []}, 1))
    assert only_facts is not None
    assert only_facts.preferences is None and len(only_facts.facts) == 2


def test_collected_serializes_by_alias_for_the_backend(monkeypatch):
    """`collected` 는 백엔드가 파싱할 camelCase 로 나가야 한다 (D141).

    이 경로는 e2e 로 확인하지 못했다(로컬 PostgreSQL 컨테이너가 없다). 백엔드는
    `collected.posting.rawText` 를 읽어 JobPostingService.create 를 부르므로, alias 가 어긋나면
    Jackson 이 그 칸을 null 로 읽고 **적재가 조용히 사라진다.** 그 침묵을 여기서 막는다.
    """

    from jobis_ai.v2bridge.models import CollectedAssets, CollectedPosting, CollectedResume

    monkeypatch.setattr(service, "chat", lambda request: ChatResponse(
        message="공고를 정리했어요.",
        intent="POSTING_ANALYSIS",
        collected=CollectedAssets(
            posting=CollectedPosting(source_type="URL",
                                     source_url="https://example.test/jobs/1",
                                     raw_text="가나테크 백엔드\n자격요건\n- Java 3년"),
            resume=CollectedResume(title="대화로 받은 이력서", raw_text="저는 백엔드 개발자입니다."),
            preferences={"roles": ["백엔드"]},
            facts=["백엔드 개발자로 취업이 목표"],
        ),
    ))

    body = client.post("/v1/chat", json=chat_request(), headers=HEADERS).json()
    collected = body["collected"]
    assert collected["posting"]["sourceType"] == "URL"
    assert collected["posting"]["sourceUrl"] == "https://example.test/jobs/1"
    assert "자격요건" in collected["posting"]["rawText"]
    assert collected["resume"]["rawText"].startswith("저는 백엔드")
    assert collected["preferences"] == {"roles": ["백엔드"]}
    assert collected["facts"] == ["백엔드 개발자로 취업이 목표"]


def test_collected_omits_empty_fields_instead_of_sending_null():
    """`collected` 의 빈 칸은 **null 로도 내지 않는다** — 키 자체가 없어야 한다.

    실측(08-03, ⓐ 첫 실경로): 백엔드 Jackson 은 `JsonNode` 칸의 JSON null 을 `NullNode` 로
    읽어 `!= null` 가드를 통과시킨다. `"profile": null` 이 그 가드를 지나 `ai_user_profiles`
    에 null 을 넣다 shape check 에 걸렸고, **같은 트랜잭션의 블롭 적재까지 함께 죽었다.**
    """

    import json as json_mod

    from jobis_ai.v2bridge.models import CollectedAssets, CollectedOutputs

    payload = json_mod.loads(CollectedAssets(
        outputs=CollectedOutputs(session_state={"user_facts": ["9월 취업"]}),
    ).model_dump_json(by_alias=True))
    assert payload == {"outputs": {"sessionState": {"user_facts": ["9월 취업"]}}}


def test_collected_is_null_when_nothing_was_captured(monkeypatch):
    """자산을 확보하지 않은 턴은 `collected` 가 null 이다 — 백엔드가 빈 적재를 돌리지 않게."""

    monkeypatch.setattr(service, "chat", lambda request: ChatResponse(
        message="무엇을 도와드릴까요?", intent="GENERAL_CAREER"))
    assert client.post("/v1/chat", json=chat_request(), headers=HEADERS).json()["collected"] is None


def test_confirmed_summary_is_the_resume_source_only_when_none_exists(monkeypatch):
    """이력서가 아직 없으면 확정 항목 요약이 이력 원천이 된다(추가만 하는 변경)."""

    from jobis_ai.v2bridge.models import ChatRequest

    request = ChatRequest(
        conversationId=uuid4(), displayName="테스터",
        messages=[{"role": "USER", "content": "안녕"}],
        career={"completedNodes": ["Java"], "activeGoals": ["백엔드 취업"]},
    )
    assert "Java" in service._career_summary_text(request)


def test_outputs_ship_only_what_this_turn_made(monkeypatch):
    """대화가 만든 산출물은 **이번 턴에 생긴 것만** 실린다 (§2-4~2-7, V23 테이블들).

    매 턴 전량을 보내면 append 형 테이블(`posting_recommendations`·`application_plans`)에
    같은 행이 계속 쌓인다. 그래서 턴 시작 전 상태와 비교한다.
    """

    session = {
        "analysis": {"fitGrade": "중", "overallScore": 0.6},
        "roadmap": [{"title": "Kafka 학습"}],
        "recommendations": [{"companyName": "가나테크"}],
        "pendingRequest": {"agent": "fit_analysis", "missing": ["resume"], "turnsLeft": 2},
    }

    class _Store:
        def get(self, _sid): return dict(session)

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: _Store())

    # 판정과 로드맵은 이미 있었고 추천만 새로 생긴 턴
    before = {"analysis": session["analysis"], "roadmap": session["roadmap"],
              "recommendations": None, "pendingRequest": session["pendingRequest"]}
    outputs = service._collected_outputs("v2-chat-o", before)
    assert outputs is not None
    assert outputs.recommendations == [{"companyName": "가나테크"}]
    assert outputs.analysis is None and outputs.roadmap is None, "안 바뀐 것은 싣지 않는다"
    # 진실의 출처 블롭(ⓐ)은 무엇이든 바뀐 턴에 세션 **전체**를 싣는다 — 부분 갱신이 없어야
    # 백엔드 upsert 와 다음 턴 복원이 갈리지 않는다
    assert set(outputs.session_state) == set(session)

    # 아무것도 안 바뀐 턴 → None (백엔드가 빈 적재를 돌리지 않는다)
    assert service._collected_outputs("v2-chat-o", dict(session)) is None

    # 판정이 새로 난 턴 → 판정·로드맵이 함께 간다(같은 행 engine_result 로 모인다)
    fresh = service._collected_outputs("v2-chat-o", {})
    assert fresh.analysis["fitGrade"] == "중"
    assert fresh.roadmap == [{"title": "Kafka 학습"}]
    # 턴을 넘겨야 하는 약속도 블롭에 실려 돌아온다
    assert fresh.session_state["pendingRequest"]["turnsLeft"] == 2
    assert not hasattr(fresh, "pending_request")


def test_chat_produces_the_map_material_from_conversation_assets(monkeypatch):
    """대화가 쌓은 자산으로 **지도 재료**를 만든다 — 사용자 지시("로드맵 생성까지 대화로").

    지금까지 이 재료를 만들 수 있는 곳은 분석 작업 하나였고, 그 경로는 대화로 쌓인 자산을
    보지 못했다. 재료를 만드는 코드는 분석 경로와 **같은 함수**(`build_competency_proposal`)를
    쓴다 — 여기서 다시 구현하면 두 경로의 지도가 갈린다.
    """

    posting = {
        "companyName": "가나테크", "jobTitle": "백엔드 개발자", "roleCategory": "backend",
        "requiredRequirements": ["Java 및 Spring Boot 실무 경험"],
        "preferredRequirements": ["Kafka 운영 경험"],
        "techStack": ["Java", "Spring Boot"], "minYears": 3,
    }
    session = {
        "analysis": {"status": "completed", "fitGrade": "중",
                     "gaps": [{"requirementId": "req-2", "missingSkills": ["Kafka"]}]},
        "posting_summary": posting,
        "judgment_summary": {"requirementStatus": [
            {"requirementId": "req-1", "text": "Java 및 Spring Boot 실무 경험",
             "type": "required", "status": "met"},
            {"requirementId": "pref-1", "text": "Kafka 운영 경험",
             "type": "preferred", "status": "not_met"},
        ]},
    }

    class _Store:
        def get(self, _sid): return dict(session)

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: _Store())
    # LLM 분류는 미설정(conftest)이라 결정론 결과만으로 만들어진다 — 그래도 재료가 나와야 한다
    proposal, job_context = service._competency_proposal_for_chat("v2-chat-map")
    assert proposal is not None
    keys = {c.canonical_key for c in proposal.competencies}
    assert "skill.java" in keys
    assert proposal.target_project.required_competency_refs, "증명 대상이 있어야 지도가 그려진다"
    # 공고 맥락도 함께 간다 — 이게 없으면 백엔드가 빈 job 을 캐시에 넣어 재사용 경로가 죽는다
    assert job_context is not None
    assert job_context.primary_track == "BACKEND"

    # 판정이 없으면 만들지 않는다 — 없는 재료를 지어내지 않는다
    session["analysis"] = {"status": "need_more_info"}
    assert service._competency_proposal_for_chat("v2-chat-map") == (None, None)


def test_chat_map_material_preserves_ai_engine_role(monkeypatch):
    """ml_engineer를 AI로 바꾼 뒤 다시 해석해 실패하던 실제 회귀 경로다."""

    session = {
        "analysis": {
            "status": "completed",
            "fitGrade": "중",
            "gaps": [{"requirementId": "req-1", "missingSkills": ["Python"]}],
        },
        "posting_summary": {
            "companyName": "인사이트365",
            "jobTitle": "Agentic Coding 개발자",
            "roleCategory": "ml_engineer",
            "requiredRequirements": ["Python 기반 AI 에이전트 개발 경험"],
            "techStack": ["Python"],
        },
        "judgment_summary": {"requirementStatus": [
            {
                "requirementId": "req-1",
                "text": "Python 기반 AI 에이전트 개발 경험",
                "type": "required",
                "status": "not_met",
            }
        ]},
    }

    class _Store:
        def get(self, _sid): return dict(session)

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: _Store())

    proposal, job_context = service._competency_proposal_for_chat("v2-chat-ai-map")

    assert proposal is not None
    assert job_context is not None
    assert job_context.primary_track == "AI"
    assert job_context.parsed_data["roleResolution"]["specialization"] == "ML_ENGINEER"


def test_map_material_ships_only_when_the_judgment_is_new(monkeypatch):
    """이미 있던 판정에는 재료를 만들지 않는다 — 같은 재료를 매 턴 다시 적재하게 된다."""

    session = {"analysis": {"status": "completed"}, "posting_summary": {"jobTitle": "백엔드"},
               "judgment_summary": {"requirementStatus": [{"requirementId": "r1"}]}}

    class _Store:
        def get(self, _sid): return dict(session)

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: _Store())
    called: list = []
    monkeypatch.setattr(service, "_competency_proposal_for_chat",
                        lambda sid: (called.append(sid), None))

    # 판정이 이미 있던 턴 → 재료를 만들지 않는다
    service._collected_outputs("v2-chat-m", {"analysis": session["analysis"]})
    assert called == []

    # 판정이 새로 난 턴 → 만든다
    service._collected_outputs("v2-chat-m", {})
    assert called == ["v2-chat-m"]


def test_request_accepts_nullable_backend_columns():
    """백엔드의 **nullable 컬럼**이 null 로 와도 요청이 거부되지 않아야 한다.

    실측(2026-08-03 22:28, 실 경로): `career_sources.title` 과 `job_postings.parsed_data` 가
    null 로 왔는데 우리가 non-null 로 선언해서 **요청 전체가 422** 로 거부됐다 — 화면에는
    "AI 서비스 요청을 처리하지 못했습니다"만 떴고 대화가 통째로 죽었다. 모듈 docstring 이
    경고한 그 사고다: *"요청 쪽 누락이 곧 장애다."* 받는 쪽은 넉넉하게, 쓰는 쪽에서 기본값을 준다.
    """

    from jobis_ai.v2bridge.models import ChatRequest

    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()), "displayName": "테스터",
        "messages": [{"role": "USER", "content": "안녕"}],
        "career": {
            "resumes": [{"id": str(uuid4()), "title": None, "sourceType": "TEXT",
                         "rawText": "이력서 원문", "createdAt": None}],
            "postings": [{"id": str(uuid4()), "sourceType": "URL",
                          "sourceUrl": "https://example.test/1", "rawText": "공고 원문",
                          "parsedData": None, "createdAt": None}],
            "preferences": None, "facts": [], "sessionState": None, "interview": None,
        },
    })
    assert request.career.resumes[0].title is None
    assert request.career.postings[0].parsed_data is None


def test_seeded_posting_does_not_suppress_the_first_look(monkeypatch):
    """**자산 복원이 에이전트의 "방금 받았나" 판단을 덮어쓰지 않는다** (D151).

    무상태 전환에서 공고 파싱 결과를 요청으로 복원해 심었는데(§2-3), `posting_analysis` 는
    `posting_summary._sourceHash` 가 맞으면 "이미 정리해 본 공고"로 읽어 **전 항목 정리를
    건너뛴다**. 실측(08-03): 공고를 처음 붙인 턴인데 요건 정리가 안 나왔다 — 파싱을 아끼려던
    복원이 사용자에게 보여줄 것까지 지웠다.

    파싱 재사용(`fromCache`)과 보여준 적 있나(`alreadyShown`)는 다른 사실이다.
    """

    import hashlib

    from jobis_ai.agents.posting_analysis import _parse

    body = "가나테크 백엔드 개발자\n자격요건\n- Java 3년 이상"
    src_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
    parsed = {"companyName": "가나테크", "jobTitle": "백엔드 개발자",
              "requiredRequirements": ["Java 3년 이상"], "preferredRequirements": [],
              "techStack": ["Java"], "domainKeywords": []}

    def run_with(origin: str | None):
        summary = {**parsed, "_sourceHash": src_hash, "_sourceText": body}
        if origin:
            summary["_origin"] = origin
        session = {"job_posting": {"sourceType": "text", "value": body},
                   "posting_summary": summary}
        _posting, data, _updates, _warnings, _text = _parse(session)
        return data

    # 백엔드에서 복원해 심은 것 → 파싱은 재사용하되 **보여준 적은 없다**
    seeded = run_with("backend")
    assert seeded["fromCache"] is True, "파싱은 다시 하지 않는다(수십 초를 아낀다)"
    assert seeded["alreadyShown"] is False, "심은 것을 '봤다'로 세면 요건 정리가 사라진다"

    # 이 대화에서 직접 정리한 것 → 다시 낭독하지 않는다(D81 유지)
    ours = run_with(None)
    assert ours["fromCache"] is True and ours["alreadyShown"] is True
