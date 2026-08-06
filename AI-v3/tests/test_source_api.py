from __future__ import annotations

import asyncio

import httpx

from jobis_ai_v3.api import create_app
from jobis_ai_v3.config import Settings


SECRET = "test-ai-secret-123"
SETTINGS = Settings(environment="test", shared_secret=SECRET, host="127.0.0.1", port=8300)
HEADERS = {
    "X-JOBIS-AI-SECRET": SECRET,
    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
    "X-Request-ID": "request-source-api",
}


def post(path: str, payload: dict) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(SETTINGS))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, json=payload, headers=HEADERS)

    return asyncio.run(send())


def test_acquire_and_verify_use_public_contracts() -> None:
    acquired = post("/v1/sources/acquire", {
        "inputType": "TEXT",
        "entryPoint": "CHAT",
        "text": "백엔드 개발자 채용\n지원 자격: 신입\nJava 경험 필수",
    })

    assert acquired.status_code == 200
    source = acquired.json()
    assert source["status"] == "AWAITING_VERIFICATION"

    verified = post(f"/v1/sources/{source['sourceDocumentId']}/verify", {
        "sourceDocument": source,
        "verifiedText": source["rawText"],
        "corrections": [],
        "verifiedBy": "USER",
    })

    assert verified.status_code == 200
    assert verified.json()["sourceDocument"]["status"] == "VERIFIED"
    assert verified.json()["verifiedSnapshot"]["sourceDocumentId"] == source["sourceDocumentId"]


def test_verify_rejects_mismatched_path_id_with_error_envelope() -> None:
    acquired = post("/v1/sources/acquire", {
        "inputType": "TEXT",
        "entryPoint": "POSTINGS_PAGE",
        "text": "백엔드 개발자 채용 공고",
    }).json()

    response = post("/v1/sources/src-other/verify", {
        "sourceDocument": acquired,
        "verifiedText": acquired["rawText"],
        "corrections": [],
        "verifiedBy": "USER",
    })

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTRACT_VALIDATION_FAILED"

