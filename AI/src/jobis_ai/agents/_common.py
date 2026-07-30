"""에이전트 공용 헬퍼 — 세션 자산에서 정규화 프로필 확보, LLM 이 정한 인자 읽기."""

from __future__ import annotations

from typing import Any

from jobis_ai.graph.nodes import build_user_profile


def agent_arg(session: dict[str, Any], agent: str, name: str) -> str:
    """플래너(LLM)가 이 에이전트에 넘긴 인자 값. 없으면 빈 문자열.

    값이 없으면 에이전트는 **기존대로 세션 자산만 보고** 동작해야 한다 — 인자는 발화에
    값이 실제로 있을 때만 오는 선택 통로다(검증기가 선언된 이름만 통과시킨다).
    """

    args = session.get("_agentArgs") or {}
    return str((args.get(agent) or {}).get(name) or "").strip()


def ensure_posting_text(session: dict[str, Any]) -> tuple[dict | None, list[dict]]:
    """job_posting 자산이 URL 원천이면 지금 수집해 **원문 텍스트 자산으로 승격**한다.

    URL 은 주소일 뿐 내용이 아니다 — 자산으로 남겨 두면 쓰는 곳(파싱·판정)마다 다시
    수집한다: 느리고, 페이지가 바뀌면 같은 대화 안에서 공고 내용이 갈린다. 첫 소비자가
    한 번 수집해 원문을 자산으로 굳히고, 어디서 왔는지는 `sourceUrl` 로 남긴다(D62).

    수집 실패 시 자산을 바꾸지 않는다(다음 턴 재시도 여지) — 경고만 올린다.
    캐시 규약은 ensure_profile 과 같다(write-back 턴에서는 스테이징만).
    반환: (승격/기존 posting, warnings)
    """

    posting = session.get("job_posting")
    if not posting or (posting.get("sourceType") or "text").lower() != "url":
        return posting, []

    from jobis_ai.extract import extract_text  # 지연 임포트: url 자산일 때만 필요

    url = (posting.get("value") or "").strip()
    extracted = extract_text(posting)
    if not extracted.text:
        return posting, extracted.warnings

    promoted = {"sourceType": "text", "value": extracted.text, "sourceUrl": url}
    session["job_posting"] = promoted     # 이번 턴 안에서 뒤 단계가 바로 쓰도록
    staged = session.get("_stagedUpdates")
    if isinstance(staged, dict):
        staged["job_posting"] = promoted
    else:
        session_id = session.get("_sessionId")
        if session_id:
            from jobis_ai.orchestrator.session import get_session_store

            get_session_store().update(str(session_id), {"job_posting": promoted})
    return promoted, extracted.warnings


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
