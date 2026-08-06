from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from jobis_ai_v3.api import create_app
from jobis_ai_v3.assessment import AtomicCapabilityAssessmentService, AssessmentFailure
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.assessment import (
    AtomicCapabilityAssessmentContext,
    CapabilityGradeRequest,
    CapabilityQuestionRequest,
    CompletedAssessmentTurn,
)
from jobis_ai_v3.contracts.capability_graph import VerificationMethod
from jobis_ai_v3.llm import StructuredGenerator


SECRET = "test-ai-secret-123"
HEADERS = {
    "X-JOBIS-AI-SECRET": SECRET,
    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
}


class StaticProvider:
    name = "scripted"
    model = "atomic-assessment-fixture"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def complete_json(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


def capability() -> AtomicCapabilityAssessmentContext:
    return AtomicCapabilityAssessmentContext(
        canonical_key="java.exceptions",
        technology_key="lang.java",
        display_name="예외 정의와 처리",
        objective="실패를 예외로 표현하고 적절한 계층에서 처리할 수 있다.",
        scope_definition="checked·unchecked 예외와 throw·catch·finally",
        excluded_scope=["Spring 트랜잭션", "분산 보상 트랜잭션"],
        verification_methods=[VerificationMethod.IMPLEMENT, VerificationMethod.DEBUG],
        graph_version="0.1.0-alpha.1",
        graph_node_version=1,
    )


def question_payload() -> dict:
    return {
        "prompt": "파일 형식 오류를 호출자에게 전달하는 Java 예외 처리 코드를 작성하세요.",
        "starterCode": "static int readPort(String value) { /* TODO */ }",
        "answerInstructions": "코드와 예외 선택 이유를 함께 작성하세요.",
        "coreCriteria": [
            "잘못된 입력을 명시적인 예외로 표현한다.",
            "예외를 삼키지 않고 호출자가 실패를 구분할 수 있게 한다.",
        ],
        "futureExtensions": ["Spring 전역 예외 처리와 연결해 볼 수 있다."],
    }


def test_question_stays_on_atomic_scope_and_uses_required_method() -> None:
    provider = StaticProvider([question_payload()])
    service = AtomicCapabilityAssessmentService(StructuredGenerator(provider))

    question = service.question(CapabilityQuestionRequest(
        session_id="session-1",
        capability=capability(),
        ordinal=1,
    ))

    assert question.method is VerificationMethod.IMPLEMENT
    assert question.capability_key == "java.exceptions"
    assert question.question_id.startswith("atomic-question:")
    system_prompt = provider.calls[0]["system_prompt"]
    user_payload = json.loads(provider.calls[0]["user_prompt"])
    assert "excludedScope" in user_payload["atomicCapability"]
    assert user_payload["atomicCapability"]["excludedScope"] == [
        "Spring 트랜잭션",
        "분산 보상 트랜잭션",
    ]
    assert "never test an excludedscope item" in system_prompt.casefold()


def test_next_question_cycles_methods_without_expanding_scope() -> None:
    provider = StaticProvider([question_payload()])
    service = AtomicCapabilityAssessmentService(StructuredGenerator(provider))
    prior = CompletedAssessmentTurn(
        question_id="question-1",
        ordinal=1,
        method=VerificationMethod.IMPLEMENT,
        prompt="예외를 구현하세요.",
        answer="코드 답변",
        score=72,
        passed=True,
    )

    question = service.question(CapabilityQuestionRequest(
        session_id="session-1",
        capability=capability(),
        completed_turns=[prior],
        ordinal=2,
    ))

    assert question.method is VerificationMethod.DEBUG
    assert json.loads(provider.calls[0]["user_prompt"])["completedTurns"][0]["score"] == 72


def test_grade_and_pass_are_computed_from_all_core_criteria() -> None:
    question_provider = StaticProvider([question_payload()])
    question = AtomicCapabilityAssessmentService(
        StructuredGenerator(question_provider)
    ).question(CapabilityQuestionRequest(
        session_id="session-1",
        capability=capability(),
        ordinal=1,
    ))
    grade_provider = StaticProvider([{
        "criterionGrades": [
            {"criterionIndex": 0, "score": 80, "feedback": "명시적 예외가 적절합니다."},
            {"criterionIndex": 1, "score": 60, "feedback": "원인 예외 보존은 보완할 수 있습니다."},
        ],
        "strengths": ["실패 조건을 코드로 분리했습니다."],
        "gaps": ["원인 예외를 함께 전달하지 않았습니다."],
        "feedback": "범위 안의 핵심은 통과했고 원인 보존을 복습하세요.",
        "scopeViolationDetected": False,
    }])
    service = AtomicCapabilityAssessmentService(StructuredGenerator(grade_provider))

    grade = service.grade(CapabilityGradeRequest(
        capability=capability(),
        question=question,
        answer="IllegalArgumentException을 던지는 Java 코드",
    ))

    assert grade.score == 70
    assert grade.passed is True


def test_scope_violating_question_cannot_pass() -> None:
    question_provider = StaticProvider([question_payload()])
    question = AtomicCapabilityAssessmentService(
        StructuredGenerator(question_provider)
    ).question(CapabilityQuestionRequest(
        session_id="session-1",
        capability=capability(),
        ordinal=1,
    ))
    provider = StaticProvider([{
        "criterionGrades": [
            {"criterionIndex": 0, "score": 100, "feedback": "충족"},
            {"criterionIndex": 1, "score": 100, "feedback": "충족"},
        ],
        "strengths": [],
        "gaps": ["질문이 Spring 트랜잭션을 필수로 요구했습니다."],
        "feedback": "원자 범위를 벗어난 질문이므로 통과 판정에 사용할 수 없습니다.",
        "scopeViolationDetected": True,
    }])

    grade = AtomicCapabilityAssessmentService(StructuredGenerator(provider)).grade(
        CapabilityGradeRequest(
            capability=capability(),
            question=question,
            answer="완전한 답변",
        )
    )

    assert grade.score == 100
    assert grade.passed is False


def test_missing_criterion_grade_is_rejected() -> None:
    question_provider = StaticProvider([question_payload()])
    question = AtomicCapabilityAssessmentService(
        StructuredGenerator(question_provider)
    ).question(CapabilityQuestionRequest(
        session_id="session-1",
        capability=capability(),
        ordinal=1,
    ))
    provider = StaticProvider([{
        "criterionGrades": [
            {"criterionIndex": 0, "score": 80, "feedback": "충족"},
            {"criterionIndex": 2, "score": 80, "feedback": "잘못된 인덱스"},
        ],
        "strengths": [],
        "gaps": [],
        "feedback": "불완전한 채점",
        "scopeViolationDetected": False,
    }])

    with pytest.raises(AssessmentFailure, match="every core criterion"):
        AtomicCapabilityAssessmentService(StructuredGenerator(provider)).grade(
            CapabilityGradeRequest(
                capability=capability(),
                question=question,
                answer="답변",
            )
        )


def test_assessment_question_and_grade_endpoints_use_the_published_contract() -> None:
    provider = StaticProvider([
        question_payload(),
        {
            "criterionGrades": [
                {"criterionIndex": 0, "score": 85, "feedback": "충족"},
                {"criterionIndex": 1, "score": 75, "feedback": "충족"},
            ],
            "strengths": ["실패 조건을 구분했습니다."],
            "gaps": [],
            "feedback": "원자 범위 안의 기준을 충족했습니다.",
            "scopeViolationDetected": False,
        },
    ])
    service = AtomicCapabilityAssessmentService(
        StructuredGenerator(provider, max_attempts=1)
    )
    app = create_app(
        Settings(
            environment="test",
            shared_secret=SECRET,
            host="127.0.0.1",
            port=8500,
        ),
        assessment_service=service,
    )

    async def send() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            question_response = await client.post(
                "/v1/assessments/questions",
                headers=HEADERS,
                json=CapabilityQuestionRequest(
                    session_id="session-api-1",
                    capability=capability(),
                    ordinal=1,
                ).model_dump(mode="json", by_alias=True),
            )
            question = question_response.json()
            grade_response = await client.post(
                "/v1/assessments/grade",
                headers=HEADERS,
                json={
                    "capability": capability().model_dump(mode="json", by_alias=True),
                    "question": question,
                    "answer": "잘못된 입력이면 IllegalArgumentException을 던집니다.",
                },
            )
            return question_response, grade_response

    question_response, grade_response = asyncio.run(send())

    assert question_response.status_code == 200
    assert question_response.json()["contractVersion"] == "jobis.ai.v3alpha1"
    assert grade_response.status_code == 200
    assert grade_response.json()["questionId"] == question_response.json()["questionId"]
    assert grade_response.json()["score"] == 80
    assert grade_response.json()["passed"] is True
