from __future__ import annotations

import pytest

from jobis_ai.career_pipeline.contracts.posting import ExperienceKind
from jobis_ai.career_pipeline.contracts.resolution import ExperienceTrack
from jobis_ai.career_pipeline.contracts.roadmap import (
    CareerGateType,
    CurrentRoadmapSnapshot,
    ExistingRoadmapNode,
    GateSpec,
    OpportunitySpec,
    ProjectSpec,
    RoadmapAction,
    RoadmapAudit,
    RoadmapNodeKind,
    RoadmapOperation,
    RoadmapProgressState,
    RoadmapProposal,
    RoadmapRelation,
    RoadmapRelationType,
)
from jobis_ai.career_pipeline.roadmap import RoadmapCompilationFailure, compile_preview


def current() -> CurrentRoadmapSnapshot:
    return CurrentRoadmapSnapshot(
        roadmap_version=3,
        nodes=[
            ExistingRoadmapNode(
                node_id="node-java",
                node_kind=RoadmapNodeKind.CAPABILITY,
                title="Java",
                canonical_key="lang.java",
                technology_key="lang.java",
                graph_node_version=1,
                verification_methods=["IMPLEMENT"],
                section_key="section.web_backend",
                progress_state=RoadmapProgressState.VERIFIED,
                scope_definition="Java language scope",
                level=2,
            ),
            ExistingRoadmapNode(
                node_id="node-entry-company",
                node_kind=RoadmapNodeKind.OPPORTUNITY,
                title="Entry Games · Backend",
                target_ref="opportunity-entry-games",
                section_key="section.web_backend",
                progress_state=RoadmapProgressState.NOT_STARTED,
                opportunity_spec=OpportunitySpec(
                    opportunity_id="opportunity-entry-games",
                    company_name="Entry Games",
                    position_title="Backend",
                    role_family="SOFTWARE_ENGINEERING",
                    role_specialization="WEB_BACKEND",
                    canonical_role_id="role.web_backend",
                    source_experience_kind=ExperienceKind.NEW_GRADUATE,
                    selected_experience_track=ExperienceTrack.NEW_GRADUATE,
                    minimum_experience_months=0,
                ),
            ),
        ],
    )


def proposal() -> RoadmapProposal:
    operations = [
        RoadmapOperation(
            operation_id="op-java",
            action=RoadmapAction.REUSE_NODE,
            node_kind=RoadmapNodeKind.CAPABILITY,
            canonical_key="lang.java",
            technology_key="lang.java",
            graph_node_version=2,
            verification_methods=["IMPLEMENT", "EXPLAIN"],
            existing_node_id="node-java",
            title="Java",
            scope_definition="Java language scope",
            section_key="section.web_backend",
            initial_progress_state=RoadmapProgressState.VERIFIED,
            reason="Reuse verified Java",
        ),
        RoadmapOperation(
            operation_id="op-project",
            action=RoadmapAction.CREATE_TARGET_PROJECT,
            node_kind=RoadmapNodeKind.TARGET_PROJECT,
            target_ref="project:opportunity-experienced",
            title="Experienced backend project",
            scope_definition="Build and operate a backend service",
            section_key="section.web_backend",
            project_spec=ProjectSpec(
                objective="Build and operate a backend service",
                deliverables=["Runnable service", "Operation report"],
                verification_criteria=["Tests pass", "Load result documented"],
                required_capability_keys=["lang.java"],
                domain_context="Backend service",
            ),
            reason="Company target project",
        ),
        RoadmapOperation(
            operation_id="op-gate",
            action=RoadmapAction.CREATE_GATE,
            node_kind=RoadmapNodeKind.CAREER_GATE,
            target_ref="gate:opportunity-experienced:req-exp",
            title="관련 직무 경력 2년",
            section_key="section.web_backend",
            gate_spec=GateSpec(
                gate_type=CareerGateType.EXPERIENCE,
                required_months=24,
                maximum_months=48,
                requirement_id="req-exp",
                evidence_ids=["seg-exp"],
                assessment_status="NOT_MET",
            ),
            reason="Formal experience gate",
        ),
        RoadmapOperation(
            operation_id="op-company",
            action=RoadmapAction.ADD_OPPORTUNITY,
            node_kind=RoadmapNodeKind.OPPORTUNITY,
            target_ref="opportunity-experienced",
            title="Experienced Cloud · Backend",
            section_key="section.web_backend",
            opportunity_spec=OpportunitySpec(
                opportunity_id="opportunity-experienced",
                company_name="Experienced Cloud",
                position_title="Backend",
                role_family="SOFTWARE_ENGINEERING",
                role_specialization="WEB_BACKEND",
                canonical_role_id="role.web_backend",
                source_experience_kind=ExperienceKind.EXPERIENCE_REQUIRED,
                selected_experience_track=ExperienceTrack.EXPERIENCED,
                minimum_experience_months=24,
                maximum_experience_months=48,
            ),
            reason="Experienced company opportunity",
        ),
    ]
    relations = [
        RoadmapRelation(
            relation_id="rel-java-project",
            from_operation_id="op-java",
            to_operation_id="op-project",
            relation_type=RoadmapRelationType.UNLOCKS_PROJECT,
            reason="Java is required",
        ),
        RoadmapRelation(
            relation_id="rel-project-company",
            from_operation_id="op-project",
            to_operation_id="op-company",
            relation_type=RoadmapRelationType.UNLOCKS_OPPORTUNITY,
            reason="Project unlocks company",
        ),
        RoadmapRelation(
            relation_id="rel-gate-company",
            from_operation_id="op-gate",
            to_operation_id="op-company",
            relation_type=RoadmapRelationType.REQUIRES_GATE,
            reason="Experience is required",
        ),
    ]
    return RoadmapProposal(
        proposal_id="proposal-experienced",
        based_on_analysis_id="analysis-experienced",
        based_on_fit_assessment_id="fit-experienced",
        based_on_normalization_id="normalization-experienced",
        based_on_roadmap_version=3,
        selected_position_id="pos-backend",
        capability_graph_version="graph-1",
        operations=operations,
        relations=relations,
        audit=RoadmapAudit(
            composer_version="roadmap-composer-3.0.0",
            provider="fixture",
            model="fixture",
            generation_attempts=1,
            generation_duration_ms=1,
            graph_content_hash="sha256:" + "a" * 64,
            preserved_existing_node_ids=["node-java"],
        ),
    )


def test_compiler_preserves_progress_and_requires_real_employment_before_experience() -> None:
    preview = compile_preview(current(), proposal())
    by_id = {node.node_id: node for node in preview.snapshot.nodes}
    gate = next(node for node in by_id.values() if node.node_kind is RoadmapNodeKind.CAREER_GATE)
    experienced = next(
        node for node in by_id.values()
        if node.target_ref == "opportunity-experienced"
    )

    assert preview.proposed_roadmap_version == 4
    assert by_id["node-java"].progress_state is RoadmapProgressState.VERIFIED
    assert by_id["node-java"].graph_node_version == 2
    assert [item.value for item in by_id["node-java"].verification_methods] == [
        "IMPLEMENT",
        "EXPLAIN",
    ]
    assert "node-entry-company" in by_id
    employment = next(
        node for node in by_id.values()
        if node.node_kind is RoadmapNodeKind.EMPLOYMENT_EVENT
    )
    interval = next(
        node for node in by_id.values()
        if node.node_kind is RoadmapNodeKind.EXPERIENCE_INTERVAL
    )
    relations = {
        (item.from_node_id, item.to_node_id, item.relation_type)
        for item in preview.snapshot.relations
    }
    assert (
        "node-entry-company",
        employment.node_id,
        RoadmapRelationType.POTENTIAL_CAREER_ENTRY,
    ) in relations
    assert (
        employment.node_id,
        interval.node_id,
        RoadmapRelationType.STARTS_EXPERIENCE,
    ) in relations
    assert (
        interval.node_id,
        gate.node_id,
        RoadmapRelationType.SATISFIES_EXPERIENCE_GATE,
    ) in relations
    assert not any(
        item.from_node_id == "node-entry-company"
        and item.to_node_id == gate.node_id
        for item in preview.snapshot.relations
    )
    assert interval.experience_interval_spec["minimumMonths"] == 24
    assert interval.experience_interval_spec["maximumMonths"] == 48
    assert interval.experience_interval_spec["evidenceState"] == "UNKNOWN"
    assert by_id["node-entry-company"].display_rank < employment.display_rank
    assert employment.display_rank < interval.display_rank
    assert interval.display_rank < gate.display_rank
    assert gate.display_rank < experienced.display_rank


def test_compiler_rejects_stale_proposal() -> None:
    stale = proposal().model_copy(update={"based_on_roadmap_version": 2})
    with pytest.raises(RoadmapCompilationFailure, match="stale proposal"):
        compile_preview(current(), stale)
