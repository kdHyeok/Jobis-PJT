"""적합도 등급 판단의 LLM 두 단계 — 재검증(recheck)과 등급 판정(judge).

설계·근거: `_fitgrade/design.md` (위임 작업 폴더). 요지만 적으면:

- **재검증(1.5단계)**: 룰 매칭이 내린 "필수 미충족/판정불가" 중, 이력서 근거나 스킬
  목록으로 뒤집을 수 있는 것을 찾아 **판정 기록 자체를 갱신**한다. 오판을 신고만 하고
  틀린 진단을 사용자에게 내보내지 않기 위해서다(진단·등급·로드맵이 같은 기록에서 나온다).
  **상향 전용**이다 — 하향은 스키마가 아예 허용하지 않는다(룰이 met 이라 한 건 근거가 실존).
- **등급 판정(3단계)**: 검증이 끝난 판정 결과만 보고 루브릭에 따라 상/중/하를 낸다.
  이력서 원문을 다시 주지 않는다 — 사실 재심은 1.5단계에서 끝났고, 입력을 넓히면
  판단이 흔들린다(저장소 실측: 규칙 추가 −0.022 vs 어휘 좁히기 +0.058).

**§0 3계층 원칙의 예외다.** 이 작업에 한해 판단 계층에 LLM 을 쓰기로 결정했고
(`_fitgrade/CHANGELOG.md` 4번), 대신 위험을 구조로 막는다:
  · 상향 전용 + 근거 인용 강제(인용 없는 override 는 코드가 버린다) → 지어낸 근거로 못 뒤집는다.
  · 등급은 하드 룰(G1~G6, `gap_matcher.decide_grade`)이 허용 범위로 클램프한다.
  · 두 호출 모두 실패해도 예외를 던지지 않는다 — 원 판정 유지 / 점수식 폴백 + warning.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, Field

from jobis_ai.gap_matcher import Match, MatchReport
from jobis_ai.structured import run_structured

# --- 재검증 ---------------------------------------------------------------

_RECHECK_SYSTEM = (
    "당신은 요구사항 판정의 재검증자입니다. 이미 내려진 '미충족/판정불가' 판정 중,"
    " 주어진 근거 문장이나 보유 스킬 목록으로 뒤집을 수 있는 것만 찾습니다.\n"
    "- 뒤집으려면 반드시 근거를 인용하세요: 근거 문장 번호(evidenceIndexes) 또는"
    " 스킬 목록에 있는 스킬명(skillName). 인용할 근거가 없으면 뒤집지 않습니다.\n"
    "- 근거가 요구를 온전히 뒷받침하면 met, 일부만 뒷받침하면 partially_met 입니다.\n"
    "- **이력서에 보유 스킬로 기재된 기술은 '쓸 수 있다'고 인정합니다** — 이 서비스의 판정"
    " 규칙이며 근거 문장이 따로 없어도 됩니다. 요구사항이 그 기술로 충족되는 성격이면"
    " skillName 을 근거로 met 으로 상향하세요(예: '검색 엔진 기반 서비스 개발 경험' ←"
    " 보유 스킬 Elasticsearch).\n"
    "  요구 문구에 '경험·운영·활용'이 들어 있어도 마찬가지입니다. 기술명을 직접 적은"
    " 요구사항('Elasticsearch 활용 경험')은 이미 같은 규칙으로 met 처리되므로, 같은 것을"
    " 풀어 쓴 요구사항만 미충족으로 남으면 판정이 문구에 따라 갈립니다.\n"
    "- 애매하면 뒤집지 않습니다. 원래 판정 유지가 기본값입니다.\n"
    "- 새로운 사실을 지어내지 마세요. 주어진 문장과 스킬 목록에 있는 것만 근거입니다.\n"
    "- 확실한 것만 overrides 에 넣고, 없으면 빈 배열을 반환하세요."
)


class _Override(BaseModel):
    """판정 1건의 상향 재판정. 하향은 타입이 허용하지 않는다(프롬프트 금지가 아니라 구조)."""

    targetIndex: int = Field(default=-1, description="재검증 대상 번호(입력 순서, 0부터).")
    newStatus: Literal["met", "partially_met"] = Field(
        default="met", description="뒤집은 뒤의 판정. 근거가 온전하면 met, 일부면 partially_met.")
    evidenceIndexes: list[int] = Field(default_factory=list, description=(
        "판정을 뒤집는 근거 문장 번호(입력 순서, 0부터). 없으면 빈 목록."))
    skillName: str = Field(default="", description=(
        "보유 스킬 목록이 근거일 때 그 스킬명. 목록에 있는 그대로 적는다."))
    why: str = Field(default="", description="무엇을 근거로 뒤집었는지 한 문장.")


class _RecheckResult(BaseModel):
    """재검증 결과 전체. 뒤집을 게 없으면 빈 overrides."""

    overrides: list[_Override] = Field(default_factory=list, description=(
        "확실하게 뒤집을 수 있는 판정만. 없으면 빈 배열."))


def _recheck_targets(report: MatchReport) -> list[int]:
    """재검증 대상 인덱스 — 필수 not_met + (종류 무관) uncertain.

    met 은 대상이 아니다: 룰이 근거를 찾았다는 뜻이라 뒤집힐 여지가 작고, 전수 재검증은
    비용과 흔들림만 늘린다. 우대 not_met 도 제외한다 — 등급을 좌우하지 않는다(루브릭 §2).
    """

    return [
        i for i, m in enumerate(report.matches)
        if m.status == "uncertain" or (m.type == "required" and m.status == "not_met")
    ]


def recheck(report: MatchReport, profile: dict) -> list[dict]:
    """의심 판정을 이력서 원본 근거로 재판정해 **report 를 갱신**한다. 반환값은 warnings.

    호출 실패·미설정이면 아무것도 바꾸지 않고 warning 만 남긴다(원 판정 유지가 안전한
    기본값 — 최악의 경우가 '현행과 동일'이 되도록 설계했다).
    """

    targets = _recheck_targets(report)
    if not targets:
        return []

    evidences: list[dict] = profile.get("evidenceMap") or []
    skills = [str(s.get("name", "")) for s in (profile.get("skills") or []) if s.get("name")]
    if not evidences and not skills:
        return []

    numbered_targets = "\n".join(
        f"{pos}. {report.matches[idx].text} (현재 판정: {report.matches[idx].status}"
        f" — {report.matches[idx].reason})"
        for pos, idx in enumerate(targets)
    )
    numbered_ev = "\n".join(f"{i}. {e.get('text', '')}" for i, e in enumerate(evidences))
    user_content = (
        f"[재검증 대상]\n{numbered_targets}\n\n"
        f"[이력서 근거 문장]\n{numbered_ev or '(없음)'}\n\n"
        f"[이력서 기재 보유 스킬]\n{', '.join(skills) or '(없음)'}"
    )

    result, warnings = run_structured(
        _RecheckResult, _RECHECK_SYSTEM, user_content, node="grade_recheck", tier="light"
    )
    if result is None:
        warnings.append({
            "code": "recheck_unavailable",
            "message": "판정 재검증을 수행하지 못해 원래 판정을 유지했습니다(LLM 미설정/호출 실패).",
        })
        return warnings

    skill_lookup = {s.lower(): s for s in skills}
    applied = 0
    for ov in result.overrides:
        if not 0 <= ov.targetIndex < len(targets):
            continue
        match_idx = targets[ov.targetIndex]
        ev_ids = [
            str(evidences[i].get("evidenceId", ""))
            for i in ov.evidenceIndexes
            if 0 <= i < len(evidences) and evidences[i].get("evidenceId")
        ]
        skill = skill_lookup.get(ov.skillName.strip().lower(), "")
        # 근거 인용 없는 override 는 버린다 — 스키마를 통과해도 지어낸 근거로는 못 뒤집는다.
        if not ev_ids and not skill:
            continue
        old = report.matches[match_idx]
        report.matches[match_idx] = replace(
            old,
            status=ov.newStatus,
            matchedEvidenceIds=ev_ids or old.matchedEvidenceIds,
            matchedSkills=([skill] if skill else old.matchedSkills),
            missingSkills=[] if ov.newStatus == "met" else old.missingSkills,
            confidence=0.6,
            method="llm_recheck",
            reason=(
                f"재검증에서 {'보유 스킬 ' + skill if skill else '이력서 근거'}로 확인했습니다"
                f"{' — ' + ov.why.strip() if ov.why.strip() else ''}."
            ),
        )
        applied += 1

    if applied:
        warnings.append({
            "code": "recheck_applied",
            "message": f"재검증에서 요구사항 판정 {applied}건을 상향했습니다.",
        })
    return warnings


# --- 등급 판정 (루브릭) ----------------------------------------------------

_GRADE_SYSTEM = (
    "당신은 채용 공고 요구사항 충족도를 등급으로 판정하는 심사자입니다."
    " 입력으로 주어진 요구사항별 판정 결과(사실)만 근거로 삼습니다."
    " 합격 여부를 예측하지 않습니다 — 등급은 '요구 충족도에 따른 다음 행동'입니다.\n"
    "\n[등급 기준]\n"
    "상 — 지금 지원해도 되는 수준.\n"
    "  · 확인된 필수 미충족(not_met)이 없다. 또는 1건뿐이며 그것이 이 공고의 핵심 요구가 아니다.\n"
    "  · '핵심 요구'란 공고 직무의 주력 기술·역할에 해당하는 요구다"
    " (예: 백엔드 공고의 Java 는 핵심, 협업 툴 사용 경험은 부수적).\n"
    "  · 부분 충족(partially_met)이 있어도 핵심 요구가 아니면 상이 가능하다.\n"
    "\n중 — 보강 후 지원할 수준.\n"
    "  · 필수에 격차가 있으나, 수 주~수개월의 학습·경험으로 메꿀 수 있는 성질이다.\n"
    "  · 예: 보조 기술 스택 2개 이상 미보유, 핵심 기술의 부분 충족,"
    " 연차 부족이 크지 않음(12~24개월 부족은 격차의 성질을 보고 판단).\n"
    "\n하 — 이 공고보다 대체(인접) 공고를 먼저 보는 게 합리적인 수준.\n"
    "  · 핵심 필수의 격차가 구조적이다 — 단기 학습으로 메꿀 수 없다.\n"
    "  · 예: 공고의 주력 기술 미보유, 연차가 24개월 이상 부족하거나 보유 경력이 요구의"
    " 절반에 못 미침, 필수 미충족이 충족보다 많음.\n"
    "\n[판정 규칙]\n"
    "· 판정 불가(uncertain)로 표시된 요구사항은 격차로 세지 않습니다. 없는 것이 아니라 모르는 것입니다.\n"
    "· 우대(preferred) 요구사항 미충족만으로는 등급을 낮추지 않습니다.\n"
    "· 근거(rationale)에는 판정을 가른 요구사항을 인용하고, 입력에 없는 사실을 만들지 않습니다."
)


class GradeVerdict(BaseModel):
    """LLM 의 등급 제안. 최종 등급은 하드 룰(G1~G6)이 클램프한 뒤 확정된다."""

    grade: Literal["상", "중", "하"] = Field(default="중", description="루브릭에 따른 등급.")
    keyRequirementIds: list[str] = Field(default_factory=list, description=(
        "등급을 가른 핵심 요구사항의 ID. 입력에 있는 ID 만 적는다."))
    rationale: str = Field(default="", description="등급 근거 1~3문장. 판정을 가른 요구사항을 인용한다.")
    shortTermGap: bool = Field(default=False, description=(
        "격차가 수 주~수개월의 학습으로 메꿀 수 있는 성질인가(중/하 판별 근거)."))


_STATUS_KO = {
    "met": "충족", "partially_met": "부분 충족",
    "not_met": "미충족", "uncertain": "판정 불가(격차로 세지 않음)",
}


def judge_grade(
    matches: list[Match], score_basis: dict, posting: dict
) -> tuple[GradeVerdict | None, list[dict]]:
    """검증된 판정 결과 → 루브릭 기반 등급 제안. 실패 시 (None, warnings)."""

    lines = []
    for m in matches:
        kind = "필수" if m.type == "required" else "우대"
        lines.append(
            f"- [{m.requirementId}] ({kind}) {m.text} → {_STATUS_KO.get(m.status, m.status)}"
            f" | 근거: {m.reason}"
        )
    scores = ", ".join(f"{k}={v}" for k, v in score_basis.items() if v is not None) or "(없음)"
    user_content = (
        f"[공고] {posting.get('title', '(제목 없음)')}"
        f" / 직무: {posting.get('roleCategory', '(미상)')}\n\n"
        f"[요구사항별 판정]\n" + "\n".join(lines) + "\n\n"
        f"[카테고리 점수(참고)] {scores}"
    )

    verdict, warnings = run_structured(
        GradeVerdict, _GRADE_SYSTEM, user_content, node="grade_judge", tier="default"
    )
    if verdict is None:
        warnings.append({
            "code": "grade_judge_unavailable",
            "message": "등급 판단을 수행하지 못해 점수 기반 등급으로 대체했습니다(LLM 미설정/호출 실패).",
        })
    return verdict, warnings
