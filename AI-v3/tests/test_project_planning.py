from __future__ import annotations

import copy
import json

import pytest

from jobis_ai_v3.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphNode,
    CapabilityNodeType,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    ProjectNecessity,
    VerificationMethod,
)
from jobis_ai_v3.contracts.normalization import CapabilityKind
from jobis_ai_v3.contracts.posting import StructuredPosting
from jobis_ai_v3.contracts.project_planning import ProjectPlanningRequest
from jobis_ai_v3.llm import StructuredGenerator
from jobis_ai_v3.project_planning import ProjectPlanningFailure, ProjectPlanningService


class StaticProvider:
    name = "scripted"
    model = "project-planner-fixture"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, **_kwargs) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def node(key: str, title: str) -> CapabilityGraphNode:
    return CapabilityGraphNode(
        canonical_key=key,
        technology_key="lang.java",
        display_name=title,
        node_type=CapabilityNodeType.PERFORMANCE,
        kind=CapabilityKind.PROGRAMMING_LANGUAGE,
        objective=f"Demonstrate {title} in executable Java code.",
        scope_definition=f"Atomic scope for {title}",
        verification_methods=[VerificationMethod.IMPLEMENT, VerificationMethod.TEST],
        confidence=GraphConfidence(
            band=GraphConfidenceBand.VERIFIED,
            reason="Reviewed test catalog entry.",
        ),
        review_status=GraphReviewStatus.APPROVED,
        version=1,
        source_ids=["source-java"],
    )


def request(structured_posting) -> ProjectPlanningRequest:
    return ProjectPlanningRequest(
        common_analysis_id="analysis-project-1",
        structured_posting=structured_posting,
        selected_position_id="pos-backend",
        graph_catalog=CapabilityGraphCatalog(
            graph_version="0.1.0-alpha.1",
            content_hash="sha256:" + "a" * 64,
            capabilities=[
                node("java.control-flow", "Java control flow"),
                node("java.classes-objects", "Java classes and objects"),
            ],
        ),
    )


def service(payload: dict) -> ProjectPlanningService:
    return ProjectPlanningService(
        StructuredGenerator(StaticProvider(payload), max_attempts=1)
    )


def payload(*, keys=None, unresolved=None, include_task=True) -> dict:
    capability_keys = (
        ["java.control-flow", "java.classes-objects"]
        if keys is None
        else keys
    )
    return {
        "title": "Game backend preparation project",
        "objective": "Build a runnable backend slice for the target company.",
        "domainContext": "Game backend",
        "tasks": ([{
            "title": "Implement the Java domain core",
            "objective": "Represent the domain with Java control flow and collaborating objects.",
            "acceptanceCriteria": [
                "The domain scenarios execute",
                "Automated tests cover success and failure paths",
            ],
            "capabilityKeys": capability_keys,
            "requirementIds": ["req-java"],
        }] if include_task else []),
        "unresolvedRequirementIds": unresolved or [],
    }


def test_broad_posting_requirement_becomes_multiple_atomic_targets(structured_posting) -> None:
    result = service(payload()).plan(request(structured_posting))

    assert len(result.tasks) == 1
    assert result.tasks[0].necessity is ProjectNecessity.REQUIRED
    assert result.tasks[0].capability_keys == [
        "java.control-flow",
        "java.classes-objects",
    ]
    assert result.tasks[0].task_key.startswith("task.draft.")


def test_responsibility_can_shape_task_without_becoming_a_learning_requirement(
    structured_posting,
) -> None:
    posting_payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    posting_payload["positions"][0]["responsibilities"] = [{
        "responsibility_id": "resp-api",
        "source_text": "Design and operate REST APIs",
        "atomic_text": "Design and operate REST APIs",
        "evidence_ids": ["seg-req"],
        "confidence": 0.95,
    }]
    posting = StructuredPosting.model_validate(posting_payload)
    draft = payload()
    draft["tasks"][0]["requirementIds"].append("resp-api")

    result = service(draft).plan(request(posting))

    assert result.tasks[0].requirement_ids == ["req-java", "resp-api"]


def test_responsibility_only_task_is_allowed_when_it_uses_approved_capabilities(
    structured_posting,
) -> None:
    posting_payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    posting_payload["positions"][0]["responsibilities"] = [{
        "responsibility_id": "resp-review",
        "source_text": "Participate in code reviews",
        "atomic_text": "Participate in code reviews",
        "evidence_ids": ["seg-req"],
        "confidence": 0.95,
    }]
    posting = StructuredPosting.model_validate(posting_payload)
    draft = payload()
    draft["tasks"].append({
        "title": "Run a code review workflow",
        "objective": "Review changes to the Java domain core before integration.",
        "acceptanceCriteria": [
            "A review checklist is committed",
            "At least one review finding is resolved",
        ],
        "capabilityKeys": ["java.classes-objects"],
        "requirementIds": ["resp-review"],
    })

    result = service(draft).plan(request(posting))

    assert result.tasks[1].requirement_ids == ["resp-review"]
    assert result.tasks[1].necessity is ProjectNecessity.REQUIRED


def test_unknown_atomic_key_is_rejected_instead_of_guessed(structured_posting) -> None:
    with pytest.raises(ProjectPlanningFailure, match="unknown capability keys"):
        service(payload(keys=["java.fabricated"])).plan(request(structured_posting))


def test_omitted_learning_requirement_must_be_explicitly_unresolved(structured_posting) -> None:
    with pytest.raises(ProjectPlanningFailure, match="omitted learnable requirements"):
        service(payload(include_task=False)).plan(request(structured_posting))


def test_catalog_gap_can_continue_as_reviewable_unresolved_requirement(structured_posting) -> None:
    result = service(
        payload(include_task=False, unresolved=["req-java"])
    ).plan(request(structured_posting))

    assert result.tasks == []
    assert result.unresolved_requirement_ids == ["req-java"]
    assert result.warnings[0].code == "ATOMIC_CAPABILITY_REVIEW_REQUIRED"


def test_project_task_and_unresolved_capability_mapping_are_preserved_together(
    structured_posting,
) -> None:
    result = service(payload(keys=[], unresolved=["req-java"])).plan(
        request(structured_posting)
    )

    assert result.tasks[0].requirement_ids == ["req-java"]
    assert result.tasks[0].capability_keys == []
    assert result.unresolved_requirement_ids == ["req-java"]
    assert result.warnings[-1].code == "ATOMIC_CAPABILITY_REVIEW_REQUIRED"


def test_responsibility_returned_as_unresolved_becomes_warning_not_pipeline_failure(
    structured_posting,
) -> None:
    posting_payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    posting_payload["positions"][0]["responsibilities"] = [{
        "responsibility_id": "resp-mobile",
        "source_text": "Build a WebView-based mobile game platform",
        "atomic_text": "Build a WebView-based mobile game platform",
        "evidence_ids": ["seg-req"],
        "confidence": 0.95,
    }]
    posting = StructuredPosting.model_validate(posting_payload)

    result = service(
        payload(unresolved=["resp-mobile"])
    ).plan(request(posting))

    assert result.unresolved_requirement_ids == []
    assert result.warnings[-1].code == (
        "PROJECT_CONTEXT_WAS_NOT_TREATED_AS_LEARNING_GAP"
    )
