from __future__ import annotations

import json

import pytest

from jobis_ai.career_pipeline.contracts.parsing import StructuredContractError, parse_structured_payload
from jobis_ai.career_pipeline.contracts.source import VerifiedPostingSnapshot
from jobis_ai.career_pipeline.llm import JsonProviderContractError, StructuredGenerator


VALID = {
    "contractVersion": "jobis.ai.v3alpha1",
    "verifiedSnapshotId": "snapshot-1",
    "sourceDocumentId": "source-1",
    "sourceRevision": 1,
    "verifiedText": "공고 원문",
    "evidenceSegments": [{
        "segmentId": "vseg-1",
        "text": "공고 원문",
        "method": "USER_PASTE",
        "sourceLocator": {
            "page": None,
            "imageIndex": None,
            "boundingBox": None,
            "charStart": 0,
            "charEnd": 5,
        },
        "confidence": 1.0,
        "overlapGroup": None,
        "warnings": [],
    }],
    "corrections": [],
    "verifiedBy": "USER",
    "verifiedAt": "2026-08-04T03:00:00Z",
    "snapshotHash": "sha256:" + "a" * 64,
}


def test_parser_accepts_plain_json_object() -> None:
    parsed = parse_structured_payload(json.dumps(VALID, ensure_ascii=False), VerifiedPostingSnapshot)

    assert parsed.verified_snapshot_id == "snapshot-1"


def test_parser_only_repairs_outer_json_fence() -> None:
    raw = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"

    parsed = parse_structured_payload(raw, VerifiedPostingSnapshot)

    assert parsed.source_document_id == "source-1"


def test_parser_does_not_invent_missing_semantic_fields() -> None:
    invalid = dict(VALID)
    del invalid["verifiedText"]

    with pytest.raises(StructuredContractError, match="violates the contract"):
        parse_structured_payload(invalid, VerifiedPostingSnapshot)


def test_parser_rejects_non_object_json() -> None:
    with pytest.raises(StructuredContractError, match="JSON object"):
        parse_structured_payload("[]", VerifiedPostingSnapshot)


def test_shared_generator_preserves_contract_failure_category(monkeypatch) -> None:
    def contract_failure(*_args, **_kwargs):
        return None, [{
            "code": "llm_contract_validation_failed",
            "message": "payload violated the contract",
        }]

    monkeypatch.setattr(
        "jobis_ai.career_pipeline.llm_adapter.run_structured",
        contract_failure,
    )

    with pytest.raises(JsonProviderContractError, match="violated the contract"):
        StructuredGenerator().generate(
            VerifiedPostingSnapshot,
            system_prompt="system",
            user_prompt="input",
        )
