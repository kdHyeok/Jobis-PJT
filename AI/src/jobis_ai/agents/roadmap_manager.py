"""roadmap_manager — **도구.** 세션에 저장된 로드맵 조회 (LLM 없음).

말을 하지 않는다: 데이터만 내고 문장은 `tool_render.render_roadmap_manager` 가 만든다
(AgentSpec docstring 의 tool/agent 구분). 그래서 문구를 고칠 때 이 파일은 건드리지 않는다.

수정·진척 체크·리마인더는 checkpointer 도입 후 얹는다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult


def run(session: dict[str, Any]) -> AgentResult:
    roadmap: list[dict] = list(session.get("roadmap") or [])
    warnings = ([] if roadmap else
                [{"code": "no_roadmap", "message": "roadmap_manager: 세션에 로드맵이 없습니다."}])
    return AgentResult(data={"roadmap": roadmap}, warnings=warnings)
