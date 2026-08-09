from __future__ import annotations

from fastapi.testclient import TestClient

from jobis_ai.capability_graph_server.app import app
from jobis_ai.career_pipeline.capability_graph.port import validate_closure_hash
from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
)

SECRET = {"X-JOBIS-GRAPH-SECRET": "local-capability-graph-secret"}
client = TestClient(app)


def test_health_reports_graph_version() -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "jobis-capability-graph"
    assert body["graphVersion"] == "0.2.0-alpha.1"
    assert body["capabilityCount"] == 69
    assert body["projectTaskCount"] == 12
    assert body["taskRequirementCount"] == 26


def test_v1_requires_shared_secret() -> None:
    assert client.get("/v1/capabilities").status_code == 401
    assert client.get("/v1/capabilities", headers=SECRET).status_code == 200


def test_catalog_is_a_valid_contract() -> None:
    catalog = CapabilityGraphCatalog.model_validate(
        client.get("/v1/capabilities", headers=SECRET).json()
    )
    assert {item.canonical_key for item in catalog.capabilities} >= {
        "java.classes-objects",
        "spring.mvc-rest-controller",
        "http.request-response",
    }
    assert all(not item.canonical_key.startswith("task.") for item in catalog.capabilities)


def test_prerequisite_closure_is_valid_and_boundary_stops_traversal() -> None:
    response = client.post(
        "/v1/graph/prerequisites",
        headers=SECRET,
        json={
            "targetCapabilityKeys": ["spring.mvc-rest-controller"],
            "boundaryCapabilityKeys": ["java.classes-objects"],
        },
    )
    assert response.status_code == 200
    closure = CapabilityGraphClosure.model_validate(response.json())
    validate_closure_hash(closure)

    keys = {node.canonical_key for node in closure.nodes}
    assert "spring.mvc-rest-controller" in keys
    assert "http.request-response" in keys
    assert "java.classes-objects" in keys  # boundary 노드 자체는 포함
    ordered = [key for layer in closure.learning_order for key in layer.capability_keys]
    assert "java.classes-objects" not in ordered  # 이미 검증된 역량은 학습 순서에서 제외
    assert ordered.index("spring.boot-configuration") < ordered.index(
        "spring.mvc-rest-controller"
    )


def test_unknown_target_is_rejected_with_error_envelope() -> None:
    response = client.post(
        "/v1/graph/prerequisites",
        headers=SECRET,
        json={"targetCapabilityKeys": ["no.such-capability"]},
    )
    assert response.status_code == 400
    assert "no.such-capability" in response.json()["error"]["message"]
