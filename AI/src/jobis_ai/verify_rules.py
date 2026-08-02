"""검증 룰 4종 (verify_rules) — "LLM 이 LLM 을 검증"하던 것을 룰 검증으로 바꾼다.

설계 §3.8. 자기 자신을 검증하는 LLM 은 자기가 만든 환각을 못 잡는다(같은 편향을 공유한다).
검증은 **기계적으로 대조 가능한 것만** 본다. 그래서 전부 룰이다. **LLM 호출 없음.**

4종:
  1. `validate_schema`          — 필수 산출물이 있는가 (구조 결함)
  2. `check_forbidden_lexicon`  — 합격 단정·과장 표현이 섞였는가 (표현 결함)
  3. `check_evidence_grounding` — 인용한 근거가 실재하는가 (참조 무결성)
  4. `check_consistency`        — gap 과 roadmap 이 서로 아귀가 맞는가 (교차 검증)

결함 등급 구분(라우팅에 쓰인다):
  - **구조 결함**(missing_field/inconsistent): 재시도해야 고쳐진다.
  - **표현 결함**(forbidden_expression): 문장만 다듬으면 되므로 통과시키되 완화 표시.
  - **근거 결함**(no_evidence): 소수면 제거하고 통과, 과다하면 구조 문제로 보고 재시도.
"""

from __future__ import annotations

import re

from jobis_ai.contracts.domain import Violation

# 표현 원칙(설계 12.3-2): 합격/불합격 단정·과장 표현 금지.
# 이 서비스는 합격을 예측하지 않는다 — 요구사항 충족도까지만 말한다.
FORBIDDEN_EXPRESSIONS: tuple[str, ...] = (
    "합격 가능", "합격가능", "불합격", "지원 불가", "지원불가",
    "반드시", "무조건", "100% 합격", "확실히 합격", "붙습니다", "떨어집니다",
    "보장", "장담", "틀림없", "당연히 됩니다",
    # 합격 예측의 우회 표현 — career_chat 이 "서류 통과 가능성은 충분히 노려볼 만해요"로
    # 새어나간 실측(2026-07-31). 예측을 돌려 말해도 예측이다.
    "통과 가능성", "합격 확률", "합격률", "승산", "노려볼 만",
)

# 숫자+마침표("2. ")는 목록 마커이지 문장 끝이 아니다 — 거기서 가르면 마커만 남는다.
_SENTENCE_SPLIT = re.compile(r"(?<!\d\.)(?<=[.!?…])\s+")


def drop_forbidden_sentences(text: str) -> tuple[str, list[str]]:
    """금지표현이 든 **문장만** 버리고 나머지를 살린다 — 전량 강등의 결정론 대안 (D123).

    목록에는 '반드시'·'보장'처럼 코칭 문장에 자연스럽게 나오는 낱말이 있어서, 한 단어가
    걸렸다고 답변 전체를 고정 문구로 바꾸면 정상 답변이 통째로 버려진다(실측: career_chat
    강등 2.5%, 전부 정상 요청). 판정 원칙은 유지한다 — 걸린 문장은 여전히 나가지 않는다.

    반환: (남은 텍스트, 걸린 표현들). 남은 텍스트가 비면 호출부가 기존 폴백을 쓴다.
    """

    hits: list[str] = []
    kept_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            kept_lines.append(line)     # 문단 구분(빈 줄)은 보존
            continue
        kept_sentences = []
        for sentence in _SENTENCE_SPLIT.split(line):
            found = [e for e in FORBIDDEN_EXPRESSIONS if e in sentence]
            if found:
                hits.extend(h for h in found if h not in hits)
            else:
                kept_sentences.append(sentence)
        if any(s.strip() for s in kept_sentences):
            kept_lines.append(" ".join(s for s in kept_sentences if s.strip()))
        # 문장이 전부 걸린 줄은 줄째 버린다 — 빈 불릿을 남기지 않는다
    return "\n".join(kept_lines).strip(), hits


def validate_schema(gap: dict, roadmap: dict) -> list[Violation]:
    """1) 핵심 산출물이 비어 있지 않은지 (설계 12.3-1).

    비어 있으면 뒤 단계가 전부 무의미하므로 구조 결함으로 본다.
    """

    violations: list[Violation] = []
    if not gap.get("requirementStatus"):
        violations.append(Violation(
            type="missing_field",
            location="gapAnalysisResult.requirementStatus",
            detail="요구사항 판정이 비어 있습니다.",
        ))
    return violations


def iter_user_facing_texts(gap: dict, roadmap: dict) -> list[str]:
    """사용자에게 보이는 문장들을 모은다 (금지 표현 검사 대상)."""

    texts: list[str] = []
    for status in gap.get("requirementStatus", []):
        texts.append(str(status.get("reason", "")))
    for strength in gap.get("strengths", []):
        texts.append(str(strength.get("text", "")))
    for item in gap.get("gaps", []):
        texts.append(str(item.get("reason", "")))
    for item in roadmap.get("roadmap", []):
        texts.append(str(item.get("goal", "")))
        texts.append(str(item.get("doneCriteria", "")))
    return [t for t in texts if t]


def check_forbidden_lexicon(gap: dict, roadmap: dict) -> tuple[list[Violation], list[dict]]:
    """2) 금지 표현 탐지 (설계 12.3-2). 표현 수준이므로 완화 표시 후 통과시킨다."""

    violations: list[Violation] = []
    warnings: list[dict] = []
    for text in iter_user_facing_texts(gap, roadmap):
        for bad in FORBIDDEN_EXPRESSIONS:
            if bad in text:
                violations.append(Violation(
                    type="forbidden_expression",
                    location="text",
                    detail=f"금지 표현 '{bad}' 발견: {text[:40]}",
                ))
                warnings.append({
                    "code": "softened_expression",
                    "message": f"단정적 표현('{bad}')을 완화 대상으로 표시했습니다.",
                })
    return violations, warnings


def check_evidence_grounding(
    gap: dict, profile: dict
) -> tuple[dict, list[Violation], list[dict], int]:
    """3) 인용한 evidenceId 가 실제 evidenceMap 에 있는지 대조 (참조 무결성).

    존재하지 않는 근거를 인용했다면 그건 환각이므로 **제거**한다. 근거가 전부 환각이었는데
    met 로 단정했다면 판정을 uncertain 으로 내린다 — 근거 없이 충족을 주장할 수 없다.

    반환: (sanitize 된 gap, 위반들, 경고들, 환각 건수)

    참고: gap_matcher 가 skillEvidence(룰 산출)만 인용하므로 지금은 여기서 걸릴 일이
    거의 없다. 그래도 남겨 둔다 — 나중에 nl_render 나 다른 LLM 단계가 이 필드를 건드릴 때
    마지막 방어선이 된다.
    """

    sanitized = dict(gap)
    violations: list[Violation] = []
    warnings: list[dict] = []
    valid_ids = {
        e.get("evidenceId") for e in profile.get("evidenceMap", []) if e.get("evidenceId")
    }

    hallucinated_count = 0
    statuses: list[dict] = []
    for raw in gap.get("requirementStatus", []):
        status = dict(raw)
        cited = status.get("matchedEvidenceIds", []) or []
        bogus = [eid for eid in cited if eid not in valid_ids]
        if bogus:
            hallucinated_count += 1
            status["matchedEvidenceIds"] = [eid for eid in cited if eid in valid_ids]
            violations.append(Violation(
                type="no_evidence",
                location=f"requirementStatus[{status.get('requirementId')}]",
                detail=f"존재하지 않는 근거 인용(환각): {bogus}",
            ))
            warnings.append({
                "code": "hallucinated_evidence",
                "message": f"{status.get('requirementId')}: 근거 {bogus} 는 evidenceMap 에 없어 제거했습니다.",
            })
            if not status["matchedEvidenceIds"] and status.get("status") == "met":
                status["status"] = "uncertain"
                status["confidence"] = min(float(status.get("confidence", 0.0)), 0.3)
        statuses.append(status)

    if statuses:
        sanitized["requirementStatus"] = statuses
    return sanitized, violations, warnings, hallucinated_count


def check_consistency(
    gap: dict, roadmap: dict, requested_weeks: int
) -> tuple[list[Violation], list[dict]]:
    """4) 교차 검증 (설계 §3.8-④).

    - 로드맵 기간이 요청 기간과 맞는가.
    - 로드맵 항목이 참조하는 requirementId 가 실재하는 gap/요구사항인가.
      **없는 요구사항을 위한 학습 계획**은 사용자 시간을 엉뚱한 데 쓰게 만든다.
    - 심각도 high 인 gap 이 로드맵에서 아예 빠지지 않았는가.
      (예산 때문에 의도적으로 뺀 경우는 assumptions 에 기록되므로 여기선 경고만 남긴다)
    """

    violations: list[Violation] = []
    warnings: list[dict] = []

    total_weeks = roadmap.get("totalWeeks")
    if roadmap and requested_weeks and total_weeks not in (None, 0) and total_weeks != requested_weeks:
        violations.append(Violation(
            type="inconsistent",
            location="roadmapResult.totalWeeks",
            detail=f"로드맵 기간({total_weeks}주)이 요청 기간({requested_weeks}주)과 다릅니다.",
        ))
        warnings.append({
            "code": "period_mismatch",
            "message": "로드맵 기간이 요청 기간과 불일치합니다.",
        })

    known_ids = {str(g.get("requirementId")) for g in gap.get("gaps", []) if g.get("requirementId")}
    if known_ids:
        for item in roadmap.get("roadmap", []):
            unknown = [
                rid for rid in (item.get("relatedRequirementIds") or [])
                if rid and str(rid) not in known_ids
            ]
            if unknown:
                violations.append(Violation(
                    type="inconsistent",
                    location=f"roadmapResult.roadmap[{item.get('title')}]",
                    detail=f"실재하지 않는 요구사항을 참조합니다: {unknown}",
                ))
                warnings.append({
                    "code": "orphan_roadmap_item",
                    "message": f"'{item.get('title')}' 항목이 gap 에 없는 요구사항 {unknown} 을 참조합니다.",
                })

        covered = {
            str(rid)
            for item in roadmap.get("roadmap", [])
            for rid in (item.get("relatedRequirementIds") or [])
        }
        uncovered_high = [
            str(g.get("requirementId"))
            for g in gap.get("gaps", [])
            if g.get("severity") == "high" and str(g.get("requirementId")) not in covered
        ]
        if uncovered_high:
            warnings.append({
                "code": "high_gap_uncovered",
                "message": f"심각도 high 인 부족 역량이 로드맵에 없습니다: {uncovered_high}",
            })

    return violations, warnings
