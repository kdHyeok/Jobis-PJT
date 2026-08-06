from __future__ import annotations

from datetime import UTC, datetime

import pytest
import httpx
from pydantic import ValidationError

from jobis_ai_v3.capability_graph import (
    CapabilityGraphContractError,
    HttpCapabilityGraphPort,
    InMemoryCapabilityGraphPort,
    closure_content_hash,
)
from jobis_ai_v3.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphNode,
    CapabilityGraphQueryRequest,
    CapabilityNodeType,
    CapabilityRelationType,
    GraphCondition,
    GraphConditionKind,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    GraphSnapshotScope,
    GraphSource,
    GraphSourceType,
    LearningLayer,
    VerificationMethod,
)
from jobis_ai_v3.contracts.normalization import CapabilityKind


NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
PLACEHOLDER_HASH = "sha256:" + "0" * 64
GRAPH_VERSION = "0.1.0-alpha.1"


def confidence() -> GraphConfidence:
    return GraphConfidence(
        band=GraphConfidenceBand.VERIFIED,
        reason="The fixture relation is explicitly reviewed.",
    )


def source() -> GraphSource:
    return GraphSource(
        source_id="source-roadmap-doc",
        title="Backend learning reference",
        uri="https://example.invalid/backend-reference",
        publisher="Example Foundation",
        source_type=GraphSourceType.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        evidence_summary="Atomic backend capability and prerequisite fixture.",
        snapshot_scope=GraphSnapshotScope.EXCERPT,
        content_hash="sha256:" + "a" * 64,
        license_name="CC BY 4.0",
    )


def node(
    key: str,
    technology_key: str,
    name: str,
    kind: CapabilityKind,
) -> CapabilityGraphNode:
    return CapabilityGraphNode(
        canonical_key=key,
        technology_key=technology_key,
        display_name=name,
        node_type=CapabilityNodeType.PERFORMANCE,
        kind=kind,
        objective=f"Perform the approved atomic learning objective for {name}.",
        scope_definition=f"Approved atomic learning scope for {name}",
        verification_methods=[VerificationMethod.IMPLEMENT],
        confidence=confidence(),
        review_status=GraphReviewStatus.APPROVED,
        version=1,
        source_ids=["source-roadmap-doc"],
    )


def edge(relation_id: str, source_key: str, target_key: str) -> CapabilityGraphEdge:
    return CapabilityGraphEdge(
        relation_id=relation_id,
        from_capability_key=source_key,
        to_capability_key=target_key,
        relation_type=CapabilityRelationType.HARD_PREREQUISITE,
        confidence=confidence(),
        review_status=GraphReviewStatus.APPROVED,
        version=1,
        source_ids=["source-roadmap-doc"],
        reason="The prerequisite is required to perform the target scope.",
    )


def closure(*, extra_edges=None) -> CapabilityGraphClosure:
    value = CapabilityGraphClosure(
        graph_version=GRAPH_VERSION,
        generated_at=NOW,
        content_hash=PLACEHOLDER_HASH,
        target_capability_keys=["spring.mvc-controller"],
        boundary_capability_keys=["java.classes-objects"],
        nodes=[
            node(
                "java.classes-objects",
                "lang.java",
                "Java class and object modelling",
                CapabilityKind.PROGRAMMING_LANGUAGE,
            ),
            node(
                "http.request-response",
                "protocol.http",
                "HTTP request and response interpretation",
                CapabilityKind.PROTOCOL,
            ),
            node(
                "spring.mvc-controller",
                "framework.spring-boot",
                "Spring MVC controller implementation",
                CapabilityKind.FRAMEWORK,
            ),
        ],
        edges=[
            edge(
                "rel-java-spring",
                "java.classes-objects",
                "spring.mvc-controller",
            ),
            edge(
                "rel-http-spring",
                "http.request-response",
                "spring.mvc-controller",
            ),
            *(extra_edges or []),
        ],
        sources=[source()],
        learning_order=[
            LearningLayer(depth=0, capability_keys=["http.request-response"]),
            LearningLayer(depth=1, capability_keys=["spring.mvc-controller"]),
        ],
    )
    return value.model_copy(update={"content_hash": closure_content_hash(value)})


def test_valid_approved_closure_can_be_read_through_port() -> None:
    graph = closure()
    port = InMemoryCapabilityGraphPort(graph)

    actual = port.get_learning_closure(CapabilityGraphQueryRequest(
        target_capability_keys=["spring.mvc-controller"],
        boundary_capability_keys=["java.classes-objects"],
        requested_graph_version=graph.graph_version,
    ))

    assert actual.graph_version == GRAPH_VERSION
    assert {item.from_capability_key for item in actual.edges} == {
        "java.classes-objects",
        "http.request-response",
    }


def test_http_port_uses_the_external_prerequisite_contract(monkeypatch) -> None:
    graph = closure()
    observed = {}

    def fake_post(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return httpx.Response(
            200,
            json=graph.model_dump(mode="json", by_alias=True),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    port = HttpCapabilityGraphPort(
        base_url="http://127.0.0.1:8600",
        shared_secret="local-capability-graph-secret",
        timeout_seconds=10.0,
    )

    actual = port.get_learning_closure(CapabilityGraphQueryRequest(
        target_capability_keys=["spring.mvc-controller"],
        boundary_capability_keys=["java.classes-objects"],
    ))

    assert actual.content_hash == graph.content_hash
    assert observed["url"] == "http://127.0.0.1:8600/v1/graph/prerequisites"
    assert observed["headers"]["X-JOBIS-CAPABILITY-GRAPH-CONTRACT"] == (
        "jobis.capability-graph.v1alpha1"
    )
    assert observed["json"]["boundaryCapabilityKeys"] == ["java.classes-objects"]


def test_http_port_reads_the_approved_atomic_catalog(monkeypatch) -> None:
    graph = closure()
    catalog = CapabilityGraphCatalog(
        graph_version=graph.graph_version,
        content_hash="sha256:" + "b" * 64,
        capabilities=graph.nodes,
    )
    observed = {}

    def fake_request(method, url, **kwargs):
        observed["method"] = method
        observed["url"] = url
        observed.update(kwargs)
        return httpx.Response(
            200,
            json=catalog.model_dump(mode="json", by_alias=True),
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    port = HttpCapabilityGraphPort(
        base_url="http://127.0.0.1:8600",
        shared_secret="local-capability-graph-secret",
        timeout_seconds=10.0,
    )

    actual = port.get_catalog()

    assert actual.graph_version == GRAPH_VERSION
    assert len(actual.capabilities) == 3
    assert observed["method"] == "GET"
    assert observed["url"] == "http://127.0.0.1:8600/v1/capabilities"


def test_tampered_content_hash_is_rejected() -> None:
    graph = closure().model_copy(update={"content_hash": "sha256:" + "f" * 64})

    with pytest.raises(CapabilityGraphContractError, match="hash mismatch"):
        InMemoryCapabilityGraphPort(graph).get_learning_closure(
            CapabilityGraphQueryRequest(
                target_capability_keys=["spring.mvc-controller"],
            )
        )


def test_wrong_requested_version_is_rejected() -> None:
    graph = closure()
    with pytest.raises(CapabilityGraphContractError, match="version"):
        InMemoryCapabilityGraphPort(graph).get_learning_closure(
            CapabilityGraphQueryRequest(
                target_capability_keys=["spring.mvc-controller"],
                requested_graph_version="0.0.1",
            )
        )


def test_hard_prerequisite_cycle_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        closure(extra_edges=[
            edge(
                "rel-spring-java",
                "spring.mvc-controller",
                "java.classes-objects",
            ),
        ])


def test_conditional_prerequisite_requires_explicit_condition() -> None:
    with pytest.raises(ValidationError, match="requires conditions"):
        CapabilityGraphEdge(
            relation_id="rel-language-choice",
            from_capability_key="java.classes-objects",
            to_capability_key="spring.mvc-controller",
            relation_type=CapabilityRelationType.CONDITIONAL_PREREQUISITE,
            confidence=confidence(),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=["source-roadmap-doc"],
            reason="Only required for the Java path.",
        )

    valid = CapabilityGraphEdge(
        relation_id="rel-language-choice",
        from_capability_key="java.classes-objects",
        to_capability_key="spring.mvc-controller",
        relation_type=CapabilityRelationType.CONDITIONAL_PREREQUISITE,
        conditions=[GraphCondition(
            kind=GraphConditionKind.LANGUAGE_CHOICE,
            key="selected-language",
            accepted_values=["lang.java"],
        )],
        confidence=confidence(),
        review_status=GraphReviewStatus.APPROVED,
        version=1,
        source_ids=["source-roadmap-doc"],
        reason="Required only for the selected Java path.",
    )
    assert valid.conditions[0].kind is GraphConditionKind.LANGUAGE_CHOICE
