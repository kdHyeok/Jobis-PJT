"""roadmap_manager 에이전트 — 로드맵 조회 (개선방안 Phase 4의 조회 전용 MVP).

중(中)갈래에 필요한 것은 자율 루프가 아니라 지속성이다(agent_develop §2.3).
MVP 는 세션에 저장된 로드맵(fit_analysis 산출)을 대화로 조회하는 것까지만 —
수정·진척 체크·리마인더는 checkpointer 도입(Phase 4) 후 이 모듈에 얹는다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult

_MAX_ITEMS_IN_REPLY = 5


def run(session: dict[str, Any]) -> AgentResult:
    roadmap: list[dict] = list(session.get("roadmap") or [])

    if not roadmap:
        return AgentResult(
            reply="저장된 로드맵이 없습니다. 공고 적합도 분석을 실행하면 준비 로드맵이 함께 만들어져요.",
            warnings=[{"code": "no_roadmap", "message": "roadmap_manager: 세션에 로드맵이 없습니다."}],
        )

    lines = []
    for item in roadmap[:_MAX_ITEMS_IN_REPLY]:
        period = f"{item.get('startDate', '')}~{item.get('endDate', '')}".strip("~")
        lines.append(
            f"[{item.get('priority', 'medium')}] {item.get('title', '')}"
            + (f" ({period})" if period else "")
        )

    reply = (
        f"현재 로드맵에 {len(roadmap)}개 항목이 있습니다. "
        + " / ".join(lines)
        + (" …" if len(roadmap) > _MAX_ITEMS_IN_REPLY else "")
        + " — 항목 수정이나 진척 체크 기능은 준비 중이에요."
    )

    return AgentResult(reply=reply, data={"roadmap": roadmap})
