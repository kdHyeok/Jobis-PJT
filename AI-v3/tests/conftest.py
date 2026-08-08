from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from jobis_ai_v3.contracts.posting import (
    AtomicRequirement,
    CompanyCandidate,
    ExperienceKind,
    ExperienceRequirement,
    NormalizationStatus,
    Position,
    RequirementCategory,
    RequirementObligation,
    RoleCandidate,
    RoleStatus,
    StructuredPosting,
)
from jobis_ai_v3.contracts.source import (
    ExtractionMethod,
    ExtractionSegment,
    SourceDocument,
    SourceInputType,
    SourceStatus,
    VerifiedBy,
    VerifiedPostingSnapshot,
)


NOW = datetime(2026, 8, 4, 3, 0, tzinfo=UTC)


def sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def source_document() -> SourceDocument:
    raw_text = "예시회사 웹 백엔드 개발자. 신입. Java와 Spring Boot 경험 필수."
    return SourceDocument(
        source_document_id="src-1",
        input_type=SourceInputType.URL,
        original_input="https://example.invalid/posting/1",
        canonical_url="https://example.invalid/posting/1",
        captured_at=NOW,
        extraction_revision=1,
        extractor_version="source-extractor-3.0.0",
        canonical_input_hash="sha256:" + "c" * 64,
        raw_text=raw_text,
        content_hash=sha256(raw_text),
        segments=[
            ExtractionSegment(segment_id="seg-company", text="예시회사", method=ExtractionMethod.HTML),
            ExtractionSegment(segment_id="seg-title", text="웹 백엔드 개발자", method=ExtractionMethod.HTML),
            ExtractionSegment(segment_id="seg-role", text="백엔드 개발", method=ExtractionMethod.HTML),
            ExtractionSegment(segment_id="seg-exp", text="신입", method=ExtractionMethod.HTML),
            ExtractionSegment(
                segment_id="seg-req",
                text="Java와 Spring Boot 경험 필수",
                method=ExtractionMethod.HTML,
            ),
        ],
        status=SourceStatus.AWAITING_VERIFICATION,
    )


@pytest.fixture
def verified_snapshot(source_document: SourceDocument) -> VerifiedPostingSnapshot:
    return VerifiedPostingSnapshot(
        verified_snapshot_id="snapshot-1",
        source_document_id=source_document.source_document_id,
        source_revision=source_document.extraction_revision,
        verified_text=source_document.raw_text,
        evidence_segments=source_document.segments,
        verified_by=VerifiedBy.USER,
        verified_at=NOW,
        snapshot_hash=sha256(f"{source_document.content_hash}\n{source_document.raw_text}"),
    )


@pytest.fixture
def structured_posting(verified_snapshot: VerifiedPostingSnapshot) -> StructuredPosting:
    requirement = AtomicRequirement(
        requirement_id="req-java",
        source_text="Java와 Spring Boot 경험 필수",
        atomic_text="Java 개발 경험",
        obligation=RequirementObligation.REQUIRED,
        category=RequirementCategory.TECHNOLOGY,
        applies_to_position_ids=["pos-backend"],
        evidence_ids=["seg-req"],
        confidence=0.94,
        normalization_status=NormalizationStatus.PENDING,
    )
    return StructuredPosting(
        analysis_version="posting-interpreter-3.0.0",
        verified_snapshot_id=verified_snapshot.verified_snapshot_id,
        company=CompanyCandidate(
            display_name="예시회사",
            evidence_ids=["seg-company"],
            confidence=0.9,
        ),
        posting_title="웹 백엔드 개발자",
        posting_title_evidence_ids=["seg-title"],
        positions=[
            Position(
                position_id="pos-backend",
                source_title="백엔드",
                role=RoleCandidate(
                    family="SOFTWARE_ENGINEERING",
                    specialization="WEB_BACKEND",
                    canonical_role_id="role.web_backend",
                    status=RoleStatus.CANDIDATE,
                    confidence=0.96,
                    evidence_ids=["seg-role"],
                ),
                experience=ExperienceRequirement(
                    kind=ExperienceKind.NEW_GRADUATE,
                    confidence=0.99,
                    evidence_ids=["seg-exp"],
                ),
                requirements=[requirement],
            )
        ],
    )
