"""RAGAS 4축 일괄 실행 — 준비 -> 프로덕션 생성 -> 채점 (템플릿·프로덕션 두 판).

두 판을 모두 재는 이유: `faithfulness`/`answer_relevancy`는 **생성 답변**의 함수다.
템플릿 스탠드인(검색결과 서술)은 하네스 정합성 검사용 상한이고, 프로덕션 생성
(GmsClient + 실 SYSTEM_PROMPT)이 실제 품질이다. 둘을 나란히 두지 않으면 점수가
"검색이 좋아서"인지 "생성이 좋아서"인지 분리되지 않는다.

ID기반 2축(`context_precision_id`/`context_recall_id`)은 결정적 집합 비교이므로 두 판에서
같은 값이 나온다 — 다르면 데이터셋 구성이 어긋났다는 신호다.

실행: python -X utf8 -m eval.ragas_all
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable, "-X", "utf8", "-u"]

STAGES = [
    ("데이터셋 구성 (동결 15종)", ["-m", "eval.ragas_prep"]),
    ("프로덕션 생성 답변 수집", ["-m", "eval.ragas_responses", "--generate-production"]),
    ("채점 — 템플릿 판", ["-m", "eval.ragas_run"]),
    ("채점 — 프로덕션 판", ["-m", "eval.ragas_run",
                            "--dataset", "ragas_dataset_production.json"]),
]


def main() -> int:
    for name, argv in STAGES:
        print(f"\n=== {name} ===", flush=True)
        p = subprocess.run(PY + argv, cwd=ROOT)
        if p.returncode != 0:
            print(f"!! 실패: {name} (종료코드 {p.returncode})")
            return p.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
