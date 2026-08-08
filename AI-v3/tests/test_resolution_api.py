from __future__ import annotations

import asyncio

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings


SECRET = "test-ai-secret-123"
SETTINGS = Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300)


def test_resolution_endpoint_uses_internal_contract(structured_posting) -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(SETTINGS))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/postings/resolve",
                headers={
                    "X-JOBIS-AI-SECRET": SECRET,
                    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
                },
                json={
                    "structuredPosting": structured_posting.model_dump(mode="json", by_alias=True),
                    "answers": [],
                },
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()["status"] == "READY_FOR_ANALYSIS"
    assert response.json()["selectedPositionId"] == "pos-backend"
