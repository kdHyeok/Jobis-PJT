"""계약(Pydantic) → JSON Schema + 샘플 JSON 산출.

백엔드에 넘길 계약 산출물을 재현 가능하게 뽑는다.

    python scripts/export_contract_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path

from jobis_ai.contracts.api import (
    AnalyzeOptions,
    AnalyzeRequest,
    AnalyzeResponse,
    JobPostingInput,
)
from jobis_ai.service import run_analysis

OUT = Path(__file__).resolve().parents[1] / "docs" / "contracts"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "analyze_request.schema.json").write_text(
        json.dumps(AnalyzeRequest.model_json_schema(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "analyze_response.schema.json").write_text(
        json.dumps(AnalyzeResponse.model_json_schema(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 샘플 요청/응답 (스켈레톤 mock 실행 결과)
    sample_request = AnalyzeRequest(
        userId=1,
        jobPostingInput=JobPostingInput(sourceType="url", value="https://example.com/jobs/1"),
        selectedExperienceIds=[3, 7, 9],
        preparationPeriodWeeks=16,
        availableHoursPerWeek=20,
        options=AnalyzeOptions(includeAlternatives=True),
    )
    sample_response = run_analysis(sample_request)

    (OUT / "sample_request.json").write_text(
        json.dumps(sample_request.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "sample_response.json").write_text(
        json.dumps(sample_response.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"계약 산출물 생성 완료 → {OUT}")


if __name__ == "__main__":
    main()
