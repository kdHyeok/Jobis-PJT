"""Deterministic local-only provider for the atomic assessment HTTP E2E check."""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException


CONTRACT_VERSION = "jobis.ai.v3alpha1"
SHARED_SECRET = os.getenv("V3_AI_SHARED_SECRET", "local-v3-integration-secret")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def authorize(secret: str | None, contract: str | None) -> None:
    if secret != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="invalid shared secret")
    if contract != CONTRACT_VERSION:
        raise HTTPException(status_code=409, detail="unsupported contract")


@app.post("/v1/assessments/questions")
def question(
    payload: dict,
    x_jobis_ai_secret: str | None = Header(default=None),
    x_jobis_ai_contract: str | None = Header(default=None),
) -> dict:
    authorize(x_jobis_ai_secret, x_jobis_ai_contract)
    ordinal = int(payload["ordinal"])
    capability = payload["capability"]
    methods = capability["verificationMethods"]
    method = methods[(ordinal - 1) % len(methods)]
    session_id = payload["sessionId"]
    return {
        "contractVersion": CONTRACT_VERSION,
        "questionId": f"local-e2e:{session_id}:{ordinal}",
        "sessionId": session_id,
        "capabilityKey": capability["canonicalKey"],
        "ordinal": ordinal,
        "method": method,
        "prompt": f"{capability['displayName']}의 승인된 범위 안에서 해결 방법을 작성하세요.",
        "answerInstructions": "코드 또는 설명과 판단 근거를 함께 작성하세요.",
        "coreCriteria": [
            "승인된 원자 범위의 핵심 개념을 적용한다.",
            "실패 조건과 판단 근거를 명시한다.",
        ],
        "futureExtensions": [],
        "audit": {
            "generatorVersion": "local-e2e-1",
            "provider": "deterministic-local",
            "model": "fixture",
            "attempts": 1,
            "durationMs": 1,
        },
    }


@app.post("/v1/assessments/grade")
def grade(
    payload: dict,
    x_jobis_ai_secret: str | None = Header(default=None),
    x_jobis_ai_contract: str | None = Header(default=None),
) -> dict:
    authorize(x_jobis_ai_secret, x_jobis_ai_contract)
    answer = payload["answer"]
    failed = "검토 필요" in answer or "NEEDS_REVIEW" in answer
    score = 50 if failed else 80
    return {
        "contractVersion": CONTRACT_VERSION,
        "questionId": payload["question"]["questionId"],
        "criterionGrades": [
            {"criterionIndex": 0, "score": score, "feedback": "기준 확인"},
            {"criterionIndex": 1, "score": score, "feedback": "기준 확인"},
        ],
        "score": score,
        "passed": not failed,
        "strengths": [] if failed else ["승인된 원자 범위 안에서 답했습니다."],
        "gaps": ["핵심 기준을 복습하세요."] if failed else [],
        "feedback": "로컬 HTTP E2E용 결정적 채점 결과입니다.",
        "scopeViolationDetected": False,
        "audit": {
            "generatorVersion": "local-e2e-1",
            "provider": "deterministic-local",
            "model": "fixture",
            "attempts": 1,
            "durationMs": 1,
        },
    }
