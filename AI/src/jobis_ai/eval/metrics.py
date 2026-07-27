"""평가 지표 (설계 18.1) — 순수 함수. 이미 산출된 출력에만 의존한다(LLM 불필요).

각 함수는 dict 를 반환하며, 러너가 케이스별/전체로 집계한다.
정보가 없는 정답 필드는 추측하지 않고 None 으로 두는 것을 전제로 한다(설계 18.2).
"""

from __future__ import annotations

import re

# 표현 정책 지표는 검증 게이트와 동일한 규칙을 써야 하므로 단일 출처를 재사용한다.
# (규칙의 정본은 verify_rules — 노드가 아니다. 지표와 게이트가 다른 사전을 쓰면
#  "지표는 깨끗한데 게이트는 막는" 상황이 생긴다)
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

_TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _is_match(pred: str, gold: str, threshold: float) -> bool:
    """두 요구사항 문장이 같은 항목인지 근사 판정(토큰 Jaccard 또는 포함관계)."""

    a, b = _tokens(pred), _tokens(gold)
    if not a or not b:
        return False
    if a <= b or b <= a:  # 한쪽이 다른 쪽을 포함
        return True
    inter = len(a & b)
    union = len(a | b)
    return (inter / union) >= threshold


# ---------------------------------------------------------------------------
# 1) 공고 파싱 F1 (설계 18.1) — 라벨 기반
# ---------------------------------------------------------------------------
def requirement_f1(predicted: list[str], gold: list[str], *, threshold: float = 0.5) -> dict:
    """추출된 요구사항 vs 정답 요구사항의 근사 매칭 F1.

    자유 문장 특성상 정확 일치가 아니라 토큰 유사도로 매칭한다(threshold 조정 가능).
    """

    remaining = list(gold)
    tp = 0
    for p in predicted:
        for i, g in enumerate(remaining):
            if _is_match(p, g, threshold):
                tp += 1
                remaining.pop(i)
                break
    fp = len(predicted) - tp
    fn = len(gold) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


# ---------------------------------------------------------------------------
# 2) 근거성 / Groundedness (설계 18.1) — 결정적
# ---------------------------------------------------------------------------
def groundedness(requirement_status: list[dict], evidence_ids: set[str] | list[str]) -> dict:
    """판정이 인용한 근거 중 실제 evidenceMap 에 존재하는 비율.

    1.0 이면 환각 인용 없음. 낮을수록 존재하지 않는 근거(환각)를 많이 인용.
    """

    valid = set(evidence_ids or [])
    total = 0
    grounded = 0
    hallucinated = 0
    for rs in requirement_status or []:
        for eid in rs.get("matchedEvidenceIds", []) or []:
            total += 1
            if eid in valid:
                grounded += 1
            else:
                hallucinated += 1
    score = grounded / total if total else 1.0  # 인용이 없으면 환각도 없음 → 1.0
    return {"citations": total, "grounded": grounded, "hallucinated": hallucinated,
            "groundedness": round(score, 4)}


# ---------------------------------------------------------------------------
# 3) 표현 정책 위반율 (설계 18.1) — 결정적 (검증 게이트와 동일 규칙)
# ---------------------------------------------------------------------------
def policy_violations(texts: list[str], forbidden: list[str] | None = None) -> dict:
    """금지 표현(합격/불합격 단정 등) 출현 수. 0 이 목표."""

    rules = forbidden if forbidden is not None else FORBIDDEN_EXPRESSIONS
    hits: list[str] = []
    for text in texts or []:
        for bad in rules:
            if bad in (text or ""):
                hits.append(bad)
    return {"violations": len(hits), "matched": sorted(set(hits))}


# ---------------------------------------------------------------------------
# 4) 로드맵 제약 준수 (설계 18.1) — 결정적
# ---------------------------------------------------------------------------
_ROADMAP_REQUIRED_FIELDS = ("title", "startDate", "endDate", "doneCriteria")


def roadmap_compliance(roadmap_result: dict, weeks: int, weekly_hours: int) -> dict:
    """시간 예산 초과 여부·필수 필드 누락 수 검사."""

    items = (roadmap_result or {}).get("roadmap", [])
    budget = (weeks or 0) * (weekly_hours or 0)
    planned = sum(int(i.get("estimatedHours", 0) or 0) for i in items)
    missing = 0
    for i in items:
        for f in _ROADMAP_REQUIRED_FIELDS:
            if not (i.get(f) or "").strip() if isinstance(i.get(f), str) else not i.get(f):
                missing += 1
    over_budget = bool(budget) and planned > budget
    return {"items": len(items), "plannedHours": planned, "budgetHours": budget,
            "overBudget": over_budget, "missingFields": missing,
            "compliant": (not over_budget) and missing == 0 and len(items) > 0}
