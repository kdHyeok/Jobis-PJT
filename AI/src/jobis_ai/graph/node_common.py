"""노드 공통 — 재시도 예산·핸드오프 로그. **여기에 판정을 넣지 않는다.**

`nodes.py`(판단·조립)와 `read_nodes.py`(읽기 계층) 양쪽이 쓰는 것만 둔다. 원래는 셋이 한
파일이었는데, 1,500줄 한 파일이 추출·정규화·룰·로드맵·대안·검증 여섯 책임을 들고 있어
새 판정이 계속 여기 쌓였다(비교분석 §3-1).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from jobis_ai.graph.state import GraphState

# 재시도 상한 (설계 16.2)
MAX_NODE_RETRY = 2
MAX_VERIFY_RETRY = 1


def _log(node: str, message: str, to: str | None = None) -> dict[str, Any]:
    """toolLog/핸드오프 이벤트 한 건 (설계 17.3의 from→to 시각화 연동)."""

    return {
        "node": node,
        "message": message,
        "to": to,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def _mark_generation_failed(empty_model, node: str, warnings: list[dict]) -> None:
    """LLM 호출 실패 시: 가짜 샘플 대신 빈 결과 + 실패 경고 + uncertainty 로 정직하게 처리.

    (키가 아예 없는 개발 모드에서는 mock 샘플을 쓰지만, 키가 있는데 호출이 실패한 경우엔
    그럴듯한 가짜 결과를 내면 안 되므로 이 경로로 온다.)
    """

    empty_model.uncertainties.append("AI 호출 실패로 결과를 생성하지 못했습니다(재시도가 필요합니다).")
    warnings.append({"code": "generation_failed",
                     "message": f"{node}: LLM 결과 생성 실패 — 빈 결과 반환(가짜 폴백 아님)"})


# 오케스트라가 생성 실패한 에이전트에게 "다시 작업"을 지시하는 최대 횟수 (설계 16.2 노드 재시도)
MAX_GEN_RETRY = 1


def _gen_retry_updates(node: str, state: GraphState, failed: bool) -> dict[str, Any]:
    """에이전트 산출물 검증 결과를 상태에 기록한다.

    실패면 nodeFailed 플래그를 세우고 retryCount 를 올린다 → 다음 라우터가 그걸 보고
    같은 에이전트를 다시 부른다(다음 에이전트로 넘어가지 않는다). 성공/개발모드(mock)면 플래그 해제.
    """

    node_failed = dict(state.get("nodeFailed") or {})
    node_failed[node] = failed
    updates: dict[str, Any] = {"nodeFailed": node_failed}
    if failed:
        rc = dict(state.get("retryCount") or {})
        rc[node] = rc.get(node, 0) + 1
        updates["retryCount"] = rc
    return updates


def _should_retry_node(state: GraphState, node: str) -> bool:
    """직전 에이전트가 생성 실패했고 재시도 예산이 남았으면 True(같은 에이전트에게 재지시)."""

    failed = (state.get("nodeFailed") or {}).get(node, False)
    count = (state.get("retryCount") or {}).get(node, 0)
    return bool(failed) and count <= MAX_GEN_RETRY
