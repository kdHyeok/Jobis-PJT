from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from jobis_ai_v3.api import SCHEMA_MODELS


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "contract-fixtures" / "schemas" / "jobis.ai.v3alpha1"
EXAMPLES = ROOT / "contract-fixtures" / "examples" / "jobis.ai.v3alpha1" / "valid-contracts.json"


def test_all_published_examples_pass_pydantic_and_json_schema() -> None:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))

    assert set(examples) == set(SCHEMA_MODELS)
    for name, model in SCHEMA_MODELS.items():
        payload = examples[name]
        parsed = model.model_validate(payload)
        schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)
        assert parsed.model_dump(mode="json", by_alias=True) == payload


def test_published_schemas_match_current_models() -> None:
    for name, model in SCHEMA_MODELS.items():
        published = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert published == model.model_json_schema(by_alias=True), f"stale schema: {name}"
