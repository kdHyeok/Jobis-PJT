from fastapi.testclient import TestClient

from jobis_ai.career_pipeline.api_adapter import _error_detail
from jobis_ai.career_pipeline.cancellation import AnalysisCancelled
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
        item["name"] == "ANALYSIS_PIPELINE" and item["available"] is True
        for item in transitional.json()["capabilities"]
    )
    graph = next(
        item
        for item in transitional.json()["capabilities"]
        if item["name"] == "CAPABILITY_GRAPH"
    )
    assert graph["available"] is True
    assert graph.get("reason") is None


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


def test_career_pipeline_explains_non_actionable_recruitment_page() -> None:
    detail = _error_detail(
        AnalysisPipelineFailure(
            code=ErrorCode.ROLE_RESOLUTION_REQUIRED,
            message="positions=[]",
            retryable=False,
        ),
        None,
    )

    assert detail.code is ErrorCode.ROLE_RESOLUTION_REQUIRED
    assert detail.retryable is False
    assert "상세 공고 URL" in detail.message
    assert "positions" not in detail.message


def test_career_pipeline_preserves_expected_cancellation_contract() -> None:
    detail = _error_detail(AnalysisCancelled("analysis was cancelled by the user"), None)

    assert detail.code is ErrorCode.ANALYSIS_CANCELLED
    assert detail.retryable is False
    assert detail.message == "사용자가 커리어 분석을 취소했습니다."
    assert "cancelled" not in detail.message
