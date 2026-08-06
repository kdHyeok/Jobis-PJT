from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .posting import StructuredPosting, all_posting_evidence_ids
from .source import SourceDocument, VerifiedPostingSnapshot


@dataclass(frozen=True, slots=True)
class ReferenceIssue:
    code: str
    message: str


class ContractReferenceError(ValueError):
    def __init__(self, issues: list[ReferenceIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in issues))


def validate_snapshot_source(
    snapshot: VerifiedPostingSnapshot,
    source: SourceDocument,
) -> None:
    issues: list[ReferenceIssue] = []
    if snapshot.source_document_id != source.source_document_id:
        issues.append(ReferenceIssue("SNAPSHOT_SOURCE_MISMATCH", "snapshot refers to another source document"))
    if snapshot.source_revision != source.extraction_revision:
        issues.append(ReferenceIssue("SNAPSHOT_REVISION_MISMATCH", "snapshot refers to another extraction revision"))
    expected_content_hash = _sha256(source.raw_text)
    if source.content_hash != expected_content_hash:
        issues.append(ReferenceIssue("SOURCE_CONTENT_HASH_MISMATCH", "source content hash is invalid"))
    expected_snapshot_hash = _sha256(f"{source.content_hash}\n{snapshot.verified_text}")
    if snapshot.snapshot_hash != expected_snapshot_hash:
        issues.append(ReferenceIssue("SNAPSHOT_HASH_MISMATCH", "verified snapshot hash is invalid"))
    if issues:
        raise ContractReferenceError(issues)


def validate_posting_evidence(
    posting: StructuredPosting,
    source: SourceDocument,
    snapshot: VerifiedPostingSnapshot,
) -> None:
    issues: list[ReferenceIssue] = []
    if posting.verified_snapshot_id != snapshot.verified_snapshot_id:
        issues.append(ReferenceIssue("POSTING_SNAPSHOT_MISMATCH", "posting refers to another verified snapshot"))

    evidence_by_id = {segment.segment_id: segment for segment in snapshot.evidence_segments}
    available_evidence = set(evidence_by_id)
    missing = sorted(all_posting_evidence_ids(posting) - available_evidence)
    if missing:
        issues.append(
            ReferenceIssue(
                "UNKNOWN_EVIDENCE_REFERENCE",
                f"posting refers to unknown verified evidence segments: {missing}",
            )
        )
    if not missing:
        if posting.company is not None:
            _require_supported_text(
                issues,
                evidence_by_id,
                posting.company.display_name,
                posting.company.evidence_ids,
                "company.displayName",
            )
        if posting.posting_title is not None:
            _require_supported_text(
                issues,
                evidence_by_id,
                posting.posting_title,
                posting.posting_title_evidence_ids,
                "postingTitle",
            )
        for position in posting.positions:
            _require_supported_text(
                issues,
                evidence_by_id,
                position.source_title,
                position.role.evidence_ids,
                f"position[{position.position_id}].sourceTitle",
            )
            for responsibility in position.responsibilities:
                _require_supported_text(
                    issues,
                    evidence_by_id,
                    responsibility.source_text,
                    responsibility.evidence_ids,
                    f"responsibility[{responsibility.responsibility_id}].sourceText",
                )
            for requirement in position.requirements:
                _require_supported_text(
                    issues,
                    evidence_by_id,
                    requirement.source_text,
                    requirement.evidence_ids,
                    f"requirement[{requirement.requirement_id}].sourceText",
                )
        for requirement in posting.shared_conditions:
            _require_supported_text(
                issues,
                evidence_by_id,
                requirement.source_text,
                requirement.evidence_ids,
                f"sharedCondition[{requirement.requirement_id}].sourceText",
            )
    if issues:
        raise ContractReferenceError(issues)


def _require_supported_text(
    issues: list[ReferenceIssue],
    evidence_by_id: dict,
    value: str,
    evidence_ids: list[str],
    field: str,
) -> None:
    needle = _normalize(value)
    evidence_text = " ".join(evidence_by_id[evidence_id].text for evidence_id in evidence_ids)
    if needle not in _normalize(evidence_text):
        issues.append(ReferenceIssue(
            "EVIDENCE_TEXT_MISMATCH",
            f"{field} is not supported by its cited verified evidence",
        ))


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
