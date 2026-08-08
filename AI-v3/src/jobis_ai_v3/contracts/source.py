from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, EntityId, NonBlank, WarningItem, ensure_unique


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class SourceInputType(StrEnum):
    URL = "URL"
    IMAGE = "IMAGE"
    TEXT = "TEXT"


class SourceEntryPoint(StrEnum):
    CHAT = "CHAT"
    POSTINGS_PAGE = "POSTINGS_PAGE"
    INTERNAL = "INTERNAL"


class ExtractionMethod(StrEnum):
    DIRECT_TEXT = "DIRECT_TEXT"
    HTML = "HTML"
    IFRAME = "IFRAME"
    OCR = "OCR"
    VLM = "VLM"
    USER_PASTE = "USER_PASTE"


class SourceStatus(StrEnum):
    RECEIVED = "RECEIVED"
    FETCHING = "FETCHING"
    EXTRACTED = "EXTRACTED"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class VerifiedBy(StrEnum):
    USER = "USER"
    OPERATOR = "OPERATOR"
    TRUSTED_DIRECT_SOURCE = "TRUSTED_DIRECT_SOURCE"


class CorrectionReason(StrEnum):
    OCR_CORRECTION = "OCR_CORRECTION"
    STRUCTURE_CORRECTION = "STRUCTURE_CORRECTION"
    MISSING_TEXT = "MISSING_TEXT"
    DUPLICATE_TEXT = "DUPLICATE_TEXT"
    OTHER = "OTHER"


class SourceLocator(ContractModel):
    page: int | None = Field(default=None, ge=1)
    image_index: int | None = Field(default=None, ge=0)
    bounding_box: tuple[float, float, float, float] | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SourceLocator":
        if self.bounding_box is not None:
            x1, y1, x2, y2 = self.bounding_box
            if not all(0.0 <= value <= 1.0 for value in self.bounding_box):
                raise ValueError("boundingBox coordinates must be normalized between 0 and 1")
            if x1 >= x2 or y1 >= y2:
                raise ValueError("boundingBox must have positive width and height")
        if self.char_start is not None or self.char_end is not None:
            if self.char_start is None or self.char_end is None:
                raise ValueError("charStart and charEnd must be provided together")
            if self.char_start >= self.char_end:
                raise ValueError("charStart must be smaller than charEnd")
        return self


class ExtractionSegment(ContractModel):
    segment_id: EntityId
    text: NonBlank
    method: ExtractionMethod
    source_locator: SourceLocator | None = None
    confidence: Confidence | None = None
    overlap_group: NonBlank | None = None
    warnings: list[WarningItem] = Field(default_factory=list)


class SourceDocument(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    source_document_id: EntityId
    input_type: SourceInputType
    original_input: NonBlank
    canonical_url: NonBlank | None = None
    captured_at: datetime
    extraction_revision: int = Field(ge=1)
    extractor_version: NonBlank
    canonical_input_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    raw_text: NonBlank
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    segments: list[ExtractionSegment]
    warnings: list[WarningItem] = Field(default_factory=list)
    status: SourceStatus

    @model_validator(mode="after")
    def validate_document(self) -> "SourceDocument":
        ensure_unique([segment.segment_id for segment in self.segments], "segmentId")
        if self.input_type is SourceInputType.URL and self.canonical_url is None:
            raise ValueError("URL source documents require canonicalUrl")
        if self.status in {SourceStatus.EXTRACTED, SourceStatus.AWAITING_VERIFICATION, SourceStatus.VERIFIED}:
            if not self.segments:
                raise ValueError("extracted source documents require at least one segment")
        return self


class PostingCorrection(ContractModel):
    field: NonBlank
    before: str
    after: NonBlank
    reason: CorrectionReason


class VerifiedPostingSnapshot(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    verified_snapshot_id: EntityId
    source_document_id: EntityId
    source_revision: int = Field(ge=1)
    previous_snapshot_id: EntityId | None = None
    verified_text: NonBlank
    evidence_segments: list[ExtractionSegment] = Field(min_length=1)
    corrections: list[PostingCorrection] = Field(default_factory=list)
    verified_by: VerifiedBy
    verified_at: datetime
    snapshot_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_evidence(self) -> "VerifiedPostingSnapshot":
        ensure_unique([segment.segment_id for segment in self.evidence_segments], "segmentId")
        for segment in self.evidence_segments:
            if segment.text not in self.verified_text:
                raise ValueError(
                    f"verified evidence segment {segment.segment_id} is not present in verifiedText"
                )
        return self


class SourceAcquisitionRequest(ContractModel):
    input_type: SourceInputType
    entry_point: SourceEntryPoint
    extraction_revision: int = Field(default=1, ge=1)
    text: NonBlank | None = None
    url: NonBlank | None = None
    image_base64: NonBlank | None = None
    image_media_type: Literal["image/png", "image/jpeg", "image/webp"] | None = None
    original_filename: NonBlank | None = None

    @model_validator(mode="after")
    def validate_input(self) -> "SourceAcquisitionRequest":
        supplied = {
            SourceInputType.TEXT: self.text,
            SourceInputType.URL: self.url,
            SourceInputType.IMAGE: self.image_base64,
        }
        if supplied[self.input_type] is None:
            raise ValueError(f"{self.input_type.value} input is missing its matching payload")
        if sum(value is not None for value in supplied.values()) != 1:
            raise ValueError("exactly one source payload must be supplied")
        if self.input_type is SourceInputType.IMAGE:
            if self.image_media_type is None or self.original_filename is None:
                raise ValueError("IMAGE inputs require imageMediaType and originalFilename")
        elif self.image_media_type is not None or self.original_filename is not None:
            raise ValueError("image metadata is only valid for IMAGE inputs")
        return self


class SourceVerificationRequest(ContractModel):
    source_document: SourceDocument
    verified_text: NonBlank
    corrections: list[PostingCorrection] = Field(default_factory=list)
    verified_by: Literal[VerifiedBy.USER, VerifiedBy.OPERATOR]
    previous_snapshot_id: EntityId | None = None

    @model_validator(mode="after")
    def validate_verification(self) -> "SourceVerificationRequest":
        if self.source_document.status not in {
            SourceStatus.EXTRACTED,
            SourceStatus.AWAITING_VERIFICATION,
            SourceStatus.VERIFIED,
        }:
            raise ValueError("only successfully extracted documents can be verified")
        if self.verified_text != self.source_document.raw_text and not self.corrections:
            raise ValueError("changed verifiedText requires at least one correction")
        return self


class SourceVerificationResult(ContractModel):
    source_document: SourceDocument
    verified_snapshot: VerifiedPostingSnapshot
