"""등급 확정 — 하드 룰(G1~G6)과 판정 오케스트레이션.

설계·근거: `_fitgrade/design.md` §3~§4, 결정 이력: `_fitgrade/CHANGELOG.md`.

**이 모듈이 따로 있는 이유**: 상/중/하 로직만 떼어 메인 브랜치에 합칠 수 있어야 한다
(위임 작업). 그래서 팀 공용 `gap_matcher.py` 에는 손댈 것을 최소로 남기고(연차 수치를
싣는 `Match.detail` 뿐), 하드 룰·오케스트레이션·LLM 호출은 전부 신규 파일에 둔다.
포팅 절차는 `_fitgrade/MERGE.md`.

역할 분담:
  · 사실 판정(무엇을 갖췄나)  → `gap_matcher` (룰, 기존 그대로)
  · 사실 재검증 / 등급 제안    → `grade_judge` (LLM)
  · **등급 확정**              → 여기 (결정론 — LLM 제안을 허용 범위로 클램프)

하드 룰은 "LLM 이 무엇을 내든 넘을 수 없는 선"이다. 프롬프트로 금지하지 않고 코드로 막는
이유는, 이 저장소 실측에서 프롬프트 금지가 지켜지지 않았기 때문이다(AGENTS §2-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobis_ai import trace
from jobis_ai.gap_matcher import (
    _STATUS_SCORE,
    Match,
    MatchReport,
    overall_fit,
    to_gap_payload,
)

# 등급 순서 (낮은 것부터). 클램프는 이 순서 위에서 잘라낸다.
_GRADE_ORDER = ("하", "중", "상")

# G6 — 연차 격차가 '구조적'이라고 볼 임계. 24개월 이상 부족 **이고** 보유가 요구의 절반
# 미만일 때만 발동한다. 격차만 보면 8년차가 10년 공고에서도 하가 되는데 그건 과하다.
_G6_GAP_MONTHS = 24


@dataclass
class GradeDecision:
    """등급 판정 결과. `overall_fit` 의 (점수, 등급) 을 대체하는 산출물."""

    grade: str
    score: float | None
    payload: dict                                    # 재검증으로 갱신된 to_gap_payload 결과
    warnings: list[dict] = field(default_factory=list)
    clampedBy: str = ""                              # 발동한 하드 룰 ID (없으면 "")
    llmGrade: str = ""                               # LLM 제안 등급 (클램프 전 — 추적용)


def _hard_rule_bounds(matches: list[Match]) -> tuple[str, str, list[str]]:
    """판정 결과 → (하한, 상한, 발동 규칙 ID). 결정론이다 — LLM 이 넘을 수 없는 선.

    G1 필수 not_met ≥ 2건 → 상 불가      G2 필수 연차 not_met → 상 불가
    G3 필수 전부 met → 하 불가            G5 필수 not_met 과반 → 하 확정(상한)
    G6 연차 격차 ≥ 24개월 & 보유 < 요구의 절반 → 하 확정
    (G4 는 여기 없다 — 판정된 요구사항이 0건이면 애초에 LLM 을 부르지 않는다. decide_grade 참고)
    """

    decided = [m for m in matches if m.status in _STATUS_SCORE]
    req_decided = [m for m in decided if m.type == "required"]
    req_notmet = [m for m in req_decided if m.status == "not_met"]
    seniority = next(
        (m for m in matches if m.kind == "seniority" and m.type == "required"), None
    )

    high, low, fired = "상", "하", []

    def cap(limit: str, rule: str) -> None:
        nonlocal high
        if _GRADE_ORDER.index(limit) < _GRADE_ORDER.index(high):
            high = limit
        fired.append(rule)

    if len(req_notmet) >= 2:
        cap("중", "G1")
    if seniority is not None and seniority.status == "not_met":
        cap("중", "G2")
    if req_decided and len(req_notmet) * 2 > len(req_decided):
        cap("하", "G5")
    if seniority is not None and seniority.status == "not_met":
        detail = seniority.detail or {}
        required_months = detail.get("requiredMonths")
        actual_months = detail.get("actualMonths")
        # 요구 개월수를 모르면(사다리 폴백) 발동하지 않는다 — 절반 조건을 잴 수 없다.
        if (
            required_months
            and actual_months is not None
            and detail.get("gapMonths", 0) >= _G6_GAP_MONTHS
            and actual_months * 2 < required_months
        ):
            cap("하", "G6")
            low = "하"
    if req_decided and all(m.status == "met" for m in req_decided):
        # 필수를 다 갖췄는데 "대체 공고 우선"은 모순이다. 상한과 충돌할 일은 없다
        # (상한을 내리는 규칙은 전부 not_met 을 전제하므로 이 조건과 양립 불가).
        low = "중"
        fired.append("G3")

    return low, high, fired


def decide_grade(report: MatchReport, profile: dict, posting: dict | None = None) -> GradeDecision:
    """하이브리드 등급 판정 — 재검증 → 집계 → LLM 등급 판단 → 하드 룰 클램프.

    `overall_fit()` 은 그대로 남는다: 점수(overallScore) 산출과 **LLM 실패 시 폴백**에 쓴다.
    어느 단계가 실패해도 예외를 던지지 않는다 — 등급이 안 나와서 분석 전체가 죽지 않게.
    """

    from jobis_ai.grade_judge import judge_grade, recheck

    warnings: list[dict] = []
    posting = posting or {}

    # 1.5단계 — 의심 판정을 원본 근거로 재판정하고 **기록 자체를 갱신**한다.
    warnings.extend(recheck(report, profile))

    payload = to_gap_payload(report)
    score_basis = payload["scoreBasis"]
    score, score_grade = overall_fit(score_basis)

    # G4 — 판정된 요구사항이 없으면 등급을 단정하지 않는다(LLM 도 부르지 않는다).
    if not [m for m in report.matches if m.status in _STATUS_SCORE]:
        return GradeDecision(grade="판정불가", score=None, payload=payload,
                             warnings=warnings, clampedBy="G4")

    # 3단계 — 루브릭 기반 LLM 등급 판단. 실패하면 기존 점수식 등급으로 폴백한다.
    verdict, judge_warnings = judge_grade(report.matches, score_basis, posting)
    warnings.extend(judge_warnings)
    proposed = verdict.grade if verdict is not None else score_grade
    if proposed not in _GRADE_ORDER:      # 폴백 등급이 "판정불가" 인 경우 등
        proposed = score_grade if score_grade in _GRADE_ORDER else "중"

    # 4단계 — 하드 룰 클램프. LLM 이 뭘 내든 허용 범위 밖으로는 못 나간다.
    low, high, fired = _hard_rule_bounds(report.matches)
    final = proposed
    if _GRADE_ORDER.index(final) > _GRADE_ORDER.index(high):
        final = high
    if _GRADE_ORDER.index(final) < _GRADE_ORDER.index(low):
        final = low

    clamped_by = ""
    if final != proposed:
        clamped_by = "+".join(fired) or "bounds"
        warnings.append({
            "code": "grade_clamped",
            "message": (
                f"등급 판단({proposed})이 하드 룰({clamped_by})의 허용 범위를 벗어나 "
                f"{final} 로 조정했습니다."
            ),
        })

    trace.emit("score", f"하이브리드 등급 판정 → {final}", {
        "proposedGrade": proposed,
        "llmAvailable": verdict is not None,
        "bounds": {"low": low, "high": high},
        "firedRules": fired,
        "clampedBy": clamped_by,
        "weightedScore": score,
        "rationale": verdict.rationale if verdict is not None else "",
        "keyRequirementIds": verdict.keyRequirementIds if verdict is not None else [],
    })
    return GradeDecision(
        grade=final, score=score, payload=payload, warnings=warnings,
        clampedBy=clamped_by, llmGrade=verdict.grade if verdict is not None else "",
    )
