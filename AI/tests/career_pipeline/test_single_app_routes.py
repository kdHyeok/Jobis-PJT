from fastapi.testclient import TestClient

from jobis_ai.career_pipeline.api_adapter import _error_detail
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.service import AnalysisPipelineFailure
from jobis_ai.v2bridge.app import app


def test_career_pipeline_is_served_by_the_single_v2bridge_app() -> None:
    client = TestClient(app)

    legacy = client.get(
        "/v1/capabilities",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
    )
    transitional = client.get(
        "/v1/capabilities",
        headers={"X-JOBIS-AI-SECRET": "local-ai-secret"},
    )

    assert legacy.status_code == 200
    assert transitional.status_code == 200
    assert transitional.json()["contractVersion"] == "jobis.ai.v3alpha1"
    assert any(
        item["name"] == "ANALYSIS_PIPELINE"
        for item in transitional.json()["capabilities"]
    )


def test_career_pipeline_rejects_missing_internal_secret() -> None:
    response = TestClient(app).get("/v1/capabilities")

    assert response.status_code == 401


def test_career_pipeline_hides_provider_name_from_public_error() -> None:
    detail = _error_detail(
        AnalysisPipelineFailure(
            code=ErrorCode.AI_PROVIDER_UNAVAILABLE,
            message="Codex CLI stopped while model gpt-example was running",
            retryable=True,
        ),
        None,
    )

    assert detail.code is ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert "Codex" not in detail.message
    assert "gpt-example" not in detail.message
    assert "분석 엔진" in detail.message


def test_career_pipeline_hides_graph_environment_name_from_public_error() -> None:
    detail = _error_detail(
        AnalysisPipelineFailure(
            code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
            message="CAPABILITY_GRAPH_URL is not configured",
            retryable=True,
        ),
        None,
    )

    assert "CAPABILITY_GRAPH_URL" not in detail.message
    assert "역량 지식 그래프" in detail.message
