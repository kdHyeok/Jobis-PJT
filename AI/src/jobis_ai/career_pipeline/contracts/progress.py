from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import ContractModel, EntityId, NonBlank, WarningItem


class AnalysisStage(StrEnum):
    SOURCE_FETCH = "SOURCE_FETCH"
    SOURCE_EXTRACT = "SOURCE_EXTRACT"
    AWAITING_SOURCE_VERIFICATION = "AWAITING_SOURCE_VERIFICATION"
    POSITION_DISCOVERY = "POSITION_DISCOVERY"
    POSTING_DETAIL = "POSTING_DETAIL"
    POSTING_STRUCTURE = "POSTING_STRUCTURE"
    AWAITING_POSITION_SELECTION = "AWAITING_POSITION_SELECTION"
    AWAITING_EXPERIENCE_TRACK_SELECTION = "AWAITING_EXPERIENCE_TRACK_SELECTION"
    AWAITING_POSTING_CONFIRMATION = "AWAITING_POSTING_CONFIRMATION"
    AWAITING_USER_EVIDENCE = "AWAITING_USER_EVIDENCE"
    PROFILE_ASSEMBLY = "PROFILE_ASSEMBLY"
    FIT_ANALYSIS = "FIT_ANALYSIS"
    CAPABILITY_NORMALIZATION = "CAPABILITY_NORMALIZATION"
    PROJECT_PLANNING = "PROJECT_PLANNING"
    CAPABILITY_GRAPH_LOOKUP = "CAPABILITY_GRAPH_LOOKUP"
    ROADMAP_PROPOSAL = "ROADMAP_PROPOSAL"
    CONTRACT_VALIDATION = "CONTRACT_VALIDATION"
    RESULT_ASSEMBLY = "RESULT_ASSEMBLY"


class ProgressStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProgressEvent(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    event_id: EntityId
    job_id: EntityId
    sequence: int = Field(ge=0)
    stage: AnalysisStage
    status: ProgressStatus
    label: NonBlank
    detail: NonBlank | None = None
    occurred_at: datetime
    elapsed_ms: int = Field(ge=0)
    stage_duration_ms: int | None = Field(default=None, ge=0)
    partial_result: dict[str, Any] | None = None
    warnings: list[WarningItem] = Field(default_factory=list)


class CapabilityFlag(ContractModel):
    name: NonBlank
    available: bool
    reason: NonBlank | None = None


class CapabilitiesResponse(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    service_version: NonBlank
    capabilities: list[CapabilityFlag]
