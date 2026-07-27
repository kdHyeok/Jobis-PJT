"""로드맵 스케줄러 (roadmap_scheduler) — 항목·순서·기간을 결정론으로 계산한다.

설계 §3.6-⑤. 기존 `_refit_roadmap_to_budget` 을 정식 툴로 승격하고, 예산 재적합에
더해 **주차 배치**까지 여기서 계산한다. 무엇을/언제/얼마나는 알고리즘이 정하고,
LLM 은 문구만 다듬는다.

역할 경계:
- **순수 계산.** LLM/RAG/임베딩 없음.
- 무엇을 배울지(자격증/과제 선택)는 여기서 정하지 않는다. 그건 `skill_to_cert` 와
  `project_template_db` 의 일이고, 이 모듈은 **이미 정해진 항목들을 시간축에 놓는** 일만 한다.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field

from jobis_ai.contracts.domain import RoadmapItem

# 우선순위 정렬 순서 (낮을수록 먼저).
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class PlannedItem:
    """스케줄링 대상 항목 1건 (날짜가 아직 없는 로드맵 항목).

    source: 이 항목이 어디서 왔는지 — "cert"(자격증) | "project"(과제). 추적성용.
    """

    title: str
    goal: str
    tasks: list[str]
    doneCriteria: str
    priority: str
    relatedRequirementIds: list[str]
    estimatedHours: int
    source: str = "project"


@dataclass
class Schedule:
    """스케줄링 결과."""

    items: list[RoadmapItem] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def planned_hours(self) -> int:
        return sum(int(i.estimatedHours or 0) for i in self.items)


def _sort_key(item: PlannedItem) -> tuple[int, int]:
    """우선순위 먼저, 같으면 가벼운 것 먼저.

    같은 우선순위에서 가벼운 것을 앞에 두는 이유: 예산이 잘려도 **뭐라도 끝난 상태**가
    되는 게 낫다. 무거운 걸 먼저 넣으면 기간 내에 아무것도 완료하지 못할 수 있다.
    """

    return (PRIORITY_RANK.get(item.priority, 1), int(item.estimatedHours or 0))


def _fit_to_budget(
    items: list[PlannedItem], budget_hours: int
) -> tuple[list[PlannedItem], list[str]]:
    """시간 예산에 맞춰 우선순위 낮은 항목부터 제외한다.

    - 우선순위(high>medium>low)를 지키고, 같은 순위면 무거운 것부터 제외한다.
    - 최소 1개는 남긴다. 단일 항목이 예산을 넘으면 그 항목 시간을 예산으로 캡한다
      (아무것도 못 하는 계획보다 잘린 계획이 낫다).
    """

    if not budget_hours or not items:
        return items, []

    kept = list(items)
    dropped: list[str] = []

    def _total() -> int:
        return sum(int(i.estimatedHours or 0) for i in kept)

    while _total() > budget_hours and len(kept) > 1:
        # 가장 낮은 우선순위 중 가장 무거운 것을 뺀다 — 같은 값이면 뒤쪽(덜 중요) 우선
        worst = max(
            range(len(kept)),
            key=lambda k: (PRIORITY_RANK.get(kept[k].priority, 1),
                           int(kept[k].estimatedHours or 0), k),
        )
        dropped.append(kept[worst].title)
        kept.pop(worst)

    if _total() > budget_hours and kept:
        kept[0].estimatedHours = budget_hours

    return kept, dropped


def schedule(
    items: list[PlannedItem],
    *,
    start_date: str,
    total_weeks: int,
    weekly_hours: int,
) -> Schedule:
    """항목들을 우선순위대로 시간축에 순차 배치한다.

    각 항목은 `ceil(estimatedHours / weekly_hours)` 주를 차지하며 겹치지 않는다.
    시간 예산(total_weeks × weekly_hours)과 기간 지평(total_weeks) **둘 다** 지킨다 —
    시간 예산만 보면 반올림 누적으로 기간을 넘길 수 있다.
    """

    result = Schedule()
    if not items:
        return result

    budget_hours = max(total_weeks, 0) * max(weekly_hours, 0)
    ordered = sorted(items, key=_sort_key)
    kept, dropped = _fit_to_budget(ordered, budget_hours)
    result.dropped.extend(dropped)

    try:
        cursor = _dt.date.fromisoformat(start_date)
    except ValueError:
        cursor = _dt.date.today()
        result.notes.append(f"시작일 '{start_date}' 을 해석하지 못해 오늘 날짜로 대체했습니다.")

    horizon_end = cursor + _dt.timedelta(weeks=max(total_weeks, 1)) - _dt.timedelta(days=1)
    per_week = max(weekly_hours, 1)

    for item in kept:
        weeks_needed = max(1, math.ceil(int(item.estimatedHours or 0) / per_week))
        item_end = cursor + _dt.timedelta(weeks=weeks_needed) - _dt.timedelta(days=1)

        # 기간 지평을 넘기면 배치하지 않는다. 끝낼 수 없는 일정을 적어 주는 건 거짓말이다.
        if item_end > horizon_end:
            result.dropped.append(item.title)
            continue

        result.items.append(RoadmapItem(
            title=item.title,
            startDate=cursor.isoformat(),
            endDate=item_end.isoformat(),
            goal=item.goal,
            tasks=list(item.tasks),
            doneCriteria=item.doneCriteria,
            priority=item.priority,
            relatedRequirementIds=list(item.relatedRequirementIds),
            estimatedHours=int(item.estimatedHours or 0),
        ))
        cursor = item_end + _dt.timedelta(days=1)

    if result.dropped:
        result.notes.append(
            f"가용 시간({budget_hours}h)·기간({total_weeks}주) 제약에 맞춰 "
            f"우선순위가 낮은 {len(result.dropped)}개 항목을 제외했습니다: {result.dropped}"
        )
    return result
