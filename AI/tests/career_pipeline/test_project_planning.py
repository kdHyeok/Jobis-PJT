from __future__ import annotations

import copy
import json

import pytest

from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphNode,
    CapabilityNodeType,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    ProjectNecessity,
    VerificationMethod,
)
from jobis_ai.career_pipeline.contracts.normalization import CapabilityKind
from jobis_ai.career_pipeline.contracts.posting import (
    RequirementCategory,
    StructuredPosting,
)
from jobis_ai.career_pipeline.contracts.project_planning import ProjectPlanningRequest
from jobis_ai.career_pipeline.llm import StructuredGenerator
from jobis_ai.career_pipeline.project_planning import ProjectPlanningFailure, ProjectPlanningService


class StaticProvider:
    name = "scripted"
    model = "project-planner-fixture"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, **_kwargs) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


class SequenceProvider:
    name = "scripted"
    model = "project-planner-fixture"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def complete_json(self, **kwargs) -> str:
        self.prompts.append(kwargs["user_prompt"])
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


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


def sequence_service(payloads: list[dict]) -> tuple[ProjectPlanningService, SequenceProvider]:
    provider = SequenceProvider(payloads)
    return (
        ProjectPlanningService(StructuredGenerator(provider, max_attempts=1)),
        provider,
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
            "taskKey": "task.domain-core",
            "title": "Implement the Java domain core",
            "objective": "Represent the domain with Java control flow and collaborating objects.",
            "acceptanceCriteria": [
                "The domain scenarios execute",
                "Automated tests cover success and failure paths",
            ],
            "capabilityKeys": capability_keys,
            "requirementIds": ["req-java"],
            "dependsOnTaskKeys": [],
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


def test_contract_invalid_draft_is_reprompted_once_with_valid_requirement_ids(
    structured_posting,
) -> None:
    invalid = payload()
    invalid["tasks"][0]["requirementIds"] = []
    planner, provider = sequence_service([invalid, payload()])

    result = planner.plan(request(structured_posting))

    assert len(provider.prompts) == 2
    assert "CONTRACT_REPAIR_REQUEST" in provider.prompts[1]
    assert '"req-java"' in provider.prompts[1]
    assert result.tasks[0].requirement_ids == ["req-java"]
    assert result.audit.generation_attempts == 2


def test_contract_invalid_draft_fails_after_one_bounded_repair_attempt(
    structured_posting,
) -> None:
    invalid = payload()
    invalid["tasks"][0]["requirementIds"] = []
    planner, provider = sequence_service([invalid, invalid])

    with pytest.raises(ProjectPlanningFailure, match="violated the contract") as caught:
        planner.plan(request(structured_posting))

    assert caught.value.retryable is True
    assert len(provider.prompts) == 2


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
        "taskKey": "task.review-workflow",
        "title": "Run a code review workflow",
        "objective": "Review changes to the Java domain core before integration.",
        "acceptanceCriteria": [
            "A review checklist is committed",
            "At least one review finding is resolved",
        ],
        "capabilityKeys": ["java.classes-objects"],
        "requirementIds": ["resp-review"],
        "dependsOnTaskKeys": ["task.domain-core"],
    })

    result = service(draft).plan(request(posting))

    assert result.tasks[1].requirement_ids == ["resp-review"]
    assert result.tasks[1].necessity is ProjectNecessity.REQUIRED
    assert result.tasks[1].depends_on_task_keys == [result.tasks[0].task_key]


def test_project_task_dependencies_must_reference_known_tasks(structured_posting) -> None:
    draft = payload()
    draft["tasks"][0]["dependsOnTaskKeys"] = ["task.missing"]

    with pytest.raises(ProjectPlanningFailure, match="unknown task keys"):
        service(draft).plan(request(structured_posting))


def test_project_task_dependencies_must_be_acyclic(structured_posting) -> None:
    draft = payload()
    draft["tasks"].append({
        "taskKey": "task.delivery",
        "title": "Deliver the service",
        "objective": "Package the completed service for review.",
        "acceptanceCriteria": ["The service starts", "The runbook is complete"],
        "capabilityKeys": ["java.classes-objects"],
        "requirementIds": ["req-java"],
        "dependsOnTaskKeys": ["task.domain-core"],
    })
    draft["tasks"][0]["dependsOnTaskKeys"] = ["task.delivery"]

    with pytest.raises(ProjectPlanningFailure, match="acyclic"):
        service(draft).plan(request(structured_posting))


def test_unknown_atomic_key_is_rejected_instead_of_guessed(structured_posting) -> None:
    with pytest.raises(ProjectPlanningFailure, match="unknown capability keys"):
        service(payload(keys=["java.fabricated"])).plan(request(structured_posting))


def test_omitted_learning_requirement_is_semantically_repaired_once(
    structured_posting,
) -> None:
    planner, provider = sequence_service([
        payload(include_task=False),
        payload(include_task=False, unresolved=["req-java"]),
    ])

    result = planner.plan(request(structured_posting))

    assert len(provider.prompts) == 2
    assert "SEMANTIC_REPAIR_REQUEST" in provider.prompts[1]
    assert "omitted learnable requirements" in provider.prompts[1]
    assert result.unresolved_requirement_ids == ["req-java"]
    assert result.audit.generation_attempts == 2


def test_semantic_repair_defaults_a_second_omission_to_unresolved(
    structured_posting,
) -> None:
    planner, provider = sequence_service([
        payload(include_task=False),
        payload(include_task=False),
    ])

    result = planner.plan(request(structured_posting))

    assert len(provider.prompts) == 2
    assert "SEMANTIC_REPAIR_REQUEST" in provider.prompts[1]
    assert result.unresolved_requirement_ids == ["req-java"]


def test_language_and_certification_are_project_context_not_project_learning(
    structured_posting,
) -> None:
    posting_payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    posting_payload["positions"][0]["requirements"].extend([
        {
            "requirement_id": "req-english",
            "source_text": "해외 인력과 영어 회화 가능",
            "atomic_text": "해외 인력과 커뮤니케이션 가능한 수준의 영어 회화 역량 보유",
            "obligation": "PREFERRED",
            "category": RequirementCategory.TECHNICAL_CAPABILITY.value,
            "applies_to_position_ids": ["pos-backend"],
            "evidence_ids": ["seg-req"],
            "confidence": 0.9,
            "normalization_status": "PENDING",
            "warnings": [],
        },
        {
            "requirement_id": "req-license",
            "source_text": "정보처리기사 우대",
            "atomic_text": "정보처리기사 보유",
            "obligation": "PREFERRED",
            "category": RequirementCategory.CERTIFICATION.value,
            "applies_to_position_ids": ["pos-backend"],
            "evidence_ids": ["seg-req"],
            "confidence": 0.9,
            "normalization_status": "PENDING",
            "warnings": [],
        },
    ])
    posting = StructuredPosting.model_validate(posting_payload)
    planner, provider = sequence_service([payload()])

    result = planner.plan(request(posting))

    prompt_payload = json.loads(provider.prompts[0])
    assert {item["requirementId"] for item in prompt_payload["learnableRequirements"]} == {
        "req-java"
    }
    assert {item["contextId"] for item in prompt_payload["projectContext"]} >= {
        "req-english",
        "req-license",
    }
    assert result.tasks[0].requirement_ids == ["req-java"]


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
