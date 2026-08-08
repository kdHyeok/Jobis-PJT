from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobis_ai_v3.contracts.source import (
    ExtractionMethod,
    ExtractionSegment,
    SourceDocument,
    SourceInputType,
    SourceLocator,
    SourceStatus,
)


NOW = datetime(2026, 8, 4, tzinfo=UTC)


def test_contract_serializes_camel_case(source_document: SourceDocument) -> None:
    payload = source_document.model_dump(mode="json", by_alias=True)

    assert payload["sourceDocumentId"] == "src-1"
    assert payload["extractionRevision"] == 1
    assert "source_document_id" not in payload


def test_url_source_requires_canonical_url() -> None:
    with pytest.raises(ValidationError, match="canonicalUrl"):
        SourceDocument(
            source_document_id="src-1",
            input_type=SourceInputType.URL,
            original_input="https://example.invalid/posting/1",
            captured_at=NOW,
            extraction_revision=1,
            extractor_version="source-extractor-3.0.0",
            canonical_input_hash="sha256:" + "c" * 64,
            raw_text="공고 원문",
            content_hash="sha256:" + "a" * 64,
            segments=[ExtractionSegment(segment_id="seg-1", text="공고 원문", method=ExtractionMethod.HTML)],
            status=SourceStatus.EXTRACTED,
        )


def test_extracted_source_requires_segment() -> None:
    with pytest.raises(ValidationError, match="at least one segment"):
        SourceDocument(
            source_document_id="src-1",
            input_type=SourceInputType.TEXT,
            original_input="공고 원문",
            captured_at=NOW,
            extraction_revision=1,
            extractor_version="source-extractor-3.0.0",
            canonical_input_hash="sha256:" + "c" * 64,
            raw_text="공고 원문",
            content_hash="sha256:" + "a" * 64,
            segments=[],
            status=SourceStatus.EXTRACTED,
        )


def test_duplicate_segment_ids_are_rejected(source_document: SourceDocument) -> None:
    payload = source_document.model_dump()
    payload["segments"].append(payload["segments"][0])

    with pytest.raises(ValidationError, match="duplicate segmentId"):
        SourceDocument.model_validate(payload)


def test_invalid_normalized_bounding_box_is_rejected() -> None:
    with pytest.raises(ValidationError, match="positive width"):
        SourceLocator(bounding_box=(0.9, 0.1, 0.2, 0.5))


def test_unknown_fields_are_rejected(source_document: SourceDocument) -> None:
    payload = source_document.model_dump()
    payload["inventedResult"] = "success"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceDocument.model_validate(payload)
