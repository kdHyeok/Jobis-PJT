"""계약 검사 결과를 통과, 실패, 미완료 상태로 요약한다."""
from __future__ import annotations


def summarize_checks(checks: list[dict]) -> tuple[str, bool]:
    """정보성 항목은 제외하고 명시적인 검사 결과만 집계한다.

    ``passed`` 키가 없는 지연 측정값 등은 정보성 항목이다. ``None``은
    실행되지 않은 검사이므로 통과가 아니라 ``incomplete``로 처리한다.
    """
    outcomes = [check["passed"] for check in checks if "passed" in check]
    if any(outcome is False for outcome in outcomes):
        return "failed", False
    if not outcomes or any(outcome is not True for outcome in outcomes):
        return "incomplete", False
    return "passed", True
