import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app, get_analysis_service
from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStageDefinition,
    AnalysisStreamEvent,
    AssessmentQuestion,
    CareerExtractionResponse,
    CareerFragmentSuggestion,
    ChatResponse,
    ClarificationDecision,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    CompletedAnalysisResponse,
    Evaluation,
    EvidenceVerificationResponse,
)
from app.service import AnalysisService
from app.settings import Settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def unconfigured_provider():
    app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(
        Settings(analysis_provider="unconfigured", _env_file=None)
    )
    yield
    app.dependency_overrides.clear()


def valid_request() -> dict:
    return {
        "analysisJobId": str(uuid4()),
        "posting": {
            "id": str(uuid4()),
            "sourceType": "TEXT",
            "sourceUrl": None,
            "rawText": "백엔드 개발자를 채용합니다.",
        },
        "career": {
            "graphId": str(uuid4()),
            "version": 1,
            "nodes": [],
        },
    }


def test_health_is_explicit_about_provider() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["provider"] == "unconfigured"


def test_analysis_requires_internal_secret() -> None:
    response = client.post("/v1/analyses", json=valid_request())
    assert response.status_code == 422


def test_unconfigured_provider_never_returns_fake_success() -> None:
    response = client.post(
        "/v1/analyses",
        json=valid_request(),
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


def test_stream_preserves_progress_and_reports_provider_error() -> None:
    response = client.post(
        "/v1/analyses/stream",
        json=valid_request(),
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
    )

    assert response.status_code == 200
    events = [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "ERROR"
    assert events[-1]["errorCode"] == "AI_PROVIDER_NOT_CONFIGURED"


def test_chat_contract_rejects_fake_success_without_provider() -> None:
    response = client.post(
        "/v1/chat",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "conversationId": str(uuid4()),
            "displayName": "테스터",
            "messages": [{"role": "USER", "content": "백엔드 개발자가 되고 싶어요."}],
            "career": {
                "completedNodes": [],
                "activeGoals": [],
                "recentPostings": [],
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


def test_career_extraction_never_returns_fake_success_without_provider() -> None:
    response = client.post(
        "/v1/career-extractions",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "sourceId": str(uuid4()),
            "sourceType": "TEXT",
            "title": "게시판 프로젝트",
            "rawText": "Spring Boot로 게시판 API를 개발하고 쿼리 성능을 개선했습니다.",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"


def test_evidence_contract_validates_node_and_payload() -> None:
    response = client.post(
        "/v1/evidence-verifications",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "evidence": {
                "id": str(uuid4()),
                "evidenceType": "PROJECT",
                "title": "게시판 프로젝트",
                "content": {"description": "테스트 코드를 작성했습니다."},
            },
            "node": {
                "id": str(uuid4()),
                "title": "Spring 테스트",
                "domain": "BACKEND",
                "kind": "SKILL",
                "scopeDefinition": "JUnit으로 서비스 계층을 검증한다.",
                "level": 2,
            },
        },
    )

    assert response.status_code == 503


def valid_analysis_response() -> dict:
    return {
        "status": "COMPLETED",
        "job": {
            "companyName": "Example",
            "roleTitle": "Backend Engineer",
            "primaryTrack": "BACKEND",
            "experienceRequirement": {
                "type": "NONE",
                "minimumMonths": 0,
                "maximumMonths": None,
                "sourceText": "신입·경력 무관",
            },
            "parsedData": {},
        },
        "evaluation": {
            "verdict": "STRENGTHEN_THEN_APPLY",
            "summary": "보완 후 지원할 수 있습니다.",
            "reasons": ["필수 기술 경험이 필요합니다."],
        },
        "competencyProposal": {
            "competencies": [
                {
                    "ref": "java",
                    "canonicalKey": "skill.java",
                    "title": "Java",
                    "domain": "BACKEND",
                    "kind": "TECHNOLOGY",
                    "stage": "LANGUAGE",
                    "scopeDefinition": "Java로 서버 로직을 구현한다.",
                    "requiredLevel": 2,
                    "roadmapEligible": True,
                    "verificationMethod": "실행 가능한 Java 서버 코드와 테스트로 확인",
                }
            ],
            "requirements": [
                {
                    "competencyRef": "java",
                    "relation": "REQUIRED",
                    "sourceText": "Java 경험",
                    "confidence": 0.9,
                }
            ],
            "targetProject": {
                "title": "Example 백엔드 맞춤 프로젝트",
                "objective": "Java 서버 구현 역량을 검증합니다.",
                "domainContext": "Example 서비스 도메인을 반영합니다.",
                "requiredCompetencyRefs": ["java"],
                "optionalCompetencyRefs": [],
                "deliverables": ["실행 가능한 Git 저장소"],
                "acceptanceCriteria": ["Java로 핵심 API가 동작합니다."],
            },
        },
    }


class OrchestrationProbeProvider:
    name = "orchestration-probe"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def decide_clarification(
        self, request: AnalysisRequest
    ) -> ClarificationDecision:
        self.calls.append("clarification")
        return ClarificationDecision(status="CONTINUE")

    async def complete_posting_analysis(
        self, request: AnalysisRequest
    ) -> CompletedAnalysisResponse:
        self.calls.append("posting")
        payload = valid_analysis_response()
        return CompletedAnalysisResponse.model_validate(payload)

    async def evaluate_shared_analysis(
        self, request: AnalysisRequest
    ) -> Evaluation:
        self.calls.append("fit")
        return Evaluation(
            verdict="STRENGTHEN_THEN_APPLY",
            summary="현재 사용자 기준으로 다시 비교했습니다.",
            reasons=["검증되지 않은 필수 역량이 남아 있습니다."],
        )


def test_actual_orchestration_stages_wrap_fresh_analysis() -> None:
    service = AnalysisService(
        Settings(analysis_provider="unconfigured", _env_file=None)
    )
    provider = OrchestrationProbeProvider()
    service._provider = provider
    request = AnalysisRequest.model_validate(valid_request())

    async def collect_events():
        return [event async for event in service.analyze_stream(request)]

    events = asyncio.run(collect_events())
    stage_ids = [stage.id for stage in events[0].stages]
    updated_ids = [
        event.stage.id
        for event in events
        if event.stage is not None
    ]

    assert stage_ids == [
        "CONTEXT_ASSEMBLY",
        "CLARIFICATION",
        "POSTING_ANALYSIS",
        "CONTRACT_VALIDATION",
        "RESULT_ASSEMBLY",
    ]
    assert updated_ids.count("POSTING_ANALYSIS") == 2
    assert provider.calls == ["clarification", "posting"]
    assert events[-1].type == "RESULT"


def test_cached_analysis_only_reruns_user_fit_stage() -> None:
    payload = valid_request()
    completed = valid_analysis_response()
    payload["sharedAnalysis"] = {
        "job": completed["job"],
        "competencyProposal": completed["competencyProposal"],
    }
    service = AnalysisService(
        Settings(analysis_provider="unconfigured", _env_file=None)
    )
    provider = OrchestrationProbeProvider()
    service._provider = provider
    request = AnalysisRequest.model_validate(payload)

    async def collect_events():
        return [event async for event in service.analyze_stream(request)]

    events = asyncio.run(collect_events())
    stage_ids = [stage.id for stage in events[0].stages]

    assert "SHARED_REUSE" in stage_ids
    assert "FIT_ANALYSIS" in stage_ids
    assert "CLARIFICATION" not in stage_ids
    assert "POSTING_ANALYSIS" not in stage_ids
    assert provider.calls == ["fit"]
    assert events[-1].result is not None
    assert events[-1].result.job == request.shared_analysis.job


def test_analysis_can_pause_for_one_clarification_question() -> None:
    response = AnalysisResponse.model_validate(
        {
            "status": "NEEDS_INPUT",
            "question": {
                "key": "target_role",
                "text": "이 공고에서 어느 직무로 지원하려고 하나요?",
                "reason": "프론트엔드와 백엔드 요구사항이 함께 포함되어 있습니다.",
                "options": [
                    {
                        "value": "backend",
                        "label": "백엔드",
                        "description": "Java와 Spring 중심으로 분석합니다.",
                    },
                    {
                        "value": "frontend",
                        "label": "프론트엔드",
                        "description": "TypeScript와 Next.js 중심으로 분석합니다.",
                    },
                ],
            },
        }
    )

    assert response.status == "NEEDS_INPUT"
    assert response.question is not None
    assert response.question.key == "target_role"


def test_competency_requires_scope_even_when_field_is_omitted() -> None:
    payload = valid_analysis_response()
    del payload["competencyProposal"]["competencies"][0]["scopeDefinition"]

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


def test_competency_schema_requires_scope_and_stage() -> None:
    schema = CompletedAnalysisResponse.model_json_schema(by_alias=True)
    competency_schema = schema["$defs"]["AnalyzedCompetency"]

    assert "scopeDefinition" in competency_schema["required"]
    assert "stage" in competency_schema["required"]
    assert "requiredLevel" in competency_schema["required"]
    assert "roadmapEligible" in competency_schema["required"]
    assert "verificationMethod" in competency_schema["properties"]


def test_assessment_retained_scores_only_accept_passed_core_dimensions() -> None:
    payload = {
        "sessionId": str(uuid4()),
        "competency": {
            "canonicalKey": "backend.java",
            "title": "Java",
            "domain": "BACKEND",
            "scopeDefinition": "Java 언어의 핵심 문법과 객체지향 설계를 적용한다.",
            "requiredLevel": 2,
            "levelDefinition": {},
            "assessmentBlueprint": {},
        },
        "target": {},
        "turns": [],
        "retainedScores": {"CONCEPT": 90, "SCENARIO": 80},
        "requiredQuestionKind": "CODE",
    }

    parsed = CompetencyAssessmentRequest.model_validate(payload)
    assert parsed.retained_scores == {"CONCEPT": 90, "SCENARIO": 80}

    payload["retainedScores"]["CODE"] = 59
    with pytest.raises(ValidationError):
        CompetencyAssessmentRequest.model_validate(payload)


def test_job_context_requires_track_and_structured_experience() -> None:
    payload = valid_analysis_response()
    del payload["job"]["primaryTrack"]

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)

    payload = valid_analysis_response()
    payload["job"]["experienceRequirement"] = {
        "type": "REQUIRED",
        "minimumMonths": 48,
        "maximumMonths": 24,
        "sourceText": "경력 2~4년",
    }

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


def test_requirement_must_reference_analyzed_competency() -> None:
    payload = valid_analysis_response()
    payload["competencyProposal"]["requirements"][0]["competencyRef"] = "missing"

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


def test_target_project_must_reference_analyzed_competency() -> None:
    payload = valid_analysis_response()
    payload["competencyProposal"]["targetProject"]["requiredCompetencyRefs"] = [
        "missing"
    ]

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


def test_qualitative_competency_cannot_be_a_project_requirement() -> None:
    payload = valid_analysis_response()
    competency = payload["competencyProposal"]["competencies"][0]
    competency["roadmapEligible"] = False
    competency["verificationMethod"] = None

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


class SuccessfulTestService:
    provider_name = "test"

    async def analyze(self, request) -> AnalysisResponse:
        return AnalysisResponse.model_validate(valid_analysis_response())

    async def analyze_stream(self, request):
        yield AnalysisStreamEvent(
            type="RUN_STARTED",
            run_id=request.analysis_job_id,
            sequence=1,
            occurred_at=datetime.now(UTC),
            stages=[
                AnalysisStageDefinition(
                    id="posting_analysis",
                    label="공고 분석",
                    role="공고 분석 에이전트",
                    message="공고 요구사항을 구조화하고 있어요.",
                    color="#ce82ff",
                )
            ],
        )
        yield AnalysisStreamEvent(
            type="RESULT",
            run_id=request.analysis_job_id,
            sequence=2,
            occurred_at=datetime.now(UTC),
            result=await self.analyze(request),
        )

    async def chat(self, request) -> ChatResponse:
        return ChatResponse(
            message="현재 경험부터 한 가지씩 확인해 볼게요.",
            intent="PROFILE_DISCOVERY",
            should_request_posting=False,
            suggested_actions=[],
        )

    async def verify_evidence(self, request) -> EvidenceVerificationResponse:
        return EvidenceVerificationResponse(
            verdict="NEEDS_WORK",
            confidence=0.7,
            summary="구현 근거를 조금 더 보완해 주세요.",
            strengths=["프로젝트 설명이 있습니다."],
            gaps=["실제 코드 근거가 없습니다."],
            next_actions=["핵심 커밋을 설명해 주세요."],
        )

    async def extract_career(self, request) -> CareerExtractionResponse:
        return CareerExtractionResponse(
            summary="프로젝트 경험에서 기술과 성과를 분리했습니다.",
            fragments=[
                CareerFragmentSuggestion(
                    kind="PROJECT",
                    title="게시판 API 개발",
                    description="Spring Boot와 PostgreSQL로 게시판 API를 구현했습니다.",
                    canonical_key="project.board-api",
                    detail={"stack": ["Spring Boot", "PostgreSQL"]},
                )
            ],
        )

    async def assess_competency(self, request) -> CompetencyAssessmentResponse:
        return CompetencyAssessmentResponse(
            answer_evaluation=None,
            next_question=AssessmentQuestion(
                kind="CONCEPT",
                prompt="HTTP 멱등성이 무엇인지 설명해 주세요.",
                code_snippet=None,
            ),
            session_summary="첫 번째 개념 문제를 준비했습니다.",
            strengths=[],
            gaps=[],
            next_actions=["질문에 근거를 포함해 답변하세요."],
        )


def test_configured_provider_contracts_serialize_successfully() -> None:
    app.dependency_overrides[get_analysis_service] = lambda: SuccessfulTestService()
    headers = {"X-JOBISS-AI-SECRET": "local-ai-secret"}

    analysis = client.post("/v1/analyses", json=valid_request(), headers=headers)
    analysis_stream = client.post(
        "/v1/analyses/stream",
        json=valid_request(),
        headers=headers,
    )
    chat = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversationId": str(uuid4()),
            "displayName": "테스터",
            "messages": [{"role": "USER", "content": "무엇부터 말할까요?"}],
            "career": {},
        },
    )
    evidence = client.post(
        "/v1/evidence-verifications",
        headers=headers,
        json={
            "evidence": {
                "id": str(uuid4()),
                "evidenceType": "PROJECT",
                "title": "API 프로젝트",
                "content": {"description": "REST API를 구현했습니다."},
            },
            "node": {
                "id": str(uuid4()),
                "title": "REST API",
                "domain": "BACKEND",
                "kind": "SKILL",
                "scopeDefinition": "REST API를 설계하고 구현한다.",
                "level": 2,
            },
        },
    )
    career = client.post(
        "/v1/career-extractions",
        headers=headers,
        json={
            "sourceId": str(uuid4()),
            "sourceType": "TEXT",
            "title": "게시판 프로젝트",
            "rawText": "Spring Boot와 PostgreSQL로 게시판 API를 구현했습니다.",
        },
    )
    assessment = client.post(
        "/v1/competency-assessments",
        headers=headers,
        json={
            "sessionId": str(uuid4()),
            "competency": {
                "canonicalKey": "shared.http-network",
                "title": "HTTP와 네트워크",
                "domain": "BACKEND",
                "scopeDefinition": "HTTP 요청과 응답의 동작을 설명하고 적용한다.",
                "requiredLevel": 2,
                "levelDefinition": {},
                "assessmentBlueprint": {},
            },
            "target": {
                "companyName": "Example",
                "roleTitle": "Backend Engineer",
                "primaryTrack": "BACKEND",
            },
            "turns": [],
            "retainedScores": {"SCENARIO": 82},
            "requiredQuestionKind": "CONCEPT",
        },
    )

    assert analysis.status_code == 200
    assert analysis.json()["competencyProposal"]["competencies"][0]["scopeDefinition"]
    assert analysis_stream.status_code == 200
    stream_events = [
        json.loads(line)
        for line in analysis_stream.text.splitlines()
        if line.strip()
    ]
    assert [event["type"] for event in stream_events] == ["RUN_STARTED", "RESULT"]
    assert stream_events[0]["stages"][0]["id"] == "posting_analysis"
    assert chat.status_code == 200
    assert chat.json()["intent"] == "PROFILE_DISCOVERY"
    assert evidence.status_code == 200
    assert evidence.json()["verdict"] == "NEEDS_WORK"
    assert career.status_code == 200
    assert career.json()["fragments"][0]["canonicalKey"] == "project.board-api"
    assert assessment.status_code == 200
    assert assessment.json()["nextQuestion"]["kind"] == "CONCEPT"
