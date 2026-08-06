from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .common import CanonicalKey, ContractModel, EntityId, NonBlank, ensure_unique
from .normalization import CapabilityKind


Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class CapabilityRelationType(StrEnum):
    HARD_PREREQUISITE = "HARD_PREREQUISITE"
    RECOMMENDED_FOUNDATION = "RECOMMENDED_FOUNDATION"
    CONDITIONAL_PREREQUISITE = "CONDITIONAL_PREREQUISITE"
    DEEPENS = "DEEPENS"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"


class GraphReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"
    REJECTED = "REJECTED"


class GraphConfidenceBand(StrEnum):
    VERIFIED = "VERIFIED"
    STRONG_INFERENCE = "STRONG_INFERENCE"
    WEAK_INFERENCE = "WEAK_INFERENCE"
    UNKNOWN = "UNKNOWN"


class GraphSourceType(StrEnum):
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    STANDARD = "STANDARD"
    USER_PROVIDED_POSTING = "USER_PROVIDED_POSTING"
    INTERNAL_DESIGN = "INTERNAL_DESIGN"
    ENGINEERING_PUBLICATION = "ENGINEERING_PUBLICATION"
    OTHER = "OTHER"


class GraphSnapshotScope(StrEnum):
    FULL_DOCUMENT = "FULL_DOCUMENT"
    EXCERPT = "EXCERPT"
    LINK_ONLY = "LINK_ONLY"
    INTERNAL_RECORD = "INTERNAL_RECORD"


class CapabilityNodeType(StrEnum):
    CONCEPT = "CONCEPT"
    PERFORMANCE = "PERFORMANCE"


class VerificationMethod(StrEnum):
    EXPLAIN = "EXPLAIN"
    IMPLEMENT = "IMPLEMENT"
    TEST = "TEST"
    DEBUG = "DEBUG"
    MEASURE = "MEASURE"
    DOCUMENT = "DOCUMENT"


class CompletionPolicy(StrEnum):
    SELF_CONFIRM = "SELF_CONFIRM"
    ASSESSMENT = "ASSESSMENT"


class GraphConditionKind(StrEnum):
    LANGUAGE_CHOICE = "LANGUAGE_CHOICE"
    ROLE_CONTEXT = "ROLE_CONTEXT"
    TARGET_SCOPE = "TARGET_SCOPE"
    PROJECT_CONTEXT = "PROJECT_CONTEXT"
    OTHER = "OTHER"


class ProjectNecessity(StrEnum):
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"
    EXTENSION = "EXTENSION"


class GraphConfidence(ContractModel):
    band: GraphConfidenceBand
    reason: NonBlank


class GraphSource(ContractModel):
    source_id: EntityId
    title: NonBlank
    uri: NonBlank
    publisher: NonBlank
    source_type: GraphSourceType
    retrieved_at: datetime
    evidence_summary: NonBlank
    snapshot_scope: GraphSnapshotScope
    content_hash: Sha256Digest
    license_name: NonBlank | None = None


class CapabilityGraphNode(ContractModel):
    canonical_key: CanonicalKey
    technology_key: CanonicalKey
    display_name: NonBlank
    node_type: CapabilityNodeType
    kind: CapabilityKind
    objective: NonBlank
    scope_definition: NonBlank
    excluded_scope: list[NonBlank] = Field(default_factory=list)
    verification_methods: list[VerificationMethod] = Field(min_length=1)
    completion_policy: CompletionPolicy = CompletionPolicy.ASSESSMENT
    aliases: list[NonBlank] = Field(default_factory=list)
    confidence: GraphConfidence
    review_status: GraphReviewStatus
    version: int = Field(ge=1)
    source_ids: list[EntityId] = Field(min_length=1)


class CapabilityGraphCatalog(ContractModel):
    contract_version: str = "jobis.capability-graph.v1alpha1"
    graph_version: NonBlank
    content_hash: Sha256Digest
    capabilities: list[CapabilityGraphNode]

    @model_validator(mode="after")
    def validate_catalog(self) -> "CapabilityGraphCatalog":
        ensure_unique(
            [item.canonical_key for item in self.capabilities],
            "capability graph catalog key",
        )
        unapproved = [
            item.canonical_key
            for item in self.capabilities
            if item.review_status is not GraphReviewStatus.APPROVED
        ]
        if unapproved:
            raise ValueError(f"capability graph catalog contains unapproved nodes: {unapproved}")
        return self


class GraphCondition(ContractModel):
    kind: GraphConditionKind
    key: NonBlank
    accepted_values: list[NonBlank] = Field(min_length=1)


class ActiveGraphCondition(ContractModel):
    kind: GraphConditionKind
    key: NonBlank
    value: NonBlank


class CapabilityGraphEdge(ContractModel):
    relation_id: EntityId
    from_capability_key: CanonicalKey
    to_capability_key: CanonicalKey
    relation_type: CapabilityRelationType
    conditions: list[GraphCondition] = Field(default_factory=list)
    reason: NonBlank
    confidence: GraphConfidence
    review_status: GraphReviewStatus
    version: int = Field(ge=1)
    source_ids: list[EntityId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_conditions(self) -> "CapabilityGraphEdge":
        if self.from_capability_key == self.to_capability_key:
            raise ValueError("capability graph edge cannot refer to itself")
        if (
            self.relation_type is CapabilityRelationType.CONDITIONAL_PREREQUISITE
            and not self.conditions
        ):
            raise ValueError("CONDITIONAL_PREREQUISITE requires conditions")
        if (
            self.relation_type is not CapabilityRelationType.CONDITIONAL_PREREQUISITE
            and self.conditions
        ):
            raise ValueError("only CONDITIONAL_PREREQUISITE may carry conditions")
        return self


class CapabilityGraphQueryRequest(ContractModel):
    target_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    project_task_keys: list[CanonicalKey] = Field(default_factory=list)
    boundary_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    project_necessities: list[ProjectNecessity] = Field(
        default_factory=lambda: [ProjectNecessity.REQUIRED]
    )
    include_relation_types: list[CapabilityRelationType] = Field(
        default_factory=lambda: [
            CapabilityRelationType.HARD_PREREQUISITE,
            CapabilityRelationType.RECOMMENDED_FOUNDATION,
        ]
    )
    active_conditions: list[ActiveGraphCondition] = Field(default_factory=list)
    requested_graph_version: NonBlank | None = None
    max_depth: int = Field(default=20, ge=1, le=50)
    include_sources: bool = True

    @model_validator(mode="after")
    def validate_keys(self) -> "CapabilityGraphQueryRequest":
        if not self.target_capability_keys and not self.project_task_keys:
            raise ValueError("targetCapabilityKeys or projectTaskKeys is required")
        ensure_unique(self.target_capability_keys, "target capability key")
        ensure_unique(self.project_task_keys, "project task key")
        ensure_unique(self.boundary_capability_keys, "boundary capability key")
        traversable = {
            CapabilityRelationType.HARD_PREREQUISITE,
            CapabilityRelationType.RECOMMENDED_FOUNDATION,
            CapabilityRelationType.CONDITIONAL_PREREQUISITE,
        }
        invalid = set(self.include_relation_types) - traversable
        if invalid:
            raise ValueError(
                "prerequisite closure cannot traverse relation types: "
                + ", ".join(sorted(item.value for item in invalid))
            )
        return self


class TargetOrigin(ContractModel):
    capability_key: CanonicalKey
    origin_type: NonBlank
    project_task_keys: list[CanonicalKey] = Field(default_factory=list)
    necessities: list[ProjectNecessity] = Field(default_factory=list)


class LearningLayer(ContractModel):
    depth: int = Field(ge=0)
    capability_keys: list[CanonicalKey]


class GraphWarning(ContractModel):
    code: NonBlank
    message: NonBlank


class CapabilityGraphClosure(ContractModel):
    contract_version: str = "jobis.capability-graph.v1alpha1"
    graph_version: NonBlank
    generated_at: datetime
    content_hash: Sha256Digest
    target_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    resolved_project_task_keys: list[CanonicalKey] = Field(default_factory=list)
    boundary_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    target_origins: list[TargetOrigin] = Field(default_factory=list)
    nodes: list[CapabilityGraphNode]
    edges: list[CapabilityGraphEdge]
    sources: list[GraphSource]
    learning_order: list[LearningLayer] = Field(default_factory=list)
    warnings: list[GraphWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "CapabilityGraphClosure":
        node_keys = [node.canonical_key for node in self.nodes]
        relation_ids = [edge.relation_id for edge in self.edges]
        source_ids = [source.source_id for source in self.sources]
        ensure_unique(node_keys, "capability graph node")
        ensure_unique(relation_ids, "capability graph relation")
        ensure_unique(source_ids, "capability graph source")
        node_key_set = set(node_keys)
        source_id_set = set(source_ids)
        missing_targets = set(self.target_capability_keys) - node_key_set
        missing_boundaries = set(self.boundary_capability_keys) - node_key_set
        if missing_targets:
            raise ValueError(f"graph closure is missing target nodes: {sorted(missing_targets)}")
        if missing_boundaries:
            raise ValueError(
                f"graph closure is missing boundary nodes: {sorted(missing_boundaries)}"
            )
        for node in self.nodes:
            if node.review_status is not GraphReviewStatus.APPROVED:
                raise ValueError(f"graph closure contains unapproved node {node.canonical_key}")
            missing_sources = set(node.source_ids) - source_id_set
            if missing_sources:
                raise ValueError(
                    f"node {node.canonical_key} has unknown source IDs: {sorted(missing_sources)}"
                )
        for edge in self.edges:
            if edge.review_status is not GraphReviewStatus.APPROVED:
                raise ValueError(f"graph closure contains unapproved relation {edge.relation_id}")
            missing_nodes = {
                edge.from_capability_key,
                edge.to_capability_key,
            } - node_key_set
            if missing_nodes:
                raise ValueError(
                    f"relation {edge.relation_id} has unknown nodes: {sorted(missing_nodes)}"
                )
            missing_sources = set(edge.source_ids) - source_id_set
            if missing_sources:
                raise ValueError(
                    f"relation {edge.relation_id} has unknown source IDs: {sorted(missing_sources)}"
                )
        ordered = [key for layer in self.learning_order for key in layer.capability_keys]
        ensure_unique(ordered, "learning order capability")
        missing_ordered = set(ordered) - node_key_set
        if missing_ordered:
            raise ValueError(f"learning order has unknown nodes: {sorted(missing_ordered)}")
        _reject_hard_prerequisite_cycles(self.edges)
        return self


def _reject_hard_prerequisite_cycles(edges: list[CapabilityGraphEdge]) -> None:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation_type is CapabilityRelationType.HARD_PREREQUISITE:
            adjacency.setdefault(edge.from_capability_key, []).append(edge.to_capability_key)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("HARD_PREREQUISITE relations contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for child in adjacency.get(node, []):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for key in list(adjacency):
        visit(key)
