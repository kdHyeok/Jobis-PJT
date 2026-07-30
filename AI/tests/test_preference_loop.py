"""preference_intake 자기 루프 — 도구는 결정론, 분기점은 LLM 이 못 바꾼다.

conftest 가 LLM 을 강제 미설정하므로 `run()` 은 결정론 폴백 경로로 답한다(기존 테스트가
그쪽을 덮는다). 여기서는 **루프의 도구와 상태 규율**을 직접 검사한다 — 도구가 전부
결정론이라 LLM 없이 전수 검사가 가능하다는 것이 이 설계의 이점이다.
"""

from __future__ import annotations

from jobis_ai.agents.preference_intake import (
    _DIM_KEYS,
    _TOOLS,
    _parse_labeled,
    _sufficient,
    _sync_session,
)


def _state(session: dict | None = None, **prefs) -> dict:
    base = {**{k: [] for k in _DIM_KEYS}, "turns": 0, **prefs}
    state = {"prefs": base, "_requested": "", "_sessionBase": session or {}}
    _sync_session(state)
    return state


# --- 라벨 미니포맷 파싱 -----------------------------------------------------------
def test_labeled_lines_map_to_dimensions():
    found, experience = _parse_labeled("직군: 백엔드\n도메인: 커머스, 핀테크\n경력: 신입")
    assert found == {"roles": ["백엔드"], "domains": ["커머스", "핀테크"]}
    assert experience == "신입"


def test_unknown_labels_are_dropped_not_guessed():
    """모르는 라벨은 버린다 — 어디에 넣을지 추측하면 선호가 조용히 오분류된다."""

    found, experience = _parse_labeled("연봉: 5000\n직군: 데이터")
    assert found == {"roles": ["데이터"]}
    assert experience == ""


# --- record_preference: 기록 + **충분성 판정을 관찰로 돌려준다** ---------------------
def test_record_reports_what_is_known_and_whether_enough():
    """관찰에 '충분한가'가 실려야 LLM 이 다음 행동을 정할 수 있다 — 이게 재선택의 입력이다."""

    state = _state()
    observation, _ = _TOOLS["record_preference"].run(state, "직군: 백엔드")
    assert state["prefs"]["roles"] == ["백엔드"]
    assert "충분한가: 아니오" in observation
    assert "아직 모르는 것" in observation

    observation, _ = _TOOLS["record_preference"].run(state, "도메인: 커머스")
    assert "충분한가: 예" in observation, "차원 2개면 분기점을 넘는다(룰)"
    assert _sufficient(state["prefs"])


def test_record_without_labels_changes_nothing():
    """라벨을 못 찾으면 아무것도 기록하지 않고, 어떻게 부르라고 알려준다."""

    state = _state()
    observation, _ = _TOOLS["record_preference"].run(state, "백엔드 하고 싶어요")
    assert state["prefs"]["roles"] == []
    assert "기록하지 않았" in observation


def test_role_terms_are_not_duplicated_into_domains():
    """직군 표현이 도메인·회사로 중복 분류되는 것을 도구가 정리한다(기존 규율 보존)."""

    state = _state()
    _TOOLS["record_preference"].run(state, "직군: 백엔드\n도메인: 백엔드")
    assert state["prefs"]["roles"] == ["백엔드"]
    assert state["prefs"]["domains"] == []


def test_experience_level_is_single_valued_and_not_a_dimension():
    """연차는 목록이 아니고 선호 '차원'도 아니다 — 찾을 대상이 아니라 걸러낼 조건이다."""

    state = _state()
    _TOOLS["record_preference"].run(state, "경력: 신입")
    assert state["prefs"]["experienceLevel"] == "신입"
    assert not _sufficient(state["prefs"]), "연차만으로는 분기점을 넘지 않는다"


# --- 상태 규율: 진짜 세션을 고치지 않는다 --------------------------------------------
def test_working_preferences_reach_the_delegate_but_not_the_real_session():
    """작업 선호는 **세션 사본**에만 얹는다.

    위임(preview_postings)이 지금 조건으로 검색하려면 사본에 선호가 있어야 하고, 동시에
    진짜 세션을 고치면 "턴의 상태 전이는 오케스트레이터 독점"(chat.py 규약)이 깨진다.
    저장은 sessionUpdates 로만 일어난다.
    """

    real = {"history": [], "userId": 7}
    state = _state(real)
    _TOOLS["record_preference"].run(state, "직군: 백엔드")

    assert state["_session"]["preferences"]["roles"] == ["백엔드"]   # 위임이 볼 사본
    assert "preferences" not in real, "진짜 세션은 건드리지 않는다"
    assert state["_session"]["userId"] == 7, "사본은 원본의 나머지를 그대로 갖는다"


# --- request_material: 효과는 코드가 정한다 -----------------------------------------
def test_request_material_records_kind_for_the_caller():
    state = _state()
    observation, _ = _TOOLS["request_material"].run(state, "공고")
    assert state["_requested"] == "job_posting"
    # 관찰은 **사실만** 담는다(ToolSpec 규약) — 지시·권유가 들어가면 답변이 도구 동작을 서술한다.
    assert "안내하세요" not in observation
    assert "붙여넣기" in observation

    _TOOLS["request_material"].run(state, "이력서")
    assert state["_requested"] == "resume"


def test_request_material_rejects_unknown_kind():
    state = _state()
    _TOOLS["request_material"].run(state, "포트폴리오")
    assert state["_requested"] == ""


# --- 위임 통로 --------------------------------------------------------------------
def test_preview_postings_is_whitelisted_to_job_recommend_only():
    """위임은 선언한 상대만 — 등록돼 있다고 아무나 부르면 액션 스페이스 제한이 무의미하다."""

    state = _state({"preferences": {"roles": ["백엔드"]}})
    observation, _ = _TOOLS["preview_postings"].run(state, "fit_analysis")
    assert "물어볼 수 없습니다" in observation


def test_preview_postings_refuses_when_nothing_to_search_with():
    """전제(이력서 또는 선호)가 없으면 실행하지 않고 그 사실을 관찰로 돌려준다."""

    state = _state()
    observation, _ = _TOOLS["preview_postings"].run(state, "job_recommend")
    assert "지금 실행할 수 없습니다" in observation


def test_preview_postings_runs_once_preferences_are_recorded():
    """선호를 기록하면 그 조건으로 실제 공고를 확인할 수 있다 — **관찰이 다음 질문을 바꾼다.**"""

    state = _state()
    _TOOLS["record_preference"].run(state, "직군: 백엔드")
    observation, _ = _TOOLS["preview_postings"].run(state, "job_recommend")
    assert "지금 실행할 수 없습니다" not in observation
    assert "job_recommend" in observation
