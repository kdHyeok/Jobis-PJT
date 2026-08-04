"""하드 룰(G1~G6) 단위 테스트 — LLM 없이 결정론만 검증한다.

설계: `_fitgrade/design.md` §4. 여기서 재는 것은 "LLM 이 무엇을 내든 넘을 수 없는 선"이
실제로 못 넘게 돼 있는가다. LLM 이 끼는 경로(recheck·judge_grade)는 이 파일에서 건드리지
않는다 — 그쪽은 평가 하네스(`_fitgrade/eval/run_eval.py`)가 실 모델로 잰다.
"""

from __future__ import annotations

import pytest

from jobis_ai.gap_matcher import Match, MatchReport
from jobis_ai.grade_decision import _hard_rule_bounds, decide_grade


def m(rid: str, status: str, *, type_: str = "required", kind: str = "text",
      detail: dict | None = None, evidence: bool = False) -> Match:
    """판정 1건. evidence=True 면 근거 ID 를 달아 준다.

    근거 유무는 하드 룰과 무관하지만(§4 는 status 만 본다) **점수식 폴백에는 영향이 있다** —
    scoreBasis 의 projectExperience 가 '근거로 뒷받침된 비율'이라 근거가 없으면 0 이 된다.
    """

    return Match(requirementId=rid, type=type_, text=f"요구 {rid}", status=status,
                 kind=kind, detail=detail or {},
                 matchedEvidenceIds=[f"e-{rid}"] if evidence else [])


def seniority(status: str, *, required_months: int = 24, actual_months: int = 0) -> Match:
    return m("s1", status, kind="seniority", detail={
        "requiredMonths": required_months,
        "actualMonths": actual_months,
        "gapMonths": required_months - actual_months,
    })


# --- G1: 필수 not_met 2건 이상 → 상 불가 -----------------------------------

def test_g1_한건이면_상을_막지_않는다():
    """1건은 LLM 재량으로 남긴다 — 그 1건이 핵심인지 부수적인지는 루브릭이 판단한다."""

    low, high, fired = _hard_rule_bounds([m("r1", "not_met"), m("r2", "met"), m("r3", "met")])
    assert high == "상"
    assert "G1" not in fired


def test_g1_두건이면_상_불가():
    low, high, fired = _hard_rule_bounds([
        m("r1", "not_met"), m("r2", "not_met"), m("r3", "met"), m("r4", "met"),
    ])
    assert high == "중"
    assert "G1" in fired


def test_g1_우대_notmet은_세지_않는다():
    low, high, fired = _hard_rule_bounds([
        m("r1", "not_met", type_="preferred"), m("r2", "not_met", type_="preferred"),
        m("r3", "met"), m("r4", "met"),
    ])
    assert high == "상"
    assert "G1" not in fired


def test_g1_uncertain은_격차로_세지_않는다():
    """모른다 ≠ 아니다 — uncertain 2건은 G1 을 발동시키지 않는다."""

    low, high, fired = _hard_rule_bounds([
        m("r1", "uncertain"), m("r2", "uncertain"), m("r3", "met"),
    ])
    assert high == "상"
    assert fired == ["G3"]  # 판정된 필수가 전부 met → 하 불가만 발동


# --- G2: 필수 연차 not_met → 상 불가 ---------------------------------------

def test_g2_연차_notmet이면_기술이_완벽해도_상_불가():
    low, high, fired = _hard_rule_bounds([
        m("r1", "met"), m("r2", "met"), m("r3", "met"),
        seniority("not_met", required_months=36, actual_months=22),  # 14개월 부족
    ])
    assert high == "중"
    assert "G2" in fired
    assert "G6" not in fired  # 격차 14개월 < 24 → 구조적 격차는 아니다


def test_g2_연차_partially면_상_가능():
    low, high, fired = _hard_rule_bounds([
        m("r1", "met"), seniority("partially_met", required_months=24, actual_months=18),
    ])
    assert high == "상"


# --- G3: 필수 전부 met → 하 불가 -------------------------------------------

def test_g3_필수_전부_met이면_하_불가():
    low, high, fired = _hard_rule_bounds([m("r1", "met"), m("r2", "met")])
    assert low == "중"
    assert "G3" in fired


def test_g3_partially가_섞이면_발동하지_않는다():
    low, high, fired = _hard_rule_bounds([m("r1", "met"), m("r2", "partially_met")])
    assert low == "하"
    assert "G3" not in fired


# --- G5: 필수 not_met 과반 → 하 확정 ---------------------------------------

def test_g5_과반이면_중도_불가():
    low, high, fired = _hard_rule_bounds([
        m("r1", "not_met"), m("r2", "not_met"), m("r3", "not_met"), m("r4", "met"),
    ])
    assert high == "하"
    assert "G5" in fired


def test_g5_정확히_절반이면_발동하지_않는다():
    """'과반'이다 — 2/4 는 넘지 못한 것이라 중이 살아 있다."""

    low, high, fired = _hard_rule_bounds([
        m("r1", "not_met"), m("r2", "not_met"), m("r3", "met"), m("r4", "met"),
    ])
    assert high == "중"      # G1 은 발동(2건)
    assert "G5" not in fired


# --- G6: 연차 격차가 구조적 → 하 확정 --------------------------------------

def test_g6_무경력_경력2년요구는_하_확정():
    """기술을 전부 갖췄어도 하. 이게 없으면 중이 나온다(baseline C11 이 실제로 상이었다)."""

    matches = [m("r1", "met"), m("r2", "met"),
               seniority("not_met", required_months=24, actual_months=0)]
    low, high, fired = _hard_rule_bounds(matches)
    assert (low, high) == ("하", "하")
    assert "G6" in fired


def test_g6_시니어_근접은_발동하지_않는다():
    """8년차가 10년 공고에 지원 — 격차 24개월이지만 보유가 절반 이상이라 하로 강제하지 않는다."""

    low, high, fired = _hard_rule_bounds([
        m("r1", "met"), seniority("not_met", required_months=120, actual_months=96),
    ])
    assert "G6" not in fired
    assert high == "중"      # G2 는 발동(연차 not_met)
    assert low == "하"       # 하 확정은 아니다 — 중/하는 LLM 재량


def test_g6_요구개월수를_모르면_발동하지_않는다():
    """사다리 폴백(공고가 숫자 없이 '시니어'라고만 함) — 절반 조건을 잴 수 없다."""

    match = m("s1", "not_met", kind="seniority", detail={"actualMonths": 0})
    low, high, fired = _hard_rule_bounds([m("r1", "met"), match])
    assert "G6" not in fired


def test_g6_연차가_uncertain이면_발동하지_않는다():
    """경력 기간을 못 읽은 것을 무경력으로 단정하지 않는다."""

    low, high, fired = _hard_rule_bounds([
        m("r1", "met"), m("s1", "uncertain", kind="seniority"),
    ])
    assert "G6" not in fired and "G2" not in fired


# --- G4 + 클램프 통합 (LLM 없이 폴백 경로로 확인) ---------------------------

def test_g4_판정된_요구사항이_없으면_llm_없이_판정불가(monkeypatch):
    """LLM 을 아예 부르지 않는 단락 경로. 부르면 실패한다."""

    def _boom(*args, **kwargs):  # pragma: no cover - 호출되면 안 된다
        raise AssertionError("G4 에서는 LLM 을 호출하면 안 된다")

    monkeypatch.setattr("jobis_ai.grade_judge.judge_grade", _boom)
    monkeypatch.setattr("jobis_ai.grade_judge.recheck", lambda report, profile: [])

    report = MatchReport(matches=[m("r1", "uncertain"), m("s1", "uncertain", kind="seniority")])
    decision = decide_grade(report, {"skills": [], "evidenceMap": []})
    assert decision.grade == "판정불가"
    assert decision.clampedBy == "G4"
    assert decision.score is None


@pytest.mark.parametrize("llm_grade,expected,rule", [
    ("상", "중", "G1"),   # 필수 not_met 2건인데 상이라고 하면 잘린다
    ("하", "중", "G3"),   # 필수 전부 met 인데 하라고 하면 올라온다
])
def test_llm_등급이_하드룰을_넘으면_클램프된다(monkeypatch, llm_grade, expected, rule):
    from jobis_ai.grade_judge import GradeVerdict

    monkeypatch.setattr("jobis_ai.grade_judge.recheck", lambda report, profile: [])
    monkeypatch.setattr(
        "jobis_ai.grade_judge.judge_grade",
        lambda matches, score_basis, posting: (
            GradeVerdict(grade=llm_grade, rationale="테스트"), []
        ),
    )

    if rule == "G1":
        matches = [m("r1", "not_met"), m("r2", "not_met"), m("r3", "met"), m("r4", "met")]
    else:
        matches = [m("r1", "met"), m("r2", "met")]

    decision = decide_grade(MatchReport(matches=matches), {"skills": [], "evidenceMap": []})
    assert decision.grade == expected
    assert decision.llmGrade == llm_grade          # LLM 이 뭐라 했는지는 남는다
    assert rule in decision.clampedBy
    assert any(w["code"] == "grade_clamped" for w in decision.warnings)


def test_llm_실패시_점수식으로_폴백한다(monkeypatch):
    """등급이 안 나와서 분석 전체가 죽지 않는다 — 폴백하되 이유를 warning 으로 남긴다."""

    monkeypatch.setattr("jobis_ai.grade_judge.recheck", lambda report, profile: [])
    monkeypatch.setattr(
        "jobis_ai.grade_judge.judge_grade",
        lambda matches, score_basis, posting: (
            None, [{"code": "grade_judge_unavailable", "message": "실패"}]
        ),
    )

    report = MatchReport(matches=[m("r1", "met", evidence=True), m("r2", "met", evidence=True)])
    decision = decide_grade(report, {"skills": [], "evidenceMap": []})
    assert decision.grade == "상"                   # 점수식 결과(전부 met + 근거 있음 → 1.0)
    assert decision.llmGrade == ""
    assert any(w["code"] == "grade_judge_unavailable" for w in decision.warnings)
