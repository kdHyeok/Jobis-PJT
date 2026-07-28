"""career_graph 스캐폴딩 검증 — 목표 직군 → 하위/징검다리 직군 도출 규칙."""

from jobis_ai.career_graph import SubRole, get_career_graph


def test_lower_seniority_derived_from_higher_target():
    """senior backend → 낮은 연차(mid/junior/intern) 하위 직군이 나온다."""
    subs = get_career_graph().derive_sub_roles("backend", "senior")

    lowers = [s for s in subs if s.relation == "lower_seniority"]
    assert lowers, "낮은 연차 경로가 있어야 한다"
    assert all(s.roleCategory == "backend" for s in lowers)
    sens = {s.seniority for s in lowers}
    assert sens <= {"mid", "junior", "intern"}, "목표(senior)보다 낮은 연차만"
    assert "senior" not in sens and "lead" not in sens


def test_stepping_stone_uses_feeder_roles():
    """backend 의 징검다리는 피더 직군(fullstack)의 진입 연차로 제안된다."""
    subs = get_career_graph().derive_sub_roles("backend", "senior")

    stones = [s for s in subs if s.relation == "stepping_stone"]
    assert any(s.roleCategory == "fullstack" and s.seniority == "junior" for s in stones)


def test_role_alias_normalized():
    """파서가 표준화 안 한 원문('web-backend')도 흡수해 backend 로 처리한다."""
    subs = get_career_graph().derive_sub_roles("web-backend", "senior")
    assert any(s.roleCategory == "backend" for s in subs)


def test_unknown_role_degrades_gracefully():
    """모르는 직군이라도 예외 없이 빈 목록/부분 결과를 돌려준다(그래프를 죽이지 않는다)."""
    subs = get_career_graph().derive_sub_roles("우주비행사", "senior")
    assert isinstance(subs, list)  # feeders 없음 → lower_seniority 도 role 미매칭이라 비어도 정상


def test_junior_target_has_no_lower_but_may_have_stones():
    """이미 낮은 연차(junior)면 lower_seniority 는 intern 뿐이거나 없고, 무한루프 없이 끝난다."""
    subs = get_career_graph().derive_sub_roles("frontend", "junior")
    for s in subs:
        assert isinstance(s, SubRole)
        if s.relation == "lower_seniority":
            assert s.seniority == "intern"


def test_max_roles_caps_result():
    subs = get_career_graph().derive_sub_roles("backend", "lead", max_roles=3)
    assert len(subs) <= 3


def test_to_query_terms_returns_labels():
    graph = get_career_graph()
    subs = graph.derive_sub_roles("backend", "senior")
    terms = graph.to_query_terms(subs)
    assert terms and all(isinstance(t, str) and t for t in terms)
