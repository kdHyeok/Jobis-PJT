"""에이전트 공용 헬퍼 — 세션 자산에서 정규화 프로필 확보."""

from __future__ import annotations

from typing import Any

from jobis_ai.graph.nodes import build_user_profile


def ensure_profile(session: dict[str, Any]) -> tuple[dict, list[dict]]:
    """세션에서 정규화 프로필을 얻는다. 없으면 이력서 원천으로 빌드해 세션에 캐시한다.

    프로필 빌드는 기존 build_user_profile 노드를 그대로 재사용한다(추출 규율·환각 방어 포함).
    반환: (profile dict, warnings)

    캐시는 **저장소를 거쳐** 쓴다. 세션 dict 는 복사본이라 여기서 직접 고쳐도 남지 않는다
    (영속 저장소로 바뀌면서 생긴 규약 — session.py 참고). 저장 대상 세션을 알 수 있을 때만
    캐시하고, 모르면 이번 호출에만 쓰고 버린다.
    """

    if session.get("profile"):
        return session["profile"], []

    resume = session.get("resume")
    updates = build_user_profile({"resumeInput": resume})
    profile = updates.get("normalizedUserProfile") or {}
    warnings = updates.get("warnings") or []

    # 같은 대화에서 프로필을 두 번 빌드하지 않도록 세션에 캐시한다(LLM 호출 절약).
    session["profile"] = profile          # 이번 턴 안에서 뒤 단계가 바로 쓰도록
    staged = session.get("_stagedUpdates")
    if isinstance(staged, dict):
        # write-back 턴(chat.handle_chat) 안 — 저장은 턴 끝에 한 번, 여기서는 스테이징만.
        # 직접 store.update 를 하면 턴 끝 write-back 의 profile=None(첨부 무효화 표식)이
        # 방금 만든 캐시를 도로 덮어쓴다.
        staged["profile"] = profile
    else:
        session_id = session.get("_sessionId")
        if session_id:
            from jobis_ai.orchestrator.session import get_session_store

            get_session_store().update(str(session_id), {"profile": profile})
    return profile, warnings
