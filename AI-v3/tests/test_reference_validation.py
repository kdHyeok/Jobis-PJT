from __future__ import annotations

import pytest

from jobis_ai_v3.contracts.posting import StructuredPosting
from jobis_ai_v3.contracts.validation import (
    ContractReferenceError,
    validate_posting_evidence,
    validate_snapshot_source,
)


def test_snapshot_matches_source(source_document, verified_snapshot) -> None:
    validate_snapshot_source(verified_snapshot, source_document)


def test_snapshot_revision_mismatch_is_rejected(source_document, verified_snapshot) -> None:
    snapshot = verified_snapshot.model_copy(update={"source_revision": 2})

    with pytest.raises(ContractReferenceError, match="extraction revision"):
        validate_snapshot_source(snapshot, source_document)


def test_posting_evidence_must_exist(source_document, verified_snapshot, structured_posting) -> None:
    payload = structured_posting.model_dump()
    payload["positions"][0]["requirements"][0]["evidence_ids"] = ["seg-missing"]
    posting = StructuredPosting.model_validate(payload)

    with pytest.raises(ContractReferenceError, match="unknown verified evidence segments"):
        validate_posting_evidence(posting, source_document, verified_snapshot)


def test_valid_posting_references_pass(source_document, verified_snapshot, structured_posting) -> None:
    validate_snapshot_source(verified_snapshot, source_document)
    validate_posting_evidence(structured_posting, source_document, verified_snapshot)
