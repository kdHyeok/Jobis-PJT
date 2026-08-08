from __future__ import annotations

import json
from pathlib import Path

from jobis_ai_v3.api import SCHEMA_MODELS


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "contract-fixtures" / "schemas" / "jobis.ai.v3alpha1"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        target = OUTPUT / f"{name}.schema.json"
        target.write_text(
            json.dumps(model.model_json_schema(by_alias=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"exported {len(SCHEMA_MODELS)} schemas to {OUTPUT}")


if __name__ == "__main__":
    main()

