"""자연어 렌더러 (nl_render) — LLM '말하기' 계층의 유일한 창구.

설계 §0-③ / §3.9. 파이프라인의 모든 판단이 끝난 뒤, **이미 확정된 사실**을 사람이
말하듯 서술하는 일만 한다. 여기가 LLM 이 손대는 마지막 지점이자, 갭 분석·로드맵·
대체 경로가 공유하는 렌더러다.

이 모듈의 계약(어기면 존재 이유가 없다):
- **주어진 결정만 서술한다.** 새 사실·수치·판정을 만들지 않는다.
- 스키마에 `summary` 문자열 하나만 둔다. 판정 필드를 주지 않으면 판정을 바꿀 수 없다
  — 프롬프트로 "바꾸지 마라" 하는 것보다 확실하다(파서·프로필과 같은 전략).
- 출력을 **`verify_rules` 의 금지 표현 검사에 통과시킨 뒤에만** 쓴다. LLM 이 "합격
  가능합니다" 를 붙이면 규칙이 잡아내고 결정론 요약으로 되돌린다. 말하기 계층이라고
  검증을 면제받지 않는다.
- LLM 이 없거나 실패해도 **빈 요약을 내지 않는다.** 계산된 사실로 문장을 만든다 —
  요약은 결과의 얼굴이라 비어 있으면 제품이 고장 난 것처럼 보인다.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

_SUMMARY_SYSTEM = """너는 이미 확정된 분석 결과를 사용자에게 말로 전해 주는 역할이다.
**판단하지 않는다.** 충족/미충족, 심각도, 점수는 이미 알고리즘이 정했고 너는 그것을 바꿀 수 없다.

절대 규칙:
- 입력에 있는 사실만 쓴다. **새로운 수치·기술명·회사명·판정을 만들어내지 말 것.**
- **건수는 주어진 값을 그대로 쓴다. 더하거나 빼서 새 총계를 만들지 말 것.**
  `metCount`·`partialCount`·`notMetCount`·`undecidedCount` 는 서로 겹치지 않고, 넷의 합이
  `requirementCount` 다. 직접 센 숫자를 적으면 사용자가 보는 총계가 어긋난다.
- 합격/불합격 가능성을 절대 말하지 말 것. "합격 가능", "무조건", "반드시", "보장" 같은 표현 금지.
  이 서비스는 합격을 예측하지 않는다 — 요구사항 충족도까지만 말한다.
- '판정 불가(uncertain)' 항목을 '부족'이라고 바꿔 말하지 말 것. 모르는 것은 모르는 것이다.
- 사용자를 평가하거나 훈계하지 말 것. 사실을 담담히 전하고 다음 할 일을 안내한다.

형식:
- 3~5문장의 한 문단. 목록·제목·마크다운 없이 자연스러운 한국어 산문.
- 입력에 `diagnosis` 문장이 있으면 그 취지를 **첫 문장**으로 삼아 자연스럽게 녹인다(없으면 생략).
- 순서: (진단) → 무엇이 확인됐는지 → 무엇이 부족한지. 판정까지만 말한다 —
  학습 계획·일정은 네 입력에 없고, 다른 층이 안내한다.
- 담백하고 존중하는 어조. 과장하지 않는다."""


class _Summary(BaseModel):
    """말하기 스키마 — `summary` 하나뿐이다. 판정 필드가 없으니 판정을 못 바꾼다.

    description 을 비우면 모델이 이 칸을 제목처럼 한 줄로 끝낸다(구조화 출력의 알려진 함정).
    """

    summary: str = Field(default="", description=(
        "사용자에게 보여줄 판정 요약 본문. 확인된 것 → 부족한 것 순서로 여러 문장으로 쓴다. "
        "제목이나 한 줄 요약이 아니다. 입력에 없는 사실·수치를 넣지 않는다."))


def _violates_policy(text: str) -> str | None:
    """금지 표현이 있으면 그 표현을 돌려준다. verify_rules 의 사전을 그대로 쓴다."""

    for bad in FORBIDDEN_EXPRESSIONS:
        if bad in text:
            return bad
    return None


# 종합 등급별 진단 문장 (2026-07-21). '합격/불합격'을 말하지 않는다 — 충족도까지만 말한다
# (설계 12.3-2, FORBIDDEN_EXPRESSIONS 원칙). 상은 진단만, 중·하는 로드맵·대안이 뒤따른다.
_DIAGNOSIS_BY_GRADE = {
    "상": "핵심 요구 역량을 대부분 충족합니다. 지원에 충분한 경쟁력이 있습니다.",
    "중": "요구 역량을 부분적으로 충족합니다. 부족한 부분을 보완하면 경쟁력을 높일 수 있습니다.",
    "하": "요구 역량과 격차가 있어 준비가 필요합니다.",
}


def _diagnosis_for(grade: str) -> str:
    """종합 등급 → 진단 문장. 판정불가/미설정이면 진단을 붙이지 않는다(빈 문자열)."""

    return _DIAGNOSIS_BY_GRADE.get(grade, "")


def _deterministic_summary(facts: dict) -> str:
    """계산된 사실만으로 만드는 요약. LLM 없이도 항상 말이 되는 문장을 낸다."""

    met = facts.get("metCount", 0)
    total = facts.get("requirementCount", 0)
    partial = facts.get("partialCount", 0)
    gaps = facts.get("notMetCount", 0)
    undecided = facts.get("undecidedCount", 0)

    parts: list[str] = []
    diagnosis = facts.get("diagnosis", "")
    if diagnosis:
        parts.append(diagnosis)
    parts.append(f"공고 요구사항 {total}건 중 {met}건은 보유 경험으로 근거가 확인됐습니다.")
    if partial:
        parts.append(f"{partial}건은 일부만 확인됐습니다.")
    if gaps:
        parts.append(f"{gaps}건은 근거가 부족하거나 확인되지 않았습니다.")
    if undecided:
        parts.append(f"{undecided}건은 이력서만으로는 판정할 수 없어 미확정으로 남겼습니다.")
    return " ".join(parts)


def _collect_facts(gap: dict, posting: dict) -> dict:
    """요약에 쓸 사실을 계산한다. LLM 에는 **이 값들만** 넘어간다.

    **로드맵 사실은 넘기지 않는다** — 요약은 판정까지만 말한다. 전에는 로드맵 항목·주수를
    넘겨서 LLM 이 "…계획이 총 8주 일정으로 준비되어 있습니다"라고 서술했는데, 그 계획(지도)은
    비동기로 그려지는 별개 산출물이라 화면과 어긋난 채 확정처럼 들렸다(실측 08-04 사용자
    지적). 계획 안내는 렌더 계층(assumedPeriod 고지·다음 행동 제안)이 한다 — 입력에서 빼면
    서술할 수 없다(§2-2: 금지는 프롬프트가 아니라 구조로).

    **건수는 서로 겹치지 않게 낸다** — met + partial + notMet + undecided = requirementCount.
    실측(2026-08-03, 세션 c1470d00): `gapCount` 로 `len(gap["gaps"])`(=12) 를 넘겼는데 그
    목록은 `partially_met` 항목(req-2)을 이미 포함하고 있어서, LLM 이 "전체 14개 중 … 1건
    부분 충족 … 12건 격차 … 1건 판정 불가"(=15건)로 서술했다. 겹치는 수를 나란히 주면 모델은
    그것을 더한다 — 말하기 계층에 산수를 시키지 않는 것이 §1(LLM 은 표현만)의 실제 적용이다.
    """

    statuses = gap.get("requirementStatus", [])
    return {
        "jobTitle": posting.get("jobTitle", ""),
        # 등급 라벨('상'/'판정불가')은 넘기지 않는다 — LLM 이 라벨을 그대로 읊으면 어색하다.
        # 대신 자연어 진단 문장만 넘겨 첫 문장으로 녹이게 한다(판정불가/미설정이면 빈 문자열).
        "diagnosis": _diagnosis_for(gap.get("fitGrade", "")),
        "requirementCount": len(statuses),
        "metCount": sum(1 for s in statuses if s.get("status") == "met"),
        "partialCount": sum(1 for s in statuses if s.get("status") == "partially_met"),
        "undecidedCount": sum(1 for s in statuses if s.get("status") == "uncertain"),
        "notMetCount": sum(1 for s in statuses if s.get("status") == "not_met"),
        "strengths": [s.get("text", "") for s in gap.get("strengths", [])],
        "gapReasons": [g.get("reason", "") for g in gap.get("gaps", [])],
    }


def render_summary(gap: dict, posting: dict) -> tuple[str, list[dict]]:
    """확정된 분석 결과 → 사람이 읽는 판정 요약 한 문단 (로드맵은 서술하지 않는다).

    반환: (요약, warnings). 어떤 경우에도 빈 문자열을 돌려주지 않는다.
    """

    facts = _collect_facts(gap, posting)
    fallback = _deterministic_summary(facts)
    warnings: list[dict] = []

    # 고급 모델 유지 — 사용자 대면 문장인 데다, 경량(gpt-5-nano) 실측에서 오히려 더 느리고
    # (6.4s→15.6s) 문체가 무너졌다. 입력(facts)이 짧아 토큰 절약 효과도 미미 (0724 실측).
    rendered, llm_warnings = run_structured(
        _Summary, _SUMMARY_SYSTEM, json.dumps(facts, ensure_ascii=False), node="nl_render"
    )
    # LLM 미설정/실패는 요약에서 치명적이지 않다 — 결정론 요약으로 조용히 대체한다.
    # (경고는 남겨서 왜 문장이 밋밋한지 추적 가능하게 한다)
    warnings.extend(llm_warnings)

    if rendered is None or not rendered.summary.strip():
        return fallback, warnings

    bad = _violates_policy(rendered.summary)
    if bad:
        # 말하기 계층도 검증을 면제받지 않는다. 규칙을 어긴 문장은 버린다.
        warnings.append({
            "code": "summary_policy_violation",
            "message": f"요약에 금지 표현('{bad}')이 포함되어 결정론 요약으로 대체했습니다.",
        })
        return fallback, warnings

    return rendered.summary.strip(), warnings
