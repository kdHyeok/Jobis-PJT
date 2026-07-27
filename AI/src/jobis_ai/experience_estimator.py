"""사용자 경력 연차 추정 (experience_estimator) — 순수 룰, LLM 미사용.

gap_matcher 의 seniority 비교(공고 요구 연차 vs 사용자 연차)를 위해 `experiences` 항목에서
총 근무 개월수를 추정한다. 판정 우선순위:

  ① 항목(role/summary)에 명시된 "3년 2개월" 같은 문구를 그대로 읽는다 — 이게 있으면
     날짜 계산보다 신뢰도가 높다(본인이 직접 밝힌 값).
  ② 없으면 period 를 날짜 구간("2022.03 - 2023.08", "2022.03 ~ 현재" 등)으로 파싱해 계산한다.
  ③ 둘 다 실패하면 그 항목은 '결측'으로 남긴다.

**결측 항목이 하나라도 있으면 총 연차는 None 이다** — 일부만 합산하면 실제보다 적게
잡혀 사용자에게 불리한 오판정이 나온다. None 은 "0년"과 다르다: gap_matcher 가 이걸
`uncertain`으로 판정하고, 필요하면 check_sufficiency 가 사용자에게 되묻는다(§3.3).
이 모듈은 스스로 질문을 만들지 않는다 — "무엇을 물을지"는 sufficiency_rules 의 몫이다.

**직군 관련성 필터(target_role_category)**: 연차는 아무 경력이나 합산하면 안 된다 —
백엔드 공고에 미술학원 강사 경력을 더하면 안 된다. `target_role_category`가 주어지면
`role_taxonomy.classify_role()`로 각 경력 항목의 직군을 추정해 **공고 직군과 같은 항목만**
합산 대상으로 삼는다. 직군이 다르거나(무관) 아예 못 정하면(애매) **둘 다 제외**한다 —
애매한 걸 넣으면 과대평가, 결측으로 처리해 매번 되물으면 사용자 피로만 커진다는
판단이다(제외 쪽이 '모른다'보다 실용적이라고 결정함, 2026-07-20 논의).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from jobis_ai.role_taxonomy import get_role_taxonomy

# 본문에 직접 적힌 "N년 M개월" 표기. 4자리 연도(2022년)와 헷갈리지 않도록
# 앞자리가 다른 숫자로 이어지지 않는 1~2자리 숫자만 잡는다((?<!\d)).
_EXPLICIT_TENURE = re.compile(r"(?<!\d)(\d{1,2})\s*년(?:\s*(\d{1,2})\s*개월)?")

# period 안의 "YYYY.MM" / "YYYY-MM" / "YYYY/MM" / "YYYY년 MM월" 표기.
_YEAR_MONTH = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})")

_ONGOING_MARKERS = ("현재", "재직중", "재직 중", "진행중", "진행 중", "present")


@dataclass
class ExperienceEstimate:
    """총 근무 개월수 추정 결과.

    totalMonths 가 None 이면 '모른다' — 0으로 찍지 않는다(§ docstring 참고).
    """

    totalMonths: int | None
    resolvedCount: int = 0
    unresolvedEntryIds: list[str] = field(default_factory=list)


def _explicit_months(text: str) -> int | None:
    match = _EXPLICIT_TENURE.search(text)
    if not match:
        return None
    years = int(match.group(1))
    months = int(match.group(2)) if match.group(2) else 0
    return years * 12 + months


def _period_months(period: str) -> int | None:
    dates = _YEAR_MONTH.findall(period)
    if not dates:
        return None

    start_y, start_m = int(dates[0][0]), int(dates[0][1])
    if len(dates) >= 2:
        end_y, end_m = int(dates[1][0]), int(dates[1][1])
    elif any(marker in period for marker in _ONGOING_MARKERS):
        today = date.today()
        end_y, end_m = today.year, today.month
    else:
        return None

    months = (end_y - start_y) * 12 + (end_m - start_m)
    return months if months >= 0 else None


def _entry_months(entry: dict) -> int | None:
    text = f"{entry.get('role', '')} {entry.get('summary', '')}"
    explicit = _explicit_months(text)
    if explicit is not None:
        return explicit
    return _period_months(str(entry.get("period", "")))


def _is_relevant(entry: dict, target_role_category: str) -> bool:
    """이 경력 항목이 공고 직군과 같은 직군인가. 다르거나 모르면 False(제외)."""

    role_category = get_role_taxonomy().classify_role(
        str(entry.get("role", "")), str(entry.get("summary", ""))
    )
    return bool(role_category) and role_category == target_role_category


def estimate_experience_months(
    profile: dict, *, target_role_category: str = ""
) -> ExperienceEstimate:
    """profile['experiences'] → 총 근무 개월수 추정.

    target_role_category 가 주어지면 그 직군과 무관한(또는 직군을 못 정한) 경력은
    합산 전에 걸러낸다(모듈 상단 docstring 참고). 안 주면 필터 없이 전부 대상으로 삼는다
    (예: 공고 직군 자체를 못 정한 경우 — 걸러낼 기준이 없으므로).

    경력 항목이 아예 없으면(신입/무경력, 또는 관련 경력이 전부 걸러진 경우) 0개월로
    확정한다 — 이건 '결측'이 아니라 '없음'이 명확한 경우다. 항목은 있는데 기간을 못
    읽은 게 있을 때만 None 이 된다.
    """

    entries = profile.get("experiences") or []
    if target_role_category:
        entries = [e for e in entries if _is_relevant(e, target_role_category)]
    if not entries:
        return ExperienceEstimate(totalMonths=0)

    total = 0
    resolved = 0
    unresolved: list[str] = []
    for entry in entries:
        months = _entry_months(entry)
        if months is None:
            unresolved.append(str(entry.get("id", "")))
            continue
        total += months
        resolved += 1

    if unresolved:
        return ExperienceEstimate(totalMonths=None, resolvedCount=resolved, unresolvedEntryIds=unresolved)
    return ExperienceEstimate(totalMonths=total, resolvedCount=resolved)
