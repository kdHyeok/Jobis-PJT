from __future__ import annotations

import asyncio

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
    CapabilityNormalizationRequest,
)


SECRET = "test-ai-secret-123"
SETTINGS = Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300)
HEADERS = {
    "X-JOBIS-AI-SECRET": SECRET,
    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
}


def request_for(structured_posting) -> CapabilityNormalizationRequest:
    payload = structured_posting.model_dump(mode="json")
    payload["positions"][0]["requirements"][0]["source_text"] = "Java"
    payload["positions"][0]["requirements"][0]["atomic_text"] = "Java"
    return CapabilityNormalizationRequest(
        common_analysis_id="analysis-normalize-api",
        structured_posting=type(structured_posting).model_validate(payload),
        selected_position_id="pos-backend",
        catalog=CapabilityCatalogSnapshot(
            catalog_version="catalog-api-1",
            entries=[
                CapabilityCatalogEntry(
                    canonical_key="lang.java",
                    display_name="Java",
                    kind=CapabilityKind.PROGRAMMING_LANGUAGE,
                    scope_definition="Java syntax, collections, exceptions, and OOP",
                    aliases=["자바"],
                    version=1,
                )
            ],
        ),
    )


def test_exact_normalization_endpoint_works_without_configured_llm(structured_posting) -> None:
    app = create_app(SETTINGS)

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/capabilities/normalize",
                headers=HEADERS,
                json=request_for(structured_posting).model_dump(mode="json", by_alias=True),
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()["items"][0]["decision"] == "AUTO_SELECTED"
    assert response.json()["items"][0]["selectedCanonicalKey"] == "lang.java"
    assert response.json()["audit"]["provider"] is None
