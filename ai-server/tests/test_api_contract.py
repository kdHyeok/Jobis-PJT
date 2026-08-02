from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app, get_analysis_service
from app.models import (
    AnalysisResponse,
    CareerExtractionResponse,
    CareerFragmentSuggestion,
    ChatResponse,
    CompletedAnalysisResponse,
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
            "parsedData": {},
        },
        "evaluation": {
            "verdict": "STRENGTHEN_THEN_APPLY",
            "summary": "보완 후 지원할 수 있습니다.",
            "reasons": ["필수 기술 경험이 필요합니다."],
        },
        "changeProposal": {
            "baseGraphVersion": 1,
            "nodes": [
                {
                    "ref": "java",
                    "action": "CREATE",
                    "canonicalKey": "skill.java",
                    "title": "Java",
                    "domain": "BACKEND",
                    "kind": "SKILL",
                    "scopeDefinition": "Java로 서버 로직을 구현한다.",
                    "level": 2,
                    "rank": 1,
                    "detail": {},
                }
            ],
            "edges": [],
            "requirements": [
                {
                    "nodeRef": "java",
                    "kind": "REQUIRED",
                    "sourceText": "Java 경험",
                    "confidence": 0.9,
                }
            ],
        },
    }


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


def test_create_node_requires_scope_even_when_field_is_omitted() -> None:
    payload = valid_analysis_response()
    del payload["changeProposal"]["nodes"][0]["scopeDefinition"]

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


def test_create_node_schema_requires_scope_definition() -> None:
    schema = CompletedAnalysisResponse.model_json_schema(by_alias=True)
    node_items = schema["$defs"]["ChangeProposal"]["properties"]["nodes"]["items"]
    create_ref = next(
        item["$ref"]
        for item in node_items["anyOf"]
        if item["$ref"].endswith("/CreateProposedNode")
    )
    create_schema = schema["$defs"][create_ref.rsplit("/", 1)[-1]]

    assert "scopeDefinition" in create_schema["required"]
    assert create_schema["properties"]["action"]["const"] == "CREATE"


def test_reuse_node_schema_requires_existing_node_id() -> None:
    schema = CompletedAnalysisResponse.model_json_schema(by_alias=True)
    node_items = schema["$defs"]["ChangeProposal"]["properties"]["nodes"]["items"]
    reuse_ref = next(
        item["$ref"]
        for item in node_items["anyOf"]
        if item["$ref"].endswith("/ReuseProposedNode")
    )
    reuse_schema = schema["$defs"][reuse_ref.rsplit("/", 1)[-1]]

    assert "existingNodeId" in reuse_schema["required"]
    assert reuse_schema["properties"]["action"]["const"] == "REUSE"


def test_edge_kind_is_limited_to_server_supported_values() -> None:
    payload = valid_analysis_response()
    payload["changeProposal"]["edges"] = [
        {"fromRef": "java", "toRef": "java", "edgeKind": "LEADS_TO"}
    ]

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(payload)


class SuccessfulTestService:
    provider_name = "test"

    async def analyze(self, request) -> AnalysisResponse:
        return AnalysisResponse.model_validate(valid_analysis_response())

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


def test_configured_provider_contracts_serialize_successfully() -> None:
    app.dependency_overrides[get_analysis_service] = lambda: SuccessfulTestService()
    headers = {"X-JOBISS-AI-SECRET": "local-ai-secret"}

    analysis = client.post("/v1/analyses", json=valid_request(), headers=headers)
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

    assert analysis.status_code == 200
    assert analysis.json()["changeProposal"]["nodes"][0]["scopeDefinition"]
    assert chat.status_code == 200
    assert chat.json()["intent"] == "PROFILE_DISCOVERY"
    assert evidence.status_code == 200
    assert evidence.json()["verdict"] == "NEEDS_WORK"
    assert career.status_code == 200
    assert career.json()["fragments"][0]["canonicalKey"] == "project.board-api"
