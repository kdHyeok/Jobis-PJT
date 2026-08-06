from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from .capability_graph import CapabilityGraphClosure
from .common import ContractModel, EntityId, NonBlank
from .errors import ErrorDetail
from .fit import FitAnalysisResult, UserEvidenceBundle
from .normalization import CapabilityNormalizationResult
from .posting import (
    ApprovedRoleCatalogEntry,
    AtomicRequirement,
    ExperienceRequirement,
    RequirementObligation,
    Responsibility,
    StructuredPosting,
)
from .project_planning import CompanyProjectBlueprint
from .progress import ProgressEvent
from .resolution import ClarificationAnswer, ExperienceTrack, PostingResolutionResult
from .roadmap import CurrentRoadmapSnapshot, RoadmapProposal
from .source import SourceDocument, SourceStatus, VerifiedPostingSnapshot


class PipelineStatus(StrEnum):
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    AWAITING_POSTING_CONFIRMATION = "AWAITING_POSTING_CONFIRMATION"
    AWAITING_USER_EVIDENCE = "AWAITING_USER_EVIDENCE"
    COMPLETED = "COMPLETED"


class PipelineStreamType(StrEnum):
    PROGRESS = "PROGRESS"
    RESULT = "RESULT"
    ERROR = "ERROR"


class PostingReview(ContractModel):
    """The selected slice of a posting that a user confirms before planning.

    The original verified text remains attached for audit and correction.  The
    lists below are a deterministic projection of StructuredPosting, not a
    second LLM summary.
    """

    review_id: EntityId
    verified_snapshot_id: EntityId
    company_name: NonBlank | None = None
    posting_title: NonBlank | None = None
    selected_position_id: EntityId
    position_title: NonBlank
    selected_experience_track: ExperienceTrack | None = None
    experience: ExperienceRequirement
    responsibilities: list[Responsibility] = Field(default_factory=list)
    responsibility_requirements: list[AtomicRequirement] = Field(default_factory=list)
    required_requirements: list[AtomicRequirement] = Field(default_factory=list)
    preferred_requirements: list[AtomicRequirement] = Field(default_factory=list)
    informational_requirements: list[AtomicRequirement] = Field(default_factory=list)
    original_text: NonBlank

    @model_validator(mode="after")
    def validate_obligations(self) -> "PostingReview":
        expected = {
            RequirementObligation.REQUIRED: self.required_requirements,
            RequirementObligation.PREFERRED: self.preferred_requirements,
            RequirementObligation.INFORMATIONAL: self.informational_requirements,
        }
        for obligation, requirements in expected.items():
            if any(item.obligation is not obligation for item in requirements):
                raise ValueError(
                    f"{obligation.value} posting review list contains another obligation"
                )
        return self


class AnalysisPipelineRequest(ContractModel):
    job_id: EntityId
    common_analysis_id: EntityId
    as_of_date: date
    source_document: SourceDocument
    verified_snapshot: VerifiedPostingSnapshot
    structured_posting_checkpoint: StructuredPosting | None = None
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list)
    user_evidence: UserEvidenceBundle
    current_roadmap: CurrentRoadmapSnapshot
    opportunity_id: EntityId
    require_posting_confirmation: bool = False
    confirmed_posting_review_id: EntityId | None = None
    skip_remaining_evidence_questions: bool = False
    requested_graph_version: NonBlank | None = None
    approved_role_catalog: list[ApprovedRoleCatalogEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_revision(self) -> "AnalysisPipelineRequest":
        if self.source_document.status is not SourceStatus.VERIFIED:
            raise ValueError("analysis pipeline requires a VERIFIED sourceDocument")
        if self.source_document.source_document_id != self.verified_snapshot.source_document_id:
            raise ValueError("sourceDocument and verifiedSnapshot belong to different sources")
        if self.source_document.extraction_revision != self.verified_snapshot.source_revision:
            raise ValueError("sourceDocument and verifiedSnapshot revisions do not match")
        if (
            self.structured_posting_checkpoint is not None
            and self.structured_posting_checkpoint.verified_snapshot_id
            != self.verified_snapshot.verified_snapshot_id
        ):
            raise ValueError(
                "structuredPostingCheckpoint belongs to a different verified snapshot"
            )
        ambiguity_ids = [answer.ambiguity_id for answer in self.clarification_answers]
        if len(ambiguity_ids) != len(set(ambiguity_ids)):
            raise ValueError("clarificationAnswers contain duplicate ambiguityId values")
        return self


class AnalysisPipelineResult(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    job_id: EntityId
    common_analysis_id: EntityId
    status: PipelineStatus
    structured_posting: StructuredPosting
    resolution: PostingResolutionResult
    posting_review: PostingReview | None = None
    fit: FitAnalysisResult | None = None
    normalization: CapabilityNormalizationResult | None = None
    project_blueprint: CompanyProjectBlueprint | None = None
    capability_graph: CapabilityGraphClosure | None = None
    roadmap_proposal: RoadmapProposal | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "AnalysisPipelineResult":
        downstream = [
            self.fit,
            self.normalization,
            self.project_blueprint,
            self.capability_graph,
            self.roadmap_proposal,
        ]
        if self.status is PipelineStatus.AWAITING_CLARIFICATION:
            if self.posting_review is not None or any(item is not None for item in downstream):
                raise ValueError("AWAITING_CLARIFICATION cannot carry review or downstream results")
        if self.status is PipelineStatus.AWAITING_POSTING_CONFIRMATION:
            if self.posting_review is None:
                raise ValueError("AWAITING_POSTING_CONFIRMATION requires postingReview")
            if any(item is not None for item in downstream):
                raise ValueError(
                    "AWAITING_POSTING_CONFIRMATION cannot carry downstream analysis results"
                )
        if self.status is PipelineStatus.AWAITING_USER_EVIDENCE:
            if self.posting_review is None:
                raise ValueError("AWAITING_USER_EVIDENCE requires postingReview")
            if self.fit is None or self.fit.assessment is not None:
                raise ValueError("AWAITING_USER_EVIDENCE requires a waiting fit result")
            if self.roadmap_proposal is not None:
                raise ValueError("AWAITING_USER_EVIDENCE cannot carry a finalized roadmap proposal")
            project_outputs = [
                self.normalization,
                self.project_blueprint,
                self.capability_graph,
            ]
            if any(item is not None for item in project_outputs) and any(
                item is None for item in project_outputs
            ):
                raise ValueError(
                    "AWAITING_USER_EVIDENCE must carry either all or none of the project outputs"
                )
        if self.status is PipelineStatus.COMPLETED:
            if self.posting_review is None:
                raise ValueError("COMPLETED requires postingReview")
            if any(item is None for item in downstream):
                raise ValueError("COMPLETED requires every downstream result")
            if self.fit is None or self.fit.assessment is None:
                raise ValueError("COMPLETED requires a completed fit assessment")
        return self


class PipelineStreamEvent(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    type: PipelineStreamType
    sequence: int = Field(ge=0)
    progress: ProgressEvent | None = None
    result: AnalysisPipelineResult | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "PipelineStreamEvent":
        payloads = [self.progress, self.result, self.error]
        if sum(item is not None for item in payloads) != 1:
            raise ValueError("pipeline stream events require exactly one payload")
        expected = {
            PipelineStreamType.PROGRESS: self.progress,
            PipelineStreamType.RESULT: self.result,
            PipelineStreamType.ERROR: self.error,
        }
        if expected[self.type] is None:
            raise ValueError(f"{self.type.value} stream event carries the wrong payload")
        return self
