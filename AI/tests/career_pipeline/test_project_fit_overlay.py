from jobis_ai.career_pipeline.fit.project_overlay import _education_fact_matches


def test_bachelor_degree_evidence_matches_college_graduate_requirement() -> None:
    assert _education_fact_matches(
        "대졸 이상 학력",
        "전주대학교 컴퓨터공학과 · 학사 · 졸업 · 2020.03. ~ 2026.02.",
    )


def test_it_major_requirement_matches_computer_science_degree() -> None:
    assert _education_fact_matches(
        "IT계열 전공",
        "전주대학교 컴퓨터공학과 · 학사 · 졸업",
    )


def test_unrelated_major_does_not_satisfy_it_major_requirement() -> None:
    assert not _education_fact_matches(
        "IT계열 전공",
        "한국대학교 국어국문학과 · 학사 · 졸업",
    )


def test_high_school_does_not_satisfy_college_graduate_requirement() -> None:
    assert not _education_fact_matches(
        "대졸 이상 학력",
        "전북기계공업고등학교 로봇자동화과 · 고졸 · 졸업",
    )
