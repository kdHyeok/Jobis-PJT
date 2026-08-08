from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai_v3.contracts.roadmap import (
    RoadmapAction,
    RoadmapAudit,
    RoadmapOperation,
    RoadmapProposal,
    RoadmapRelation,
    RoadmapRelationType,
)


def operation(key: str, operation_id: str) -> RoadmapOperation:
    return RoadmapOperation(
        operation_id=operation_id,
        action=RoadmapAction.CREATE_NODE,
        canonical_key=key,
        title=key,
        scope_definition=f"Approved scope for {key}",
        section_key="section.backend",
        reason="공고 필수 역량",
    )


def audit() -> RoadmapAudit:
    return RoadmapAudit(
        composer_version="roadmap-composer-test",
        provider="scripted",
        model="fixture",
        generation_attempts=1,
        generation_duration_ms=1,
        graph_content_hash="sha256:" + "a" * 64,
    )


def proposal(operations, relations=None) -> RoadmapProposal:
    return RoadmapProposal(
        proposal_id="proposal-1",
        based_on_analysis_id="analysis-1",
        based_on_fit_assessment_id="fit-1",
        based_on_normalization_id="normalization-1",
        based_on_roadmap_version=1,
        selected_position_id="pos-backend",
        capability_graph_version="graph-1",
        operations=operations,
        relations=relations or [],
        audit=audit(),
    )


def test_create_node_requires_scope_definition() -> None:
    with pytest.raises(ValidationError, match="scopeDefinition"):
        RoadmapOperation(
            operation_id="op-java",
            action=RoadmapAction.CREATE_NODE,
            canonical_key="lang.java",
            title="Java",
            section_key="section.backend",
            reason="공고 필수 역량",
        )


def test_valid_create_node_keeps_scope_definition() -> None:
    item = operation("lang.java", "op-java")
    assert item.scope_definition.startswith("Approved")


def test_proposal_rejects_unknown_relation_operation() -> None:
    relation = RoadmapRelation(
        relation_id="rel-java-spring",
        from_operation_id="op-java",
        to_operation_id="op-spring",
        relation_type=RoadmapRelationType.HARD_PREREQUISITE,
        reason="Java precedes Spring",
    )

    with pytest.raises(ValidationError, match="unknown operations"):
        proposal([operation("framework.spring_boot", "op-spring")], [relation])


def test_relation_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError, match="itself"):
        RoadmapRelation(
            relation_id="rel-self",
            from_operation_id="op-java",
            to_operation_id="op-java",
            relation_type=RoadmapRelationType.HARD_PREREQUISITE,
            reason="invalid",
        )


def test_proposal_rejects_blocking_cycle() -> None:
    java = operation("lang.java", "op-java")
    spring = operation("framework.spring_boot", "op-spring")
    relations = [
        RoadmapRelation(
            relation_id="rel-1",
            from_operation_id="op-java",
            to_operation_id="op-spring",
            relation_type=RoadmapRelationType.HARD_PREREQUISITE,
            reason="forward",
        ),
        RoadmapRelation(
            relation_id="rel-2",
            from_operation_id="op-spring",
            to_operation_id="op-java",
            relation_type=RoadmapRelationType.HARD_PREREQUISITE,
            reason="backward",
        ),
    ]

    with pytest.raises(ValidationError, match="cycle"):
        proposal([java, spring], relations)
