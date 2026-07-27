"""로드맵 툴(cert_db / skill_to_cert / project_template_db) 유닛 테스트.

설계 §3.6 의 결정을 못 박는다: 로드맵은 LLM 창작이 아니라 정형 DB 조회다.
"""

from jobis_ai.cert_db import get_cert_db
from jobis_ai.project_template_db import get_project_template_db
from jobis_ai.skill_to_cert import get_skill_to_cert


# --- cert_db ---------------------------------------------------------------
def test_easiest_prefers_lighter_certification():
    """같은 스킬을 커버한다면 가벼운 쪽을 권한다 — 로드맵의 목적은 '따게 만드는 것'이다.
    SQL gap 에 SQLP(150h)보다 SQLD(40h)를 먼저 권해야 한다."""
    db = get_cert_db()
    picked = db.easiest(db.get_many(["sqlp", "sqld"]))
    assert picked.key == "sqld"


def test_get_many_skips_unknown_keys_silently():
    """없는 자격증을 지어내지 않는다."""
    certs = get_cert_db().get_many(["sqld", "존재하지-않는-자격증"])
    assert [c.key for c in certs] == ["sqld"]


def test_certifications_have_measurable_completion_data():
    """doneCriteria 가 '자격증 취득'이라 측정 가능해지는 게 이 설계의 핵심 이점이다."""
    for cert in get_cert_db().all():
        assert cert.name and cert.issuer
        assert cert.prepHours > 0, f"{cert.key}: 준비시간이 없으면 스케줄러가 배치할 수 없다"
        assert cert.subjects, f"{cert.key}: 시험과목이 곧 로드맵 tasks 다"
        assert cert.alwaysAvailable or cert.examWindowsPerYear > 0, \
            f"{cert.key}: 상시도 아니고 시행 횟수도 없으면 응시 계획을 세울 수 없다"


def test_exam_dates_are_empty_by_default():
    """시험 일정은 해마다 바뀌므로 코드에 박지 않는다 — 박으면 반드시 낡는다(§3.6 구현 노트).

    비어 있으면 스케줄러가 순차 배치로 폴백한다(없는 날짜를 지어내지 않는다).
    """
    assert all(cert.examDates == () for cert in get_cert_db().all())


# --- skill_to_cert ---------------------------------------------------------
def test_maps_sql_family_to_data_certifications():
    mapper = get_skill_to_cert()
    assert mapper.recommend(["SQL"])["SQL"].key == "sqld"
    assert mapper.recommend(["AWS"])["AWS"].key.startswith("aws-")
    assert mapper.recommend(["Kubernetes"])["Kubernetes"].key in ("cka", "ckad")


def test_skills_without_certification_return_empty_not_forced_match():
    """매핑이 없는 게 정상이다. 억지로 붙이면 "MSA 를 배우려면 정보처리기사를 따세요"가 나온다."""
    mapper = get_skill_to_cert()
    for skill in ["Docker", "MSA", "Kafka", "React", "Spring Boot"]:
        assert mapper.certs_for(skill) == [], f"{skill} 에 억지 자격증이 매핑됐다"
    assert set(mapper.uncovered(["Docker", "SQL", "MSA"])) == {"Docker", "MSA"}


def test_recommend_omits_uncovered_skills():
    """자격증 없는 스킬은 결과에 넣지 않는다 — 호출부가 그걸 보고 프로젝트 과제로 돌린다."""
    assert get_skill_to_cert().recommend(["Docker"]) == {}


def test_alias_input_resolves_to_same_certification():
    mapper = get_skill_to_cert()
    assert mapper.recommend(["마리아DB"])["마리아DB"].key == "sqld"


# --- project_template_db ---------------------------------------------------
def test_relevance_beats_cost_when_choosing_template():
    """시간만 보고 고르면 'MSA 부족'에 5시간 짧다는 이유로 MSA 전용 과제 대신
    '이벤트 드리븐 전환'이 뽑힌다 — 더 싸지만 겨냥이 빗나간 처방이다(§5.5)."""
    db = get_project_template_db()
    assert db.best_for_skill("msa").key == "msa-decompose"
    assert db.best_for_skill("kafka").key == "event-driven"


def test_templates_map_to_dedicated_projects():
    db = get_project_template_db()
    assert db.best_for_skill("docker").key == "docker-containerize"
    assert db.best_for_skill("kubernetes").key == "k8s-deploy"
    assert db.best_for_skill("git").key == "git-collaboration"


def test_unknown_skill_has_no_template():
    assert get_project_template_db().best_for_skill("존재하지않는스킬") is None


def test_fallback_template_exists_for_evidence_gaps():
    """스킬을 특정할 수 없는 gap('기재됐으나 근거 없음')에도 줄 과제가 있어야 한다."""
    fallback = get_project_template_db().fallback()
    assert fallback.targetSkills == (), "폴백은 특정 스킬용이 아니다"
    assert fallback.doneCriteria


def test_all_templates_have_measurable_done_criteria():
    """doneCriteria 를 산출물·수치·URL 로 미리 적어 두는 게 이 DB 의 존재 이유다.

    LLM 이 지어내면 "이해한다" 같은 측정 불가능한 문장이 된다.
    """
    markers = ("URL", "저장소", "스크린샷", "수치", "결과", "기록", "비교", "점수", "로그", "목록")
    for t in get_project_template_db()._by_key.values():
        assert t.tasks and t.estimatedHours > 0
        assert any(m in t.doneCriteria for m in markers), \
            f"{t.key}: doneCriteria 가 측정 가능하지 않다 — {t.doneCriteria!r}"
