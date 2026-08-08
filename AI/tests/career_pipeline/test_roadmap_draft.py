from __future__ import annotations

import copy
import asyncio
import json
from datetime import UTC, date, datetime

import pytest
import httpx

from jobis_ai.career_pipeline.capability_graph import closure_content_hash
from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphNode,
    CapabilityNodeType,
    CapabilityRelationType,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    GraphSnapshotScope,
    GraphSource,
    GraphSourceType,
    LearningLayer,
    ProjectNecessity,
    VerificationMethod,
)
from jobis_ai.career_pipeline.contracts.fit import (
    AssessmentBasis,
    ClaimState,
    EvidenceSourceType,
    EvidenceState,
    FitAssessment,
    FitAudit,
    FitMetrics,
    RequirementAssessment,
    RequirementStatus,
    UserCompetencyEvidence,
    UserEvidenceBundle,
    UserEvidenceItem,
    VerificationState,
    VerdictProposal,
)
from jobis_ai.career_pipeline.contracts.normalization import (
    CapabilityKind,
    CapabilityNormalizationResult,
    NewCapabilityCandidate,
    NormalizationAudit,
    NormalizationDecision,
    RequirementNormalization,
    ReviewStatus,
    RoadmapDisposition,
)
from jobis_ai.career_pipeline.contracts.posting import PostingStatus, RequirementCategory, StructuredPosting
from jobis_ai.career_pipeline.contracts.resolution import ExperienceTrack
from jobis_ai.career_pipeline.contracts.project_planning import (
    CompanyProjectBlueprint,
    PlannedProjectTask,
    ProjectPlanningAudit,
)
from jobis_ai.career_pipeline.contracts.roadmap import (
    CurrentRoadmapSnapshot,
    ExistingRoadmapNode,
    OpportunityGoalMode,
    OpportunityTargetInput,
    RoadmapAction,
    RoadmapDraftRequest,
    RoadmapNodeKind,
    RoadmapProgressState,
    RoadmapRelationType,
)
from jobis_ai.career_pipeline.llm import StructuredGenerator
from jobis_ai.career_pipeline.roadmap import RoadmapDraftFailure, RoadmapDraftService


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
GRAPH_VERSION = "0.1.0-alpha.1"


class StaticProvider:
    name = "scripted"
    model = "roadmap-fixture"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, **_kwargs) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def source() -> GraphSource:
    return GraphSource(
        source_id="source-graph",
        title="Approved backend curriculum",
        uri="https://example.invalid/curriculum",
        publisher="Example Foundation",
        source_type=GraphSourceType.INTERNAL_DESIGN,
        retrieved_at=NOW,
        evidence_summary="Reviewed atomic capability fixture for roadmap tests.",
        snapshot_scope=GraphSnapshotScope.INTERNAL_RECORD,
        content_hash="sha256:" + "a" * 64,
    )


def graph_confidence() -> GraphConfidence:
    return GraphConfidence(
        band=GraphConfidenceBand.VERIFIED,
        reason="The roadmap fixture is explicitly reviewed.",
    )


def graph(*, include_target: bool = True) -> CapabilityGraphClosure:
    nodes = [
        CapabilityGraphNode(
            canonical_key="java.control-flow",
            technology_key="lang.java",
            display_name="Java control flow",
            node_type=CapabilityNodeType.PERFORMANCE,
            kind=CapabilityKind.COMPUTER_SCIENCE,
            objective="Implement requirement branches with conditions and loops.",
            scope_definition="Java if, switch, for, while, and branch control",
            verification_methods=[VerificationMethod.IMPLEMENT],
            confidence=graph_confidence(),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=["source-graph"],
        ),
    ]
    edges = []
    targets = []
    if include_target:
        nodes.append(CapabilityGraphNode(
            canonical_key="java.classes-objects",
            technology_key="lang.java",
            display_name="Java class and object modelling",
            node_type=CapabilityNodeType.PERFORMANCE,
            kind=CapabilityKind.PROGRAMMING_LANGUAGE,
            objective="Model state and behavior with Java classes and collaborating objects.",
            scope_definition="Classes, constructors, fields, methods, and object collaboration",
            verification_methods=[VerificationMethod.IMPLEMENT],
            confidence=graph_confidence(),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=["source-graph"],
        ))
        edges.append(CapabilityGraphEdge(
            relation_id="rel-control-flow-classes",
            from_capability_key="java.control-flow",
            to_capability_key="java.classes-objects",
            relation_type=CapabilityRelationType.HARD_PREREQUISITE,
            confidence=graph_confidence(),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=["source-graph"],
            reason="Programming fundamentals precede language-specific practice.",
        ))
        targets = ["java.classes-objects"]
    value = CapabilityGraphClosure(
        graph_version=GRAPH_VERSION,
        generated_at=NOW,
        content_hash="sha256:" + "0" * 64,
        target_capability_keys=targets,
        nodes=nodes,
        edges=edges,
        sources=[source()],
        learning_order=[
            LearningLayer(
                depth=0,
                capability_keys=["java.control-flow"],
            ),
            *(
                [
                    LearningLayer(
                        depth=1,
                        capability_keys=["java.classes-objects"],
                    )
                ]
                if include_target else []
            ),
        ],
    )
    return value.model_copy(update={"content_hash": closure_content_hash(value)})


def fit(
    *,
    experience: RequirementAssessment | None = None,
    track: ExperienceTrack | None = None,
) -> FitAssessment:
    java = RequirementAssessment(
        requirement_id="req-java",
        status=RequirementStatus.VERIFIED_MET,
        required=True,
        included_in_denominator=True,
        basis=AssessmentBasis.VERIFIED_COMPETENCY,
        matched_competencies=["java.classes-objects"],
        posting_evidence_ids=["seg-req"],
        reason="Java was verified.",
        confidence=1.0,
    )
    assessments = [java, *([experience] if experience else [])]
    return FitAssessment(
        fit_assessment_id="fit-roadmap-1",
        common_analysis_id="analysis-roadmap-1",
        selected_position_id="pos-backend",
        selected_experience_track=track,
        user_evidence_set_id="evidence-roadmap-1",
        user_evidence_revision=1,
        policy_version="fit-policy-0.1",
        formal_eligibility=(
            experience.status if experience else RequirementStatus.NOT_APPLICABLE
        ),
        requirement_assessments=assessments,
        metrics=FitMetrics(
            required_total=len(assessments),
            required_known=len(assessments),
            required_verified_met=sum(
                item.status is RequirementStatus.VERIFIED_MET for item in assessments
            ),
            preferred_total=0,
            claimed_readiness_percent=100,
            evidenced_readiness_percent=100,
            verified_readiness_percent=100,
        ),
        verdict_proposal=VerdictProposal.APPLY_NOW,
        audit=FitAudit(
            matcher_version="fit-test",
            policy_version="fit-policy-0.1",
            provider="scripted",
            model="fixture",
            generation_attempts=1,
            generation_duration_ms=1,
            evaluated_requirement_ids=[item.requirement_id for item in assessments],
        ),
    )


def normalization(*, provisional: bool = False) -> CapabilityNormalizationResult:
    if provisional:
        item = RequirementNormalization(
            requirement_id="req-java",
            source_category=RequirementCategory.TECHNOLOGY,
            disposition=RoadmapDisposition.LEARNING_CAPABILITY,
            decision=NormalizationDecision.NEW_CANDIDATE_PROPOSED,
            new_candidate=NewCapabilityCandidate(
                candidate_id="capability-candidate-fluxion",
                display_name="FluxionDB",
                proposed_kind=CapabilityKind.DATABASE,
                scope_definition="Operating FluxionDB stream partitions, retention, recovery, and monitoring",
                aliases=["FluxionDB"],
                evidence_ids=["seg-req"],
                confidence=0.95,
            ),
            review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
            evidence_ids=["seg-req"],
            reason="New technology candidate",
        )
    else:
        item = RequirementNormalization(
            requirement_id="req-java",
            source_category=RequirementCategory.TECHNOLOGY,
            disposition=RoadmapDisposition.LEARNING_CAPABILITY,
            decision=NormalizationDecision.AUTO_SELECTED,
            selected_canonical_key="java.classes-objects",
            candidates=[{
                "canonicalKey": "java.classes-objects",
                "matchType": "EXACT_ALIAS",
                "confidence": 1.0,
                "reason": "Exact approved alias",
            }],
            review_status=ReviewStatus.NOT_REQUIRED,
            evidence_ids=["seg-req"],
            reason="Exact approved alias",
        )
    return CapabilityNormalizationResult(
        normalization_id="normalization-roadmap-1",
        common_analysis_id="analysis-roadmap-1",
        selected_position_id="pos-backend",
        catalog_version=GRAPH_VERSION,
        items=[item],
        audit=NormalizationAudit(
            normalizer_version="normalizer-test",
            catalog_version=GRAPH_VERSION,
        ),
    )


def project_payload(*, provisional: bool = False) -> dict:
    return {
        "project": {
            "title": "Example Games backend readiness project",
            "objective": "Build a small service that demonstrates the target backend requirements.",
            "deliverables": ["Runnable service", "Architecture and operation notes"],
            "verificationCriteria": ["Automated tests pass", "The service can be run from documented steps"],
            "requiredCapabilityKeys": [] if provisional else ["java.classes-objects"],
            "preferredCapabilityKeys": [],
            "requiredProvisionalCandidateIds": (
                ["capability-candidate-fluxion"] if provisional else []
            ),
            "preferredProvisionalCandidateIds": [],
            "domainContext": "Example Games backend service",
        },
    }


def blueprint(
    *,
    preferred: bool = False,
    provisional: bool = False,
    fabricated: bool = False,
) -> CompanyProjectBlueprint:
    tasks = [
        PlannedProjectTask(
            task_key="task.draft.java-service",
            necessity=ProjectNecessity.REQUIRED,
            title="Java service core",
            objective="Model and implement the backend service core with Java objects.",
            acceptance_criteria=["The service runs", "Automated tests pass"],
            capability_keys=(
                []
                if provisional
                else ["database.fabricated" if fabricated else "java.classes-objects"]
            ),
            requirement_ids=["req-java"],
        )
    ]
    if preferred:
        tasks.append(PlannedProjectTask(
            task_key="task.draft.kafka-events",
            necessity=ProjectNecessity.RECOMMENDED,
            title="Kafka event extension",
            objective="Publish backend events through Kafka.",
            acceptance_criteria=["Events are published", "Failures are tested"],
            capability_keys=["kafka.producer"],
            requirement_ids=["req-kafka"],
        ))
    return CompanyProjectBlueprint(
        blueprint_id="project-blueprint-roadmap-1",
        common_analysis_id="analysis-roadmap-1",
        selected_position_id="pos-backend",
        title="Example Games backend readiness project",
        objective="Build a service that demonstrates the target backend requirements.",
        domain_context="Example Games backend service",
        tasks=tasks,
        unresolved_requirement_ids=["req-java"] if provisional else [],
        audit=ProjectPlanningAudit(
            planner_version="planner-test",
            graph_version=GRAPH_VERSION,
            graph_content_hash="sha256:" + "b" * 64,
            provider="scripted",
            model="project-planner-fixture",
            generation_attempts=1,
            generation_duration_ms=1,
        ),
    )


def request(
    structured_posting,
    *,
    current=None,
    graph_value=None,
    normalization_value=None,
    fit_value=None,
    blueprint_value=None,
    user_evidence=None,
) -> RoadmapDraftRequest:
    return RoadmapDraftRequest(
        common_analysis_id="analysis-roadmap-1",
        structured_posting=structured_posting,
        selected_position_id="pos-backend",
        fit_assessment=fit_value or fit(),
        normalization=normalization_value or normalization(),
        project_blueprint=blueprint_value or blueprint(),
        capability_graph=graph_value or graph(),
        user_evidence=user_evidence,
        current_roadmap=current or CurrentRoadmapSnapshot(roadmap_version=0),
        opportunity=OpportunityTargetInput(
            opportunity_id="opportunity-example-games-backend",
            company_name="Example Games",
            position_title="Backend engineer",
            posting_title="Example Games backend engineer",
        ),
    )


def service(payload=None) -> RoadmapDraftService:
    return RoadmapDraftService(
        StructuredGenerator(StaticProvider(payload or project_payload()), max_attempts=1)
    )


def test_one_branch_contains_capabilities_project_and_company_opportunity(structured_posting) -> None:
    proposal = service().compose(request(structured_posting))

    kinds = [item.node_kind for item in proposal.operations]
    assert kinds.count(RoadmapNodeKind.CAPABILITY) == 2
    assert kinds.count(RoadmapNodeKind.TARGET_PROJECT) == 1
    assert kinds.count(RoadmapNodeKind.OPPORTUNITY) == 1
    assert proposal.status.value == "DRAFT"
    assert any(
        relation.relation_type is RoadmapRelationType.HARD_PREREQUISITE
        for relation in proposal.relations
    )
    assert any(
        relation.relation_type is RoadmapRelationType.UNLOCKS_PROJECT
        for relation in proposal.relations
    )
    assert any(
        relation.relation_type is RoadmapRelationType.UNLOCKS_OPPORTUNITY
        for relation in proposal.relations
    )
    control_flow = next(
        item for item in proposal.operations if item.canonical_key == "java.control-flow"
    )
    java = next(
        item for item in proposal.operations if item.canonical_key == "java.classes-objects"
    )
    opportunity = next(
        item for item in proposal.operations
        if item.node_kind is RoadmapNodeKind.OPPORTUNITY
    )
    assert control_flow.section_key == "section.web_backend"
    assert java.section_key == "section.web_backend"
    assert opportunity.opportunity_spec.role_specialization == "WEB_BACKEND"
    assert opportunity.opportunity_spec.minimum_experience_months == 0
    assert opportunity.opportunity_spec.goal_mode is OpportunityGoalMode.REFERENCE_TARGET


def test_atomic_capabilities_use_stable_learning_chapters_not_project_task_titles(
    structured_posting,
) -> None:
    proposal = service().compose(request(structured_posting))
    capabilities = [
        item for item in proposal.operations
        if item.node_kind is RoadmapNodeKind.CAPABILITY
    ]

    assert capabilities
    assert all(
        membership.chapter_title != "Java service core"
        for item in capabilities
        for membership in item.section_memberships
    )
    java = next(item for item in capabilities if item.canonical_key == "java.classes-objects")
    control_flow = next(item for item in capabilities if item.canonical_key == "java.control-flow")
    assert java.section_memberships[0].chapter_key == "chapter.language-framework"
    assert control_flow.section_memberships[0].chapter_key == "chapter.foundation"
    assert java.section_memberships[0].target_ref == "stage.entry"
    assert "직접 필요한" in java.section_memberships[0].reason
    assert "선수 관계로 포함된" in control_flow.section_memberships[0].reason


@pytest.mark.parametrize(
    ("posting_status", "goal_mode"),
    [
        (PostingStatus.ACTIVE, OpportunityGoalMode.ACTIVE_APPLICATION),
        (PostingStatus.CLOSED, OpportunityGoalMode.REOPENING_PREPARATION),
        (PostingStatus.UNKNOWN, OpportunityGoalMode.REFERENCE_TARGET),
    ],
)
def test_opportunity_goal_mode_follows_posting_lifecycle(
    structured_posting,
    posting_status,
    goal_mode,
) -> None:
    posting = structured_posting.model_copy(update={
        "posting_status": posting_status,
        "application_deadline": (
            date(2026, 7, 31) if posting_status is PostingStatus.CLOSED else None
        ),
    })

    proposal = service().compose(request(posting))
    opportunity = next(
        item for item in proposal.operations
        if item.node_kind is RoadmapNodeKind.OPPORTUNITY
    )

    assert opportunity.opportunity_spec.posting_status is posting_status
    assert opportunity.opportunity_spec.goal_mode is goal_mode


def test_existing_verified_capability_is_reused_without_progress_reset(structured_posting) -> None:
    current = CurrentRoadmapSnapshot(
        roadmap_version=4,
        nodes=[
            ExistingRoadmapNode(
                node_id="node-java-existing",
                node_kind=RoadmapNodeKind.CAPABILITY,
                title="Java",
                canonical_key="java.classes-objects",
                section_key="section.web_backend",
                progress_state=RoadmapProgressState.VERIFIED,
                scope_definition="Existing Java scope",
            )
        ],
    )

    proposal = service().compose(request(structured_posting, current=current))
    java = next(
        item for item in proposal.operations if item.canonical_key == "java.classes-objects"
    )

    assert java.action is RoadmapAction.REUSE_NODE
    assert java.existing_node_id == "node-java-existing"
    assert java.initial_progress_state is RoadmapProgressState.VERIFIED
    assert "node-java-existing" in proposal.audit.preserved_existing_node_ids


def test_verified_user_evidence_overlays_new_capability_progress(structured_posting) -> None:
    evidence = UserEvidenceBundle(
        evidence_set_id="evidence-roadmap-overlay",
        revision=1,
        evidence_items=[UserEvidenceItem(
            evidence_id="evidence-java-project",
            source_type=EvidenceSourceType.PROJECT,
            title="Java domain project",
            text="Implemented collaborating Java objects and verified them with tests.",
            verification_state=VerificationState.VERIFIED,
            confidence=1.0,
        )],
        competencies=[UserCompetencyEvidence(
            competency_id="java.classes-objects",
            display_name="Java classes and objects",
            scope_definition="Model state and behavior with collaborating Java objects.",
            claim_state=ClaimState.CLAIMED,
            evidence_state=EvidenceState.EVIDENCED,
            verification_state=VerificationState.VERIFIED,
            claimed_level=2,
            verified_level=2,
            evidence_refs=["evidence-java-project"],
            confidence=1.0,
        )],
    )

    proposal = service().compose(request(
        structured_posting,
        user_evidence=evidence,
    ))
    java = next(
        item for item in proposal.operations
        if item.canonical_key == "java.classes-objects"
    )
    control_flow = next(
        item for item in proposal.operations
        if item.canonical_key == "java.control-flow"
    )

    assert java.initial_progress_state is RoadmapProgressState.VERIFIED
    assert control_flow.initial_progress_state is RoadmapProgressState.NOT_STARTED


def test_new_technology_continues_as_user_scoped_provisional_node(structured_posting) -> None:
    posting = copy.deepcopy(structured_posting.model_dump(mode="json"))
    posting["positions"][0]["requirements"][0]["source_text"] = "FluxionDB 운영"
    posting["positions"][0]["requirements"][0]["atomic_text"] = "FluxionDB 운영"
    structured = StructuredPosting.model_validate(posting)
    proposal = service(project_payload(provisional=True)).compose(request(
        structured,
        graph_value=graph(include_target=False),
        normalization_value=normalization(provisional=True),
        blueprint_value=blueprint(provisional=True),
    ))

    item = next(
        operation
        for operation in proposal.operations
        if operation.provisional_candidate_id == "capability-candidate-fluxion"
    )
    assert item.action is RoadmapAction.CREATE_NODE
    assert "level" not in item.model_dump(mode="json", by_alias=True)
    assert item.canonical_key is None
    assert any(
        warning.code == "PROVISIONAL_CAPABILITY_PENDING_REVIEW"
        for warning in proposal.warnings
    )
    project = next(
        operation for operation in proposal.operations
        if operation.node_kind is RoadmapNodeKind.TARGET_PROJECT
    )
    assert project.project_spec.required_provisional_candidate_ids == [
        "capability-candidate-fluxion"
    ]
    assert [task.title for task in project.project_spec.tasks] == ["Java service core"]


def test_missing_graph_target_is_rejected(structured_posting) -> None:
    with pytest.raises(RoadmapDraftFailure, match="missing normalized targets"):
        service().compose(request(
            structured_posting,
            graph_value=graph(include_target=False),
        ))


def test_preferred_capability_is_a_bonus_not_a_project_blocker(structured_posting) -> None:
    posting_payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    preferred = copy.deepcopy(posting_payload["positions"][0]["requirements"][0])
    preferred.update({
        "requirement_id": "req-kafka",
        "source_text": "Kafka 경험 우대",
        "atomic_text": "Kafka 비동기 메시징",
        "obligation": "PREFERRED",
    })
    posting_payload["positions"][0]["requirements"].append(preferred)
    posting = StructuredPosting.model_validate(posting_payload)

    normalization_value = normalization()
    kafka_normalization = RequirementNormalization(
        requirement_id="req-kafka",
        source_category=RequirementCategory.TECHNOLOGY,
        disposition=RoadmapDisposition.LEARNING_CAPABILITY,
        decision=NormalizationDecision.AUTO_SELECTED,
        selected_canonical_key="kafka.producer",
        candidates=[{
            "canonicalKey": "kafka.producer",
            "matchType": "EXACT_ALIAS",
            "confidence": 1.0,
            "reason": "Exact alias",
        }],
        review_status=ReviewStatus.NOT_REQUIRED,
        evidence_ids=["seg-req"],
        reason="Exact alias",
    )
    normalization_value = normalization_value.model_copy(update={
        "items": [*normalization_value.items, kafka_normalization]
    })

    graph_value = graph()
    kafka_node = CapabilityGraphNode(
        canonical_key="kafka.producer",
        technology_key="messaging.kafka",
        display_name="Kafka event publishing",
        node_type=CapabilityNodeType.PERFORMANCE,
        kind=CapabilityKind.MESSAGING,
        objective="Publish a domain event with a defined Kafka record contract.",
        scope_definition="Producer records, keys, acknowledgements, and send failures",
        verification_methods=[VerificationMethod.IMPLEMENT, VerificationMethod.TEST],
        confidence=graph_confidence(),
        review_status=GraphReviewStatus.APPROVED,
        version=1,
        source_ids=["source-graph"],
    )
    graph_value = graph_value.model_copy(update={
        "target_capability_keys": ["java.classes-objects", "kafka.producer"],
        "nodes": [*graph_value.nodes, kafka_node],
        "learning_order": [
            *graph_value.learning_order,
            LearningLayer(depth=2, capability_keys=["kafka.producer"]),
        ],
        "content_hash": "sha256:" + "0" * 64,
    })
    graph_value = graph_value.model_copy(update={
        "content_hash": closure_content_hash(graph_value)
    })
    proposal = service().compose(request(
        posting,
        graph_value=graph_value,
        normalization_value=normalization_value,
        blueprint_value=blueprint(preferred=True),
    ))

    kafka = next(item for item in proposal.operations if item.canonical_key == "kafka.producer")
    project = next(item for item in proposal.operations if item.node_kind is RoadmapNodeKind.TARGET_PROJECT)
    relation = next(
        item for item in proposal.relations
        if item.from_operation_id == kafka.operation_id
        and item.to_operation_id == project.operation_id
    )
    assert relation.relation_type is RoadmapRelationType.BONUS_SUPPORTS_PROJECT
    assert kafka.required_for == []
    assert kafka.preferred_for == ["opportunity-example-games-backend"]
    assert kafka.technology_key == "messaging.kafka"
    assert kafka.graph_node_version == 1
    assert kafka.verification_methods == [VerificationMethod.IMPLEMENT, VerificationMethod.TEST]
    assert kafka.completion_policy.value == "ASSESSMENT"


def test_project_cannot_invent_capability_reference(structured_posting) -> None:
    with pytest.raises(RoadmapDraftFailure, match="missing normalized targets"):
        service().compose(request(
            structured_posting,
            blueprint_value=blueprint(fabricated=True),
        ))


def test_experience_range_preserves_minimum_and_maximum_before_opportunity(structured_posting) -> None:
    payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    payload["positions"][0]["experience"] = {
        "kind": "RANGE",
        "min_months": 24,
        "max_months": 48,
        "experienced_min_months": None,
        "confidence": 1.0,
        "evidence_ids": ["seg-exp"],
    }
    posting = StructuredPosting.model_validate(payload)
    exp_assessment = RequirementAssessment(
        requirement_id="req-experience-pos-backend",
        status=RequirementStatus.NOT_MET,
        required=True,
        included_in_denominator=True,
        basis=AssessmentBasis.VERIFIED_INSUFFICIENCY,
        posting_evidence_ids=["seg-exp"],
        reason="Verified experience is below 24 months.",
        confidence=1.0,
    )
    proposal = service().compose(request(
        posting,
        fit_value=fit(experience=exp_assessment),
    ))

    gate = next(
        item for item in proposal.operations
        if item.node_kind is RoadmapNodeKind.CAREER_GATE
    )
    assert gate.gate_spec.required_months == 24
    assert gate.gate_spec.maximum_months == 48
    assert gate.initial_progress_state is RoadmapProgressState.NOT_STARTED
    opportunity = next(
        item for item in proposal.operations
        if item.node_kind is RoadmapNodeKind.OPPORTUNITY
    )
    assert opportunity.opportunity_spec.minimum_experience_months == 24
    assert opportunity.opportunity_spec.maximum_experience_months == 48
    assert any(
        relation.from_operation_id == gate.operation_id
        and relation.relation_type is RoadmapRelationType.REQUIRES_GATE
        for relation in proposal.relations
    )


def test_new_graduate_track_does_not_inherit_the_experienced_gate(structured_posting) -> None:
    payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    payload["positions"][0]["experience"] = {
        "kind": "NEW_GRADUATE_OR_EXPERIENCED",
        "min_months": None,
        "max_months": None,
        "experienced_min_months": 36,
        "confidence": 1.0,
        "evidence_ids": ["seg-exp"],
    }
    posting = StructuredPosting.model_validate(payload)

    proposal = service().compose(request(
        posting,
        fit_value=fit(track=ExperienceTrack.NEW_GRADUATE),
    ))

    assert not any(
        item.node_kind is RoadmapNodeKind.CAREER_GATE
        for item in proposal.operations
    )
