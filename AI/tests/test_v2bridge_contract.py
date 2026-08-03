"""v2 HTTP 계약(엔드포인트·인증·오류 코드) 검증 — 팀 ai-server 의 계약 테스트와 같은 관점.

엔진은 monkeypatch 로 대체한다(LLM 없이 1초대). 여기서 지키는 것:
  · 인증: 헤더 없으면 422, 틀리면 401 (백엔드 RestClient 가 이 코드로 실패를 구분한다)
  · 오류 코드: AI_PROVIDER_NOT_CONFIGURED / AI_PROVIDER_UNAVAILABLE / INVALID_AI_RESPONSE
  · 응답 직렬화: camelCase(alias) 로 나간다
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jobis_ai.v2bridge import service
from jobis_ai.v2bridge.app import app
from jobis_ai.v2bridge.models import (
    AnalysisQuestion,
    AnalysisResponse,
    CareerExtractionResponse,
    CareerFragmentSuggestion,
    ChangeProposal,
    ChatResponse,
    Evaluation,
    EvidenceVerificationResponse,
    JobContext,
    ProposedNode,
    ProposedRequirement,
    SuggestedAction,
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


def completed_analysis() -> AnalysisResponse:
    return AnalysisResponse(
        status="COMPLETED",
        job=JobContext(company_name="예시", role_title="백엔드"),
        evaluation=Evaluation(verdict="STRENGTHEN_THEN_APPLY",
                              summary="보완 후 지원", reasons=["요건 미충족"]),
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
def test_missing_secret_header_is_422():
    assert client.post("/v1/analyses", json=analysis_request()).status_code == 422


def test_wrong_secret_is_401():
    response = client.post("/v1/analyses", json=analysis_request(),
                           headers={"X-JOBISS-AI-SECRET": "wrong"})
    assert response.status_code == 401


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
        lines = [json_mod.loads(l) for l in res.iter_lines() if l]
    assert lines[0]["type"] == "progress" and lines[0]["label"] == "계획 수립"
    assert lines[1]["type"] == "result"
    assert lines[1]["response"]["message"] == "정리했어요."


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
    assert client.get("/v1/sessions/abc").status_code == 422
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
