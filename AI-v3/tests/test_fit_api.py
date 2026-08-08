from __future__ import annotations

import asyncio
import json

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.fit import FitAnalysisRequest, UserEvidenceBundle
from jobis_ai_v3.contracts.resolution import ExperienceTrack
from jobis_ai_v3.fit import FitAnalysisService
from jobis_ai_v3.llm import StructuredGenerator


SECRET = "test-ai-secret-123"
SETTINGS = Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300)
HEADERS = {
    "X-JOBIS-AI-SECRET": SECRET,
    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
}


class StaticProvider:
    name = "scripted"
    model = "fit-api"

    def complete_json(self, **_kwargs) -> str:
        return json.dumps({
            "requirementMatches": [{
                "requirementId": "req-java",
                "competencyCandidates": [],
                "formalFactCandidates": [],
                "confidence": 0.9,
                "reason": "No supplied user evidence can be linked.",
            }]
        })


def request_for(structured_posting) -> FitAnalysisRequest:
    return FitAnalysisRequest(
        common_analysis_id="analysis-api-1",
        structured_posting=structured_posting,
        selected_position_id="pos-backend",
        selected_experience_track=ExperienceTrack.NEW_GRADUATE,
        user_evidence=UserEvidenceBundle(
            evidence_set_id="evidence-api-1",
            revision=1,
        ),
        skip_remaining_evidence_questions=True,
    )


def test_fit_endpoint_returns_unknown_instead_of_false_failure(structured_posting) -> None:
    fit_service = FitAnalysisService(
        StructuredGenerator(StaticProvider(), max_attempts=1)
    )
    app = create_app(SETTINGS, fit_service=fit_service)

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/fit/analyze",
                headers=HEADERS,
                json=request_for(structured_posting).model_dump(mode="json", by_alias=True),
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assessment = response.json()["assessment"]["requirementAssessments"][0]
    assert assessment["status"] == "UNKNOWN"
    assert assessment["includedInDenominator"] is False


def test_unconfigured_fit_endpoint_returns_explicit_provider_error(structured_posting) -> None:
    app = create_app(SETTINGS)

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/fit/analyze",
                headers=HEADERS,
                json=request_for(structured_posting).model_dump(mode="json", by_alias=True),
            )

    response = asyncio.run(send())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"
