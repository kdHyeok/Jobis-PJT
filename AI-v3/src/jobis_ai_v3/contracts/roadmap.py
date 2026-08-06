from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .capability_graph import (
    CapabilityGraphClosure,
    CompletionPolicy,
    GraphCondition,
    VerificationMethod,
)
from .common import CanonicalKey, ContractModel, EntityId, NonBlank, WarningItem, ensure_unique
from .fit import FitAssessment, RequirementStatus, UserEvidenceBundle
from .normalization import CapabilityNormalizationResult
from .posting import ExperienceKind, PostingStatus, StructuredPosting
from .project_planning import CompanyProjectBlueprint, PlannedProjectTask
from .resolution import ExperienceTrack


class ProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class RoadmapAction(StrEnum):
    REUSE_NODE = "REUSE_NODE"
    CREATE_NODE = "CREATE_NODE"
    CREATE_GATE = "CREATE_GATE"
    CREATE_TARGET_PROJECT = "CREATE_TARGET_PROJECT"
    ADD_OPPORTUNITY = "ADD_OPPORTUNITY"


class RoadmapNodeKind(StrEnum):
    CAPABILITY = "CAPABILITY"
    TARGET_PROJECT = "TARGET_PROJECT"
    CAREER_GATE = "CAREER_GATE"
    OPPORTUNITY = "OPPORTUNITY"
    EMPLOYMENT_EVENT = "EMPLOYMENT_EVENT"
    EXPERIENCE_INTERVAL = "EXPERIENCE_INTERVAL"


class RoadmapProgressState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    CLAIMED = "CLAIMED"
    EVIDENCED = "EVIDENCED"
    VERIFIED = "VERIFIED"


class OpportunityGoalMode(StrEnum):
    ACTIVE_APPLICATION = "ACTIVE_APPLICATION"
    REOPENING_PREPARATION = "REOPENING_PREPARATION"
    REFERENCE_TARGET = "REFERENCE_TARGET"


class SectionMembership(ContractModel):
    section_key: CanonicalKey
    chapter_key: EntityId
    chapter_title: NonBlank
    target_ref: EntityId
    reason: NonBlank


class CareerGateType(StrEnum):
    EXPERIENCE = "EXPERIENCE"
    CREDENTIAL = "CREDENTIAL"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class RoadmapRelationType(StrEnum):
    HARD_PREREQUISITE = "HARD_PREREQUISITE"
    RECOMMENDED_FOUNDATION = "RECOMMENDED_FOUNDATION"
    CONDITIONAL_PREREQUISITE = "CONDITIONAL_PREREQUISITE"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    PART_OF = "PART_OF"
    UNLOCKS_PROJECT = "UNLOCKS_PROJECT"
    BONUS_SUPPORTS_PROJECT = "BONUS_SUPPORTS_PROJECT"
    REQUIRES_GATE = "REQUIRES_GATE"
    UNLOCKS_OPPORTUNITY = "UNLOCKS_OPPORTUNITY"
    CAREER_STAGE_ORDER = "CAREER_STAGE_ORDER"
    POTENTIAL_CAREER_ENTRY = "POTENTIAL_CAREER_ENTRY"
    STARTS_EXPERIENCE = "STARTS_EXPERIENCE"
    SATISFIES_EXPERIENCE_GATE = "SATISFIES_EXPERIENCE_GATE"


class ProjectSpec(ContractModel):
    objective: NonBlank
    deliverables: list[NonBlank] = Field(min_length=2)
    verification_criteria: list[NonBlank] = Field(min_length=2)
    required_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    preferred_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    required_provisional_candidate_ids: list[EntityId] = Field(default_factory=list)
    preferred_provisional_candidate_ids: list[EntityId] = Field(default_factory=list)
    domain_context: NonBlank
    tasks: list[PlannedProjectTask] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capabilities(self) -> "ProjectSpec":
        ensure_unique(self.required_capability_keys, "project required capability")
        ensure_unique(self.preferred_capability_keys, "project preferred capability")
        overlap = set(self.required_capability_keys) & set(self.preferred_capability_keys)
        if overlap:
            raise ValueError(f"project capabilities cannot be both required and preferred: {sorted(overlap)}")
        ensure_unique(
            self.required_provisional_candidate_ids,
            "project required provisional candidate",
        )
        ensure_unique(
            self.preferred_provisional_candidate_ids,
            "project preferred provisional candidate",
        )
        provisional_overlap = set(self.required_provisional_candidate_ids) & set(
            self.preferred_provisional_candidate_ids
        )
        if provisional_overlap:
            raise ValueError(
                "project provisional capabilities cannot be both required and preferred: "
                f"{sorted(provisional_overlap)}"
            )
        return self


class GateSpec(ContractModel):
    gate_type: CareerGateType
    required_months: int | None = Field(default=None, ge=1)
    maximum_months: int | None = Field(default=None, ge=1)
    requirement_id: EntityId | None = None
    evidence_ids: list[EntityId] = Field(default_factory=list)
    assessment_status: RequirementStatus

    @model_validator(mode="after")
    def validate_gate(self) -> "GateSpec":
        if self.gate_type is CareerGateType.EXPERIENCE and self.required_months is None:
            raise ValueError("EXPERIENCE gate requires requiredMonths")
        if self.gate_type is not CareerGateType.EXPERIENCE and (
            self.required_months is not None or self.maximum_months is not None
        ):
            raise ValueError("only EXPERIENCE gate may carry experience months")
        if (
            self.maximum_months is not None
            and self.required_months is not None
            and self.maximum_months < self.required_months
        ):
            raise ValueError("maximumMonths cannot be less than requiredMonths")
        return self


class OpportunitySpec(ContractModel):
    opportunity_id: EntityId
    company_name: NonBlank
    position_title: NonBlank
    posting_title: NonBlank | None = None
    role_family: NonBlank
    role_specialization: NonBlank
    canonical_role_id: EntityId | None = None
    source_experience_kind: ExperienceKind
    selected_experience_track: ExperienceTrack | None = None
    minimum_experience_months: int | None = Field(default=None, ge=0)
    maximum_experience_months: int | None = Field(default=None, ge=0)
    posting_status: PostingStatus = PostingStatus.UNKNOWN
    application_deadline: date | None = None
    goal_mode: OpportunityGoalMode = OpportunityGoalMode.REFERENCE_TARGET

    @model_validator(mode="after")
    def validate_career_stage(self) -> "OpportunitySpec":
        if (
            self.source_experience_kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED
            and self.selected_experience_track is None
        ):
            raise ValueError("mixed experience opportunity requires selectedExperienceTrack")
        if self.source_experience_kind in {
            ExperienceKind.NEW_GRADUATE,
            ExperienceKind.NO_RESTRICTION,
        } and (
            self.minimum_experience_months != 0
            or self.maximum_experience_months is not None
        ):
            raise ValueError("entry opportunities require minimumExperienceMonths=0 and no maximum")
        if self.source_experience_kind in {
            ExperienceKind.EXPERIENCE_REQUIRED,
            ExperienceKind.RANGE,
        } and (self.minimum_experience_months is None or self.minimum_experience_months <= 0):
            raise ValueError("experienced opportunities require positive minimumExperienceMonths")
        if (
            self.maximum_experience_months is not None
            and self.minimum_experience_months is not None
            and self.maximum_experience_months < self.minimum_experience_months
        ):
            raise ValueError(
                "maximumExperienceMonths cannot be less than minimumExperienceMonths"
            )
        expected_goal_mode = {
            PostingStatus.ACTIVE: OpportunityGoalMode.ACTIVE_APPLICATION,
            PostingStatus.CLOSED: OpportunityGoalMode.REOPENING_PREPARATION,
            PostingStatus.UNKNOWN: OpportunityGoalMode.REFERENCE_TARGET,
        }[self.posting_status]
        if self.goal_mode is not expected_goal_mode:
            raise ValueError(
                f"{self.posting_status.value} opportunity requires goalMode={expected_goal_mode.value}"
            )
        return self


class ExistingRoadmapNode(ContractModel):
    node_id: EntityId
    node_kind: RoadmapNodeKind
    title: NonBlank
    canonical_key: CanonicalKey | None = None
    technology_key: CanonicalKey | None = None
    graph_node_version: int | None = Field(default=None, ge=1)
    verification_methods: list[VerificationMethod] = Field(default_factory=list)
    objective: NonBlank | None = None
    excluded_scope: list[NonBlank] = Field(default_factory=list)
    completion_policy: CompletionPolicy = CompletionPolicy.ASSESSMENT
    provisional_candidate_id: EntityId | None = None
    target_ref: EntityId | None = None
    section_key: CanonicalKey
    progress_state: RoadmapProgressState
    scope_definition: NonBlank | None = None
    level: int | None = Field(default=None, ge=1, le=5)
    display_rank: int = Field(default=0, ge=0)
    section_memberships: list[SectionMembership] = Field(default_factory=list)
    project_spec: ProjectSpec | None = None
    gate_spec: GateSpec | None = None
    opportunity_spec: OpportunitySpec | None = None
    employment_spec: dict | None = None
    experience_interval_spec: dict | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "ExistingRoadmapNode":
        ensure_unique(
            [
                f"{item.section_key}:{item.chapter_key}:{item.target_ref}"
                for item in self.section_memberships
            ],
            "section membership",
        )
        if self.node_kind is RoadmapNodeKind.CAPABILITY:
            if (self.canonical_key is None) == (self.provisional_candidate_id is None):
                raise ValueError(
                    "capability nodes require exactly one of canonicalKey or provisionalCandidateId"
                )
            if self.target_ref is not None:
                raise ValueError("capability nodes cannot carry targetRef")
            if any((
                self.project_spec,
                self.gate_spec,
                self.opportunity_spec,
                self.employment_spec,
                self.experience_interval_spec,
            )):
                raise ValueError("capability nodes cannot carry non-capability payloads")
        else:
            if self.canonical_key is not None or self.provisional_candidate_id is not None:
                raise ValueError("non-capability nodes cannot carry capability identities")
            if self.target_ref is None:
                raise ValueError("non-capability nodes require targetRef")
            payloads = {
                RoadmapNodeKind.TARGET_PROJECT: self.project_spec,
                RoadmapNodeKind.CAREER_GATE: self.gate_spec,
                RoadmapNodeKind.OPPORTUNITY: self.opportunity_spec,
                RoadmapNodeKind.EMPLOYMENT_EVENT: self.employment_spec,
                RoadmapNodeKind.EXPERIENCE_INTERVAL: self.experience_interval_spec,
            }
            supplied = [item for item in payloads.values() if item is not None]
            if len(supplied) > 1 or (
                supplied and payloads[self.node_kind] is None
            ):
                raise ValueError("existing non-capability payload does not match nodeKind")
        return self


class ExistingRoadmapRelation(ContractModel):
    relation_id: EntityId
    from_node_id: EntityId
    to_node_id: EntityId
    relation_type: RoadmapRelationType
    conditions: list[GraphCondition] = Field(default_factory=list)
    reason: NonBlank

    @model_validator(mode="after")
    def validate_relation(self) -> "ExistingRoadmapRelation":
        if self.from_node_id == self.to_node_id:
            raise ValueError("existing roadmap relation cannot refer to itself")
        if (
            self.relation_type is RoadmapRelationType.CONDITIONAL_PREREQUISITE
            and not self.conditions
        ):
            raise ValueError("conditional existing relation requires conditions")
        if (
            self.relation_type is not RoadmapRelationType.CONDITIONAL_PREREQUISITE
            and self.conditions
        ):
            raise ValueError("only conditional existing relations may carry conditions")
        return self


class CurrentRoadmapSnapshot(ContractModel):
    roadmap_version: int = Field(ge=0)
    nodes: list[ExistingRoadmapNode] = Field(default_factory=list)
    relations: list[ExistingRoadmapRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_nodes(self) -> "CurrentRoadmapSnapshot":
        ensure_unique([node.node_id for node in self.nodes], "existing roadmap nodeId")
        ensure_unique(
            [node.canonical_key for node in self.nodes if node.canonical_key is not None],
            "existing canonical capability",
        )
        ensure_unique(
            [
                node.provisional_candidate_id
                for node in self.nodes
                if node.provisional_candidate_id is not None
            ],
            "existing provisional capability",
        )
        ensure_unique(
            [
                f"{node.node_kind.value}:{node.target_ref}"
                for node in self.nodes
                if node.target_ref is not None
            ],
            "existing roadmap target reference",
        )
        ensure_unique(
            [relation.relation_id for relation in self.relations],
            "existing roadmap relationId",
        )
        node_ids = {node.node_id for node in self.nodes}
        for relation in self.relations:
            missing = {relation.from_node_id, relation.to_node_id} - node_ids
            if missing:
                raise ValueError(
                    f"existing relation {relation.relation_id} refers to missing nodes {sorted(missing)}"
                )
        return self


class OpportunityTargetInput(ContractModel):
    opportunity_id: EntityId
    company_name: NonBlank
    position_title: NonBlank
    posting_title: NonBlank | None = None


class RoadmapDraftRequest(ContractModel):
    common_analysis_id: EntityId
    structured_posting: StructuredPosting
    selected_position_id: EntityId
    fit_assessment: FitAssessment
    normalization: CapabilityNormalizationResult
    project_blueprint: CompanyProjectBlueprint
    capability_graph: CapabilityGraphClosure
    user_evidence: UserEvidenceBundle | None = None
    current_roadmap: CurrentRoadmapSnapshot
    opportunity: OpportunityTargetInput

    @model_validator(mode="after")
    def validate_revisions(self) -> "RoadmapDraftRequest":
        if self.selected_position_id not in {
            position.position_id for position in self.structured_posting.positions
        }:
            raise ValueError("selectedPositionId does not exist in structuredPosting")
        if self.fit_assessment.common_analysis_id != self.common_analysis_id:
            raise ValueError("fitAssessment belongs to a different commonAnalysisId")
        if self.normalization.common_analysis_id != self.common_analysis_id:
            raise ValueError("normalization belongs to a different commonAnalysisId")
        if self.fit_assessment.selected_position_id != self.selected_position_id:
            raise ValueError("fitAssessment belongs to a different selectedPositionId")
        if self.normalization.selected_position_id != self.selected_position_id:
            raise ValueError("normalization belongs to a different selectedPositionId")
        if self.project_blueprint.common_analysis_id != self.common_analysis_id:
            raise ValueError("projectBlueprint belongs to a different commonAnalysisId")
        if self.project_blueprint.selected_position_id != self.selected_position_id:
            raise ValueError("projectBlueprint belongs to a different selectedPositionId")
        return self


class RoadmapOperation(ContractModel):
    operation_id: EntityId
    action: RoadmapAction
    node_kind: RoadmapNodeKind = RoadmapNodeKind.CAPABILITY
    canonical_key: CanonicalKey | None = None
    technology_key: CanonicalKey | None = None
    graph_node_version: int | None = Field(default=None, ge=1)
    verification_methods: list[VerificationMethod] = Field(default_factory=list)
    objective: NonBlank | None = None
    excluded_scope: list[NonBlank] = Field(default_factory=list)
    completion_policy: CompletionPolicy = CompletionPolicy.ASSESSMENT
    provisional_candidate_id: EntityId | None = None
    existing_node_id: EntityId | None = None
    target_ref: EntityId | None = None
    title: NonBlank | None = None
    scope_definition: NonBlank | None = None
    section_key: CanonicalKey
    initial_progress_state: RoadmapProgressState = RoadmapProgressState.NOT_STARTED
    progress_evidence_set_id: EntityId | None = None
    preserve_existing_progress: bool = True
    requirement_ids: list[EntityId] = Field(default_factory=list)
    required_for: list[EntityId] = Field(default_factory=list)
    preferred_for: list[EntityId] = Field(default_factory=list)
    section_memberships: list[SectionMembership] = Field(default_factory=list)
    project_spec: ProjectSpec | None = None
    gate_spec: GateSpec | None = None
    opportunity_spec: OpportunitySpec | None = None
    reason: NonBlank

    @model_validator(mode="after")
    def validate_action_fields(self) -> "RoadmapOperation":
        ensure_unique(self.requirement_ids, "roadmap operation requirementId")
        ensure_unique(
            [
                f"{item.section_key}:{item.chapter_key}:{item.target_ref}"
                for item in self.section_memberships
            ],
            "roadmap operation section membership",
        )
        if self.node_kind is not RoadmapNodeKind.CAPABILITY and self.section_memberships:
            raise ValueError("only capability operations may carry sectionMemberships")
        if self.action is RoadmapAction.CREATE_NODE:
            if self.node_kind is not RoadmapNodeKind.CAPABILITY:
                raise ValueError("CREATE_NODE requires CAPABILITY nodeKind")
            if (self.canonical_key is None) == (self.provisional_candidate_id is None):
                raise ValueError(
                    f"{self.action.value} requires exactly one capability identity"
                )
        if self.action is RoadmapAction.REUSE_NODE:
            if self.node_kind is RoadmapNodeKind.CAPABILITY:
                if (self.canonical_key is None) == (self.provisional_candidate_id is None):
                    raise ValueError("reused capability requires exactly one capability identity")
            elif self.target_ref is None:
                raise ValueError("reused non-capability node requires targetRef")
        if self.action is RoadmapAction.REUSE_NODE and self.existing_node_id is None:
            raise ValueError("REUSE_NODE requires existingNodeId")
        if self.action is not RoadmapAction.REUSE_NODE and self.existing_node_id is not None:
            raise ValueError("only REUSE_NODE may carry existingNodeId")
        if self.node_kind is RoadmapNodeKind.CAPABILITY and self.target_ref is not None:
            raise ValueError("capability operations cannot carry targetRef")
        if self.node_kind is not RoadmapNodeKind.CAPABILITY and self.target_ref is None:
            raise ValueError("non-capability operations require targetRef")
        if self.action is RoadmapAction.CREATE_NODE:
            missing = [
                name
                for name, value in {
                    "title": self.title,
                    "scopeDefinition": self.scope_definition,
                }.items()
                if value is None
            ]
            if missing:
                raise ValueError(f"CREATE_NODE requires {', '.join(missing)}")
        expected_payloads = {
            RoadmapAction.CREATE_TARGET_PROJECT: (RoadmapNodeKind.TARGET_PROJECT, self.project_spec),
            RoadmapAction.CREATE_GATE: (RoadmapNodeKind.CAREER_GATE, self.gate_spec),
            RoadmapAction.ADD_OPPORTUNITY: (RoadmapNodeKind.OPPORTUNITY, self.opportunity_spec),
        }
        if self.action in expected_payloads:
            expected_kind, payload = expected_payloads[self.action]
            if self.node_kind is not expected_kind or payload is None or self.title is None:
                raise ValueError(f"{self.action.value} requires {expected_kind.value} payload and title")
        payloads = [self.project_spec, self.gate_spec, self.opportunity_spec]
        if self.action not in expected_payloads and any(item is not None for item in payloads):
            raise ValueError("capability operations cannot carry project, gate, or opportunity payloads")
        if self.action not in {RoadmapAction.REUSE_NODE, RoadmapAction.CREATE_GATE}:
            if self.initial_progress_state is not RoadmapProgressState.NOT_STARTED:
                if (
                    self.action is not RoadmapAction.CREATE_NODE
                    or self.progress_evidence_set_id is None
                ):
                    raise ValueError(
                        "new progress requires a capability node and user evidence set"
                    )
        if (
            self.progress_evidence_set_id is not None
            and self.node_kind is not RoadmapNodeKind.CAPABILITY
        ):
            raise ValueError("only capability operations may carry progressEvidenceSetId")
        return self


class RoadmapRelation(ContractModel):
    relation_id: EntityId
    from_operation_id: EntityId
    to_operation_id: EntityId
    relation_type: RoadmapRelationType
    conditions: list[GraphCondition] = Field(default_factory=list)
    reason: NonBlank

    @model_validator(mode="after")
    def validate_relation(self) -> "RoadmapRelation":
        if self.from_operation_id == self.to_operation_id:
            raise ValueError("roadmap relation cannot refer to itself")
        if (
            self.relation_type is RoadmapRelationType.CONDITIONAL_PREREQUISITE
            and not self.conditions
        ):
            raise ValueError("conditional roadmap relation requires conditions")
        if (
            self.relation_type is not RoadmapRelationType.CONDITIONAL_PREREQUISITE
            and self.conditions
        ):
            raise ValueError("only conditional roadmap relations may carry conditions")
        return self


class ExcludedRequirement(ContractModel):
    requirement_id: EntityId
    reason_code: NonBlank
    explanation: NonBlank


class RoadmapAudit(ContractModel):
    composer_version: NonBlank
    provider: NonBlank
    model: NonBlank
    generation_attempts: int = Field(ge=1)
    generation_duration_ms: int = Field(ge=0)
    graph_content_hash: NonBlank
    preserved_existing_node_ids: list[EntityId] = Field(default_factory=list)


class RoadmapProposal(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    proposal_id: EntityId
    based_on_analysis_id: EntityId
    based_on_fit_assessment_id: EntityId
    based_on_normalization_id: EntityId
    based_on_roadmap_version: int = Field(ge=0)
    selected_position_id: EntityId
    capability_graph_version: NonBlank
    operations: list[RoadmapOperation]
    relations: list[RoadmapRelation] = Field(default_factory=list)
    remove_target_refs: list[EntityId] = Field(default_factory=list)
    excluded_requirements: list[ExcludedRequirement] = Field(default_factory=list)
    audit: RoadmapAudit
    warnings: list[WarningItem] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.DRAFT

    @model_validator(mode="after")
    def validate_operations(self) -> "RoadmapProposal":
        operation_ids = [operation.operation_id for operation in self.operations]
        ensure_unique(operation_ids, "roadmap operation id")
        operation_id_set = set(operation_ids)
        ensure_unique([relation.relation_id for relation in self.relations], "roadmap relation id")
        for relation in self.relations:
            missing = {relation.from_operation_id, relation.to_operation_id} - operation_id_set
            if missing:
                raise ValueError(
                    f"relation {relation.relation_id} refers to unknown operations {sorted(missing)}"
                )
        _reject_blocking_cycles(self.relations)
        ensure_unique(
            [excluded.requirement_id for excluded in self.excluded_requirements],
            "excluded requirement id",
        )
        ensure_unique(self.remove_target_refs, "removed target reference")
        return self


class RoadmapCompilationPreview(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    proposal_id: EntityId
    based_on_roadmap_version: int = Field(ge=0)
    proposed_roadmap_version: int = Field(ge=1)
    snapshot: CurrentRoadmapSnapshot
    created_node_ids: list[EntityId] = Field(default_factory=list)
    reused_node_ids: list[EntityId] = Field(default_factory=list)
    created_relation_ids: list[EntityId] = Field(default_factory=list)
    removed_node_ids: list[EntityId] = Field(default_factory=list)
    removed_relation_ids: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_versions(self) -> "RoadmapCompilationPreview":
        if self.proposed_roadmap_version != self.based_on_roadmap_version + 1:
            raise ValueError("proposedRoadmapVersion must be exactly base version + 1")
        if self.snapshot.roadmap_version != self.proposed_roadmap_version:
            raise ValueError("preview snapshot version must match proposedRoadmapVersion")
        return self


def _reject_blocking_cycles(relations: list[RoadmapRelation]) -> None:
    blocking = {
        RoadmapRelationType.HARD_PREREQUISITE,
        RoadmapRelationType.CONDITIONAL_PREREQUISITE,
        RoadmapRelationType.UNLOCKS_PROJECT,
        RoadmapRelationType.REQUIRES_GATE,
        RoadmapRelationType.UNLOCKS_OPPORTUNITY,
        RoadmapRelationType.CAREER_STAGE_ORDER,
        RoadmapRelationType.POTENTIAL_CAREER_ENTRY,
        RoadmapRelationType.STARTS_EXPERIENCE,
        RoadmapRelationType.SATISFIES_EXPERIENCE_GATE,
    }
    adjacency: dict[str, list[str]] = {}
    for relation in relations:
        if relation.relation_type in blocking:
            adjacency.setdefault(relation.from_operation_id, []).append(relation.to_operation_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("blocking roadmap relations contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for child in adjacency.get(node, []):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in list(adjacency):
        visit(node)
