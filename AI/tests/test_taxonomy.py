"""skill_taxonomy / role_taxonomy 유닛 테스트.

설계 §5.1(implies 함의 관계)·§5.8(어휘 단일 소유자)의 결정을 못 박는다.
전부 순수 룰이므로 LLM 없이 돈다.
"""

from jobis_ai.role_taxonomy import get_role_taxonomy
from jobis_ai.skill_taxonomy import get_skill_taxonomy


# --- skill_taxonomy: 표준화 -------------------------------------------------
def test_aliases_collapse_to_canonical_name():
    t = get_skill_taxonomy()
    assert t.normalize("ReactJS") == "React"
    assert t.normalize("리액트") == "React"
    assert t.normalize("NodeJS") == "Node.js"
    assert t.normalize("스프링부트") == "Spring Boot"


def test_unknown_skill_survives_normalization():
    """사전에 없는 신기술도 버리지 않는다 — 신기술은 항상 사전보다 먼저 나온다."""
    assert get_skill_taxonomy().normalize("Bun") == "Bun"
    assert get_skill_taxonomy().category_of("Bun") == "etc"


def test_normalize_all_dedups_synonyms():
    t = get_skill_taxonomy()
    assert t.normalize_all(["React", "ReactJS", "리액트", "Java", "자바"]) == ["React", "Java"]


# --- skill_taxonomy: 원문 검색 경계 ----------------------------------------
def test_find_in_text_does_not_match_inside_longer_token():
    """Java 가 JavaScript 안에서 잡히면 갭 판정이 통째로 틀어진다."""
    t = get_skill_taxonomy()
    assert t.find_in_text("JavaScript 개발자") == ["JavaScript"]
    assert set(t.find_in_text("Java 와 JavaScript 둘 다")) == {"Java", "JavaScript"}


def test_find_in_text_matches_two_char_hangul_alias():
    """'도커'는 2글자여도 완결된 단어다 — ASCII 기준(3자)을 적용하면 통째로 놓친다."""
    assert get_skill_taxonomy().find_in_text("도커, 쿠버네티스 사용 경험") == ["Docker", "Kubernetes"]


def test_find_in_text_prefers_longer_alias():
    assert get_skill_taxonomy().find_in_text("Node.js 서버") == ["Node.js"]


# --- skill_taxonomy: implies 함의 관계 (설계 §5.1) --------------------------
def test_rdbms_implies_sql_and_rdbms_from_concrete_product():
    """MySQL 을 썼다면 RDBMS·SQL 을 쓴 것이다.

    이게 없으면 "MySQL 등 RDBMS 설계 및 SQL 활용" 요구사항에서 RDBMS·SQL 을 각각
    따로 증명하라고 요구하게 되어 MySQL 경험자가 미충족으로 찍힌다.
    """
    implied = get_skill_taxonomy().implied_by("MySQL")
    assert "RDBMS" in implied and "SQL" in implied


def test_with_implied_expands_and_dedups():
    result = get_skill_taxonomy().with_implied(["MySQL"])
    assert result[0] == "MySQL"
    assert set(result) == {"MySQL", "RDBMS", "SQL"}


def test_implies_is_recursive():
    """Next.js → React (한 단계 건너뛴 함의도 따라가야 한다)."""
    assert "React" in get_skill_taxonomy().implied_by("Next.js")


def test_spring_boot_does_not_imply_java():
    """엄격히 수반되는 것만 implies 다 — Spring Boot 는 Kotlin 으로도 쓴다.

    이 테스트가 깨졌다면 누군가 편의를 위해 느슨한 함의를 넣은 것이다.
    느슨한 함의는 '근거 없는 스킬 보유'를 만들어낸다(§5.1).
    """
    assert "Java" not in get_skill_taxonomy().implied_by("Spring Boot")
    assert "Spring" in get_skill_taxonomy().implied_by("Spring Boot")


def test_mariadb_is_not_collapsed_into_mysql():
    """다른 제품은 다른 스킬이다 — 별칭으로 뭉개면 이력서의 MariaDB 가 MySQL 로 둔갑한다."""
    assert get_skill_taxonomy().normalize("MariaDB") == "MariaDB"


def test_es6_does_not_resolve_to_elasticsearch():
    """'ES' 를 Elasticsearch 별칭으로 두면 JavaScript 의 ES6 와 충돌한다."""
    assert get_skill_taxonomy().normalize("ES6") == "JavaScript"


# --- role_taxonomy: 분류 ---------------------------------------------------
def test_classify_role_prefers_job_title_over_body():
    roles = get_role_taxonomy()
    assert roles.classify_role("백엔드 개발자", "React 도 조금 씁니다") == "backend"


def test_classify_role_falls_back_to_body_frequency():
    roles = get_role_taxonomy()
    assert roles.classify_role("개발자 채용", "프론트엔드 개발. 프론트엔드 경험 필수.") == "frontend"


def test_classify_seniority_from_explicit_keyword_and_years():
    roles = get_role_taxonomy()
    assert roles.classify_seniority("신입 개발자", "") == "junior"
    assert roles.classify_seniority("개발자", "", years=3) == "mid"
    assert roles.classify_seniority("개발자", "", years=8) == "senior"
    assert roles.classify_seniority("개발자", "", years=12) == "lead"


def test_seniority_years_beat_english_words_inside_other_words():
    """실측(Gno=49638113): 회사 소개 'Global Leading DX Company' 의 'lead' 가 경력 3년 공고를
    lead(10년+)로 분류해, 4년 경력자가 연차 미달로 판정될 수 있었다(D118).

    ① 요구 연차가 있으면 그것이 이긴다  ② ASCII 별칭은 단어 경계로만 맞는다."""
    roles = get_role_taxonomy()
    body = "IEA Global Leading DX Company. 경력 : 3년 이상"
    assert roles.classify_seniority("AI Agent 개발자", body, years=3) == "mid"
    # 연차 근거가 없어도 단어 안에 박힌 'lead' 는 매칭되지 않는다
    assert roles.classify_seniority("AI Agent 개발자", "Global Leading DX Company") == ""
    # 진짜 단어로 쓰인 별칭은 그대로 잡는다
    assert roles.classify_seniority("Tech Lead", "") == "lead"
    assert roles.classify_seniority("신입사원 채용", "") == "junior"


def test_unknown_role_and_seniority_stay_empty_not_guessed():
    """모르면 모른다고 둔다 — 여기서 찍으면 career_graph 가 그 위에 경로를 쌓아 오류가 증폭된다."""
    roles = get_role_taxonomy()
    assert roles.classify_role("사무직", "일반 사무 업무") == ""
    assert roles.classify_seniority("개발자", "우리는 좋은 회사입니다") == ""


def test_normalize_role_absorbs_seniority_prefixed_and_aliases():
    roles = get_role_taxonomy()
    assert roles.normalize_role("senior backend") == "backend"
    assert roles.normalize_role("web-backend") == "backend"
    assert roles.normalize_role("서버개발") == "backend"


def test_role_taxonomy_owns_vocabulary_used_by_career_graph():
    """career_graph 가 쓰는 role 키가 role_taxonomy 사전과 일치해야 한다 (§5.8).

    사전이 갈라지면 'backend' 와 'web-backend' 가 서로 다른 직군이 되는 사고가 난다.
    """
    from jobis_ai.career_graph import _FEEDERS

    roles = get_role_taxonomy()
    for target, feeders in _FEEDERS.items():
        assert roles.is_known_role(target), f"career_graph 의 '{target}' 가 role_taxonomy 에 없다"
        for feeder in feeders:
            assert roles.is_known_role(feeder), f"피더 '{feeder}' 가 role_taxonomy 에 없다"


def test_role_category_llm_pick_fills_the_gap_but_cannot_leave_the_taxonomy():
    """D120: 사전에 없는 표기는 별칭 룰이 못 잇는다(실측 Gno=49638113 "AI Agent 개발자").
    LLM 이 사전 **목록에서 고르고**, 목록 밖 값은 버린다 — career_graph·RAG 가 이 키로
    조회하므로 없는 키는 하류를 조용히 끊는다."""
    from jobis_ai.contracts.domain import NormalizedJobPosting
    from jobis_ai.graph.read_nodes import _apply_rule_extraction
    from jobis_ai.rule_extractor import extract_rules

    def apply(title, llm_pick, text):
        posting = NormalizedJobPosting(jobTitle=title, roleCategory=llm_pick)
        warnings = _apply_rule_extraction(posting, extract_rules(text), text)
        return posting.roleCategory, [w["code"] for w in warnings]

    text = "ㆍ생성형 AI 기반 AI Agent 설계 및 개발\nㆍ경력 3년 이상"
    # ② 별칭이 없는 표기 → LLM 이 고른 사전 키를 쓴다
    assert apply("AI Agent 개발자", "ml_engineer", text)[0] == "ml_engineer"
    # ① 직무명 별칭이 있으면 룰이 이긴다 (LLM 이 다르게 골라도)
    assert apply("백엔드 개발자", "ml_engineer", text)[0] == "backend"
    # 사전 밖 값은 버리고 이유를 남긴다
    role, codes = apply("AI Agent 개발자", "ai_agent_engineer", text)
    assert role == "" and "role_pick_off_taxonomy" in codes
    assert "role_unclassified" in codes
