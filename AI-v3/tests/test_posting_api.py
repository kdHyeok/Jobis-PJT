from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.posting import PostingInterpretationRequest
from jobis_ai_v3.contracts.source import (
    SourceAcquisitionRequest,
    SourceEntryPoint,
    SourceInputType,
    SourceVerificationRequest,
    VerifiedBy,
)
from jobis_ai_v3.source import SourceAcquisitionService
from jobis_ai_v3.interpretation import PostingInterpretationService
from jobis_ai_v3.llm import StructuredGenerator


SECRET = "test-ai-secret-123"
SETTINGS = Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300)
HEADERS = {
    "X-JOBIS-AI-SECRET": SECRET,
    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
}


class StaticProvider:
    name = "scripted"
    model = "api-smoke"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, **_kwargs) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def posting_request() -> PostingInterpretationRequest:
    service = SourceAcquisitionService(settings=SETTINGS)
    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        text="백엔드 개발자 모집. 신입.",
    ))
    verified = service.verify(SourceVerificationRequest(
        source_document=source,
        verified_text=source.raw_text,
        verified_by=VerifiedBy.USER,
    ))
    return PostingInterpretationRequest(
        source_document=verified.source_document,
        verified_snapshot=verified.verified_snapshot,
        as_of_date=date(2026, 8, 4),
    )


def test_unconfigured_interpreter_returns_explicit_error_contract() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(SETTINGS))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/postings/structure",
                headers=HEADERS,
                json=posting_request().model_dump(mode="json", by_alias=True),
            )

    response = asyncio.run(send())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"
    assert response.json()["error"]["retryable"] is False


def test_structure_endpoint_returns_evidence_linked_positions() -> None:
    request = posting_request()
    evidence = request.verified_snapshot.evidence_segments[0].segment_id
    experience_evidence = request.verified_snapshot.evidence_segments[-1].segment_id
    draft = {
        "company": None,
        "postingTitle": "백엔드 개발자 모집",
        "postingTitleEvidenceIds": [evidence],
        "positions": [{
            "positionKey": "backend",
            "sourceTitle": "백엔드 개발자",
            "role": {
                "family": "SOFTWARE_ENGINEERING",
                "specialization": "WEB_BACKEND",
                "canonicalRoleIdCandidate": "role.web_backend",
                "confidence": 0.98,
                "evidenceIds": [evidence],
            },
            "experience": {
                "kind": "NEW_GRADUATE",
                "minMonths": None,
                "maxMonths": None,
                "experiencedMinMonths": None,
                "confidence": 0.98,
                "evidenceIds": [experience_evidence],
            },
            "responsibilities": [],
            "requirements": [],
        }],
        "sharedConditions": [],
        "applicationDeadline": None,
        "applicationDeadlineEvidenceIds": [],
    }
    posting_service = PostingInterpretationService(
        StructuredGenerator(StaticProvider(draft), max_attempts=1)
    )

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(SETTINGS, posting_service=posting_service))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/postings/structure",
                headers=HEADERS,
                json=request.model_dump(mode="json", by_alias=True),
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()["positions"][0]["role"]["specialization"] == "WEB_BACKEND"
