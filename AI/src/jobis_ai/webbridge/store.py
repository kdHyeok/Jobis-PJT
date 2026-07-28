"""직전 분석 결과 보관 — 웹의 단발 HTTP 요청이 판정 근거를 다시 쓸 수 있게.

웹은 로드맵을 만들 때 `/roadmap` 에 {company, role, routeKind, goalCompany} 만 보낸다
(SavedRoadmapService). 즉 "누구의 어떤 분석"인지가 요청에 없다. 그래서 WS 분석이 끝날 때
그 결과를 회사·직무 키로 잠깐 들고 있다가, 곧바로 이어지는 /roadmap·/roadmap-ask 요청에서
같은 근거(요건 판정·로드맵)를 재사용한다.

프로세스 안에만 있는 개발용 캐시다. 서버를 재시작하면 사라지고, 그때는 핸들러가 근거 없이
일반적인 답으로 폴백한다(없는 근거를 만들어내지 않는다).

한계: 키가 (회사, 직무)라서 같은 회사·직무를 여러 사용자가 동시에 분석하면 마지막 것이 이긴다.
정확히 하려면 웹이 analysisId 를 함께 보내면 되지만, 지금은 웹을 건드리지 않는다는 전제로 둔다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Optional

_MAX_ENTRIES = 32

_lock = threading.Lock()
_recent: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
_last: Optional[dict[str, Any]] = None


def _key(company: str, role: str) -> tuple[str, str]:
    return ((company or "").strip(), (role or "").strip())


def remember(state: dict[str, Any]) -> None:
    """분석 최종 상태를 회사·직무 키로 보관한다."""

    global _last
    posting = state.get("normalizedJobPosting") or {}
    company = posting.get("companyName") or ""
    role = posting.get("jobTitle") or posting.get("roleCategory") or ""
    with _lock:
        _last = state
        _recent[_key(company, role)] = state
        _recent.move_to_end(_key(company, role))
        while len(_recent) > _MAX_ENTRIES:
            _recent.popitem(last=False)


def recall(company: str, role: str = "") -> Optional[dict[str, Any]]:
    """회사(+직무)로 분석 상태를 찾는다. 직무까지 맞는 게 없으면 회사만으로 찾고,
    그것도 없으면 가장 최근 분석을 준다 — 단발 요청이 직전 분석의 후속인 경우가 대부분이다."""

    with _lock:
        hit = _recent.get(_key(company, role))
        if hit is not None:
            return hit
        target = (company or "").strip()
        if target:
            for (c, _r), state in reversed(_recent.items()):
                if c == target:
                    return state
        return _last
