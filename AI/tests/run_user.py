"""아무 유저 폴더나 넣고 6개 에이전트를 돌려보는 범용 실행기.

    python tests/run_user.py user2
    python tests/run_user.py user2 24 15      # 준비기간(주) 주당시간 지정(선택, 기본 16 20)

폴더(tests/docs/<유저>/)에 아래를 넣으면 된다:
- 공고:  공고.txt (공고 본문)  ── 없으면 공고url.txt (URL) 사용
- 이력서: 아무 이름의 .docx 또는 .pdf 파일 (폴더에서 자동으로 찾음)

resumeInput 은 API 계약에 없는 내부 필드라, 여기서 GraphState 에 직접 주입한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


def _find_resume(folder: Path) -> Path | None:
    """폴더에서 이력서 파일(.docx/.pdf)을 자동으로 찾는다(임시 ~$ 파일 제외)."""
    for ext in ("*.docx", "*.pdf"):
        files = [f for f in sorted(folder.glob(ext)) if not f.name.startswith("~$")]
        if files:
            return files[0]
    return None


def _job_source(folder: Path) -> dict | None:
    """공고 입력을 찾는다. 본문 텍스트(공고.txt·채용공고.txt·이름에 '공고/채용' 포함 .txt) 우선,
    없으면 URL 파일(공고url.txt·url.txt)."""
    # 1) 정해진 이름의 본문 텍스트
    for name in ("공고.txt", "채용공고.txt"):
        p = folder / name
        if p.exists():
            return {"sourceType": "text", "value": p.read_text(encoding="utf-8")}
    # 2) 이름에 '공고/채용'이 들어간 아무 .txt (url 파일은 제외)
    for p in sorted(folder.glob("*.txt")):
        low = p.name.lower()
        if "url" in low:
            continue
        if "공고" in p.name or "채용" in p.name:
            return {"sourceType": "text", "value": p.read_text(encoding="utf-8")}
    # 3) URL 파일
    for name in ("공고url.txt", "url.txt"):
        p = folder / name
        if p.exists():
            return {"sourceType": "url", "value": p.read_text(encoding="utf-8").strip()}
    return None


def _dump(title: str, result: dict) -> None:
    print(f"\n===== {title} =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    who = sys.argv[1] if len(sys.argv) > 1 else "user1"
    weeks = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    weekly = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    folder = _ROOT / "tests" / "docs" / who
    if not folder.is_dir():
        print(f"[오류] 폴더가 없습니다: {folder}")
        sys.exit(1)

    job = _job_source(folder)
    resume = _find_resume(folder)

    # 무엇을 입력으로 쓰는지 먼저 알려준다
    print(f"[대상] {folder}")
    if job is None:
        print("[오류] 공고.txt 또는 공고url.txt 가 없습니다.")
        sys.exit(1)
    print(f"[공고] {job['sourceType']} 방식" +
          ("  (⚠️ URL은 본문을 못 가져올 수 있음 → 공고.txt 권장)" if job["sourceType"] == "url" else ""))
    if resume is None:
        print("[경고] 이력서(.docx/.pdf)를 못 찾음 → 폴백 프로필로 진행합니다.")
    else:
        print(f"[이력서] {resume.name}")
    print(f"[제약] 준비기간 {weeks}주 · 주당 {weekly}시간")

    # ---- 6개 에이전트 순서대로 실행 ----
    state: dict = {"jobPostingInput": job,
                   "preparationPeriodWeeks": weeks, "availableHoursPerWeek": weekly}

    state.update(_run("parse_job_posting", parse_job_posting, state))
    if resume is not None:
        state["resumeInput"] = {"sourceType": "file", "value": str(resume)}
    state.update(_run("build_user_profile", build_user_profile, state))
    state.update(_run("analyze_gap", analyze_gap, state))
    state.update(_run("plan_roadmap", plan_roadmap, state))
    state.update(_run("find_alternatives", find_alternatives, state))
    _run("verify_result", verify_result, state)


def _run(title, fn, state):
    out = fn(state)
    _dump(title, out)
    return out


if __name__ == "__main__":
    main()
