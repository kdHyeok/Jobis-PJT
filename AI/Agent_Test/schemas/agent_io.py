"""agent core 반환 스키마 — AGENTS §2.4.

`run_agent()`의 공개 반환 계약. `meta.tools_called`로 성공 판정(§8)을 검증하고,
FastAPI(task 09)는 이 객체를 success/data 봉투로 감싸기만 한다.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.tool_io import Level


class Meta(BaseModel):
    tools_called: list[str] = Field(default_factory=list)
    level: Optional[Level] = None                   # analyze_gap 결과 (없으면 None)
    run_id: str = ""                                # 대화 단위 식별(로그 연결). scenario는 제거(D11 후속)


class RunAgentResult(BaseModel):
    reply: str                                      # 자연어 최종 응답
    meta: Meta
