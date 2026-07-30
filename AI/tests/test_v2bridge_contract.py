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
