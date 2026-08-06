from __future__ import annotations

import asyncio

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings


SECRET = "test-ai-secret-123"


def app():
    app = create_app(Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300))
    return app


def get(path: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def auth_headers() -> dict[str, str]:
    return {
        "X-JOBIS-AI-SECRET": SECRET,
        "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
        "X-Request-ID": "request-1",
    }


def test_health_is_public() -> None:
    response = get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.headers["X-Request-ID"].startswith("request-")
    assert response.headers["X-Trace-ID"].startswith("trace-")


def test_internal_endpoint_requires_secret() -> None:
    response = get("/v1/meta", headers={"X-Request-ID": "request-1"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED_AI_CLIENT"
    assert response.json()["error"]["requestId"] == "request-1"


def test_capabilities_do_not_claim_unimplemented_features() -> None:
    response = get("/v1/capabilities", headers=auth_headers())

    assert response.status_code == 200
    capabilities = {item["name"]: item["available"] for item in response.json()["capabilities"]}
    assert capabilities["CONTRACTS"] is True
    assert capabilities["SOURCE_ACQUISITION"] is True
    assert capabilities["FIT_ANALYSIS"] is False


def test_schema_endpoint_returns_camel_case_contract() -> None:
    response = get("/v1/schemas/source-document", headers=auth_headers())

    assert response.status_code == 200
    assert "sourceDocumentId" in response.json()["properties"]
    assert response.json()["additionalProperties"] is False


def test_unknown_schema_uses_error_contract() -> None:
    response = get("/v1/schemas/no-such-schema", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_AVAILABLE"


def test_unsupported_contract_version_is_rejected() -> None:
    headers = auth_headers()
    headers["X-JOBIS-AI-CONTRACT"] = "jobis.ai.v2"

    response = get("/v1/meta", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "UNSUPPORTED_CONTRACT_VERSION"
