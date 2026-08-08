"""user1 페르소나 픽스처로 실제 노드를 돌려보는 수동 확인 스크립트.

    python -m tests.run_user1        (레포 루트에서)
    또는  python tests/run_user1.py

입력:
- 공고: tests/docs/user1/공고.txt 가 있으면 그 본문(text), 없으면 공고url.txt 의 URL
- 이력서: tests/docs/user1/이력서_김도현_백엔드.docx (file)

resumeInput 은 API 계약(AnalyzeRequest)에 없는 내부 필드라, 여기서 GraphState 에 직접 주입한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# src 레이아웃을 import 경로에 추가 (editable 설치 없이도 실행되게)
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from jobis_ai.graph.nodes import (  # noqa: E402
    analyze_gap,
    build_user_profile,
    find_alternatives,
    parse_job_posting,
    plan_roadmap,
    verify_result,
)

_FIXTURE = _ROOT / "tests" / "docs" / "user1"


def _job_source() -> dict:
    text_file = _FIXTURE / "공고.txt"
    if text_file.exists():
        return {"sourceType": "text", "value": text_file.read_text(encoding="utf-8")}
    url = (_FIXTURE / "공고url.txt").read_text(encoding="utf-8").strip()
    return {"sourceType": "url", "value": url}


def _dump(title: str, result: dict) -> None:
    print(f"\n===== {title} =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    resume = _FIXTURE / "이력서_김도현_백엔드.docx"

    # 노드 출력을 다음 노드 입력으로 이어붙여(간이 파이프라인) 갭 분석까지 확인한다.
    state: dict = {"jobPostingInput": _job_source()}

    job_out = parse_job_posting(state)
    _dump("parse_job_posting", job_out)
    state.update(job_out)

    state["resumeInput"] = {"sourceType": "file", "value": str(resume)}
    profile_out = build_user_profile(state)
    _dump("build_user_profile", profile_out)
    state.update(profile_out)

    gap_out = analyze_gap(state)
    _dump("analyze_gap", gap_out)
    state.update(gap_out)

    # 준비 기간/주당 시간 제약 (요청에서 오는 값 — 하네스에서는 임의 지정)
    state["preparationPeriodWeeks"] = 16
    state["availableHoursPerWeek"] = 20
    roadmap_out = plan_roadmap(state)
    _dump("plan_roadmap", roadmap_out)
    state.update(roadmap_out)

    alt_out = find_alternatives(state)
    _dump("find_alternatives", alt_out)
    state.update(alt_out)

    verify_out = verify_result(state)
    _dump("verify_result", verify_out)


if __name__ == "__main__":
    main()
