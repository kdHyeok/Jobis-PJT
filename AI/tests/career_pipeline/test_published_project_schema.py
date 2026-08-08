from __future__ import annotations

import json
from pathlib import Path

from jobis_ai.career_pipeline.contracts.project_planning import CompanyProjectBlueprint


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    ROOT
    / "contract-fixtures"
    / "schemas"
    / "jobis.ai.v3alpha1"
    / "company-project-blueprint.schema.json"
)
EXAMPLES_PATH = (
    ROOT
    / "contract-fixtures"
    / "examples"
    / "jobis.ai.v3alpha1"
    / "valid-contracts.json"
)


def test_published_company_project_schema_matches_unified_ai_contract() -> None:
    published = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert published == CompanyProjectBlueprint.model_json_schema(by_alias=True)


def test_published_company_project_example_is_valid() -> None:
    published = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    examples = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    payload = examples["company-project-blueprint"]

    parsed = CompanyProjectBlueprint.model_validate(payload)

    assert parsed.model_dump(mode="json", by_alias=True) == payload
