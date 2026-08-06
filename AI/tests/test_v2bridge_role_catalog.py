"""서비스 경계 직무 taxonomy — LLM 없이 경로·모호성만 검증한다."""

from dataclasses import dataclass

import pytest

from jobis_ai.v2bridge import role_catalog


@dataclass
class Answer:
    question_key: str
    answer_value: str


def test_game_server_is_not_collapsed_into_web_backend():
    posting = {
        "jobTitle": "게임 서버 개발자",
        # 구 코어의 넓은 '서버' 별칭이 만든 값도 브리지에서 근거로 교정한다.
        "roleCategory": "backend",
    }
    raw = "실시간 전투 서버, 매칭 서버 및 TCP/UDP 네트워크 모듈을 개발합니다."

    result = role_catalog.resolve(posting, raw_text=raw)

    assert result.primary_track == "GAME"
    assert result.specialization == "GAME_SERVER"


def test_game_portal_and_billing_stay_backend_with_game_specialization():
    posting = {"jobTitle": "게임 웹 백엔드 개발자", "roleCategory": "backend"}
    raw = "게임 포털과 커뮤니티, 계정 인증 및 결제·과금 API를 개발합니다."

    result = role_catalog.resolve(posting, raw_text=raw)

    assert result.primary_track == "BACKEND"
    assert result.specialization == "GAME_PLATFORM_BACKEND"


def test_mixed_game_client_and_server_requires_user_choice():
    raw = "Unity 클라이언트와 실시간 게임 서버 및 매칭 서버 개발자를 함께 모집합니다."

    question = role_catalog.clarification_question({}, raw_text=raw)

    assert question is not None
    assert question.key == "target_track"
    assert {option.value for option in question.options} == {"unity_client", "game_server"}


def test_mixed_web_roles_require_choice_but_explicit_fullstack_does_not():
    mixed = "프론트엔드(TypeScript/React)와 백엔드(Java/Spring) 개발자를 함께 모집합니다."
    assert role_catalog.clarification_question({}, raw_text=mixed) is not None

    fullstack = "React와 Spring을 모두 담당하는 풀스택 개발자를 모집합니다."
    assert role_catalog.clarification_question({}, raw_text=fullstack) is None
    assert role_catalog.resolve({}, raw_text=fullstack).primary_track == "FULLSTACK"


def test_mixed_backend_and_data_roles_require_user_choice():
    raw = "백엔드 개발자와 데이터 엔지니어를 함께 모집합니다."

    question = role_catalog.clarification_question({}, raw_text=raw)

    assert question is not None
    assert {option.value for option in question.options} == {"backend", "data_engineer"}


def test_generic_recruitment_title_can_use_role_sections_in_body():
    posting = {"jobTitle": "2026 개발 부문 공개 채용", "roleCategory": "mobile"}
    raw = "모바일 앱 개발자와 임베디드 펌웨어 개발자를 모집합니다."

    question = role_catalog.clarification_question(posting, raw_text=raw)

    assert question is not None
    assert {option.value for option in question.options} == {"mobile", "embedded"}


def test_large_multi_role_posting_asks_for_text_instead_of_picking_first_role():
    raw = (
        "백엔드 개발자, 프론트엔드 개발자, 모바일 앱 개발자, "
        "데이터 엔지니어, 보안 엔지니어를 함께 모집합니다."
    )

    question = role_catalog.clarification_question({}, raw_text=raw)

    assert question is not None
    assert question.input_type == "TEXT"
    assert question.options == []


def test_free_text_track_answer_is_normalized():
    answers = [Answer("target_track", "저는 데이터 엔지니어 직무로 분석할게요")]

    result = role_catalog.resolve({}, raw_text="여러 개발 직무 공개 채용", answers=answers)

    assert result.primary_track == "DATA"
    assert result.specialization == "DATA_ENGINEER"


def test_user_selection_wins_and_is_not_asked_twice():
    raw = "Unity 클라이언트와 실시간 게임 서버 개발자를 함께 모집합니다."
    answers = [Answer("target_track", "game_server")]

    result = role_catalog.resolve({}, raw_text=raw, answers=answers)

    assert result.primary_track == "GAME"
    assert result.specialization == "GAME_SERVER"
    assert result.selected_by_user is True
    assert role_catalog.clarification_question({}, raw_text=raw, answers=answers) is None


@pytest.mark.parametrize(
    "engine_role,expected",
    [
        ("backend", "BACKEND"),
        ("frontend", "FRONTEND"),
        ("fullstack", "FULLSTACK"),
        ("mobile", "MOBILE"),
        ("data_engineer", "DATA"),
        ("data_scientist", "DATA"),
        ("ml_engineer", "AI"),
        ("devops", "DEVOPS"),
        ("sre", "DEVOPS"),
        ("security", "SECURITY"),
        ("qa", "QA"),
    ],
)
def test_engine_semantic_role_is_normalized_to_svg_track(engine_role, expected):
    result = role_catalog.resolve({"roleCategory": engine_role})
    assert result.primary_track == expected


def test_cloud_and_embedded_titles_extend_the_svg_tracks_without_skill_whitelists():
    cloud = role_catalog.resolve(
        {"jobTitle": "클라우드 엔지니어", "roleCategory": "devops"}
    )
    embedded = role_catalog.resolve(
        {}, raw_text="임베디드 펌웨어 개발자 모집: MCU 제어 소프트웨어 개발"
    )

    assert cloud.primary_track == "CLOUD"
    assert embedded.primary_track == "EMBEDDED"


def test_unclassified_role_fails_explicitly_instead_of_defaulting_to_backend():
    with pytest.raises(ValueError, match="정규화할 근거가 부족"):
        role_catalog.resolve({"jobTitle": "일반 사무직", "roleCategory": ""})
