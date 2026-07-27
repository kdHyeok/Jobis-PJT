"""gap_matcher 유닛 테스트 — 판정 엔진의 계약을 못 박는다.

이 모듈이 파이프라인의 심장이다(설계 §3.5). 여기 임계값이나 규칙이 바뀌면
사용자가 받는 판정이 통째로 달라지므로, **왜 그런 판정이 나오는지**를 테스트로 고정한다.
LLM 을 호출하지 않으므로 전부 결정론이다.
"""

from jobis_ai.gap_matcher import get_gap_matcher, overall_fit, to_gap_payload


def _profile(*, skills=(), evidence=(), skill_evidence=None):
    return {
        "skills": [{"name": s, "level": ""} for s in skills],
        "evidenceMap": [{"evidenceId": eid, "text": txt} for eid, txt in evidence],
        "skillEvidence": skill_evidence or {},
    }


def _req(rid, text, rtype="required"):
    return {"requirementId": rid, "text": text, "type": rtype}


# --- 기본 판정 -------------------------------------------------------------
def test_met_when_all_required_skills_have_evidence():
    report = get_gap_matcher().match(
        [_req("req-1", "Java 개발 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")],
                 skill_evidence={"Java": ["ev-1"]}),
    )
    m = report.matches[0]
    assert m.status == "met"
    assert m.matchedEvidenceIds == ["ev-1"], "판정 근거로 실제 evidenceId 를 인용해야 한다"


def test_met_when_skill_is_claimed_but_unevidenced():
    """이력서에 스킬로 기재만 돼 있어도 met 을 인정한다(2026-07-20 결정).

    근거 문장은 없어도 인용은 하지 않는다 — 없는 근거를 지어내진 않는다.
    """
    report = get_gap_matcher().match(
        [_req("req-1", "Java 개발 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "문서 작업을 했습니다")]),
    )
    m = report.matches[0]
    assert m.status == "met"
    assert m.matchedEvidenceIds == [], "근거가 없으면 근거를 인용하지 않는다"
    assert m.confidence < 1.0, "판정은 통과해도 근거 없는 만큼 신뢰도는 낮게 남는다"


def test_not_met_when_skill_absent_entirely():
    report = get_gap_matcher().match(
        [_req("req-1", "AWS 배포 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")]),
    )
    m = report.matches[0]
    assert m.status == "not_met"
    assert m.missingSkills == ["AWS"]


# --- '없다'와 '모른다'의 구분 (설계 §3.5 / §5) -----------------------------
def test_undecidable_requirement_is_uncertain_not_not_met():
    """기술명도 못 뽑고 임베딩도 없으면 '판정 불가'다. '미충족'이 아니다.

    not_met 은 "이 사람에게 없다"는 주장이고, uncertain 은 "우리가 판정 못 한다"는 고백이다.
    여기서 not_met 으로 찍으면 근거 없이 사람의 결함을 단정하게 된다.
    """
    report = get_gap_matcher().match(
        [_req("req-1", "경력 3년 이상의 서버 개발 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")]),
    )
    m = report.matches[0]
    assert m.status == "uncertain"
    assert m.method == "undecidable"
    assert report.undecidable_count == 1
    assert any(w["code"] == "undecidable_requirements" for w in report.warnings)


def test_uncertain_is_excluded_from_gaps():
    """gap 은 '확인된 부족'이다. 판정 불가를 gap 에 넣으면 로드맵이 그 위에
    '경력 3년을 쌓으세요' 같은 무의미한 계획을 세운다."""
    report = get_gap_matcher().match(
        [_req("req-1", "경력 3년 이상의 서버 개발 경험"), _req("req-2", "AWS 배포 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")]),
    )
    payload = to_gap_payload(report)
    gap_ids = {g["requirementId"] for g in payload["gaps"]}
    assert gap_ids == {"req-2"}, "uncertain(req-1)은 gap 이 아니다"


def test_undecidable_is_not_counted_as_uncovered_in_ratio():
    """판정 못 한 걸 '미달'로 세면 정보 부족을 사용자 탓으로 돌리게 된다."""
    report = get_gap_matcher().match(
        [_req("req-1", "경력 3년 이상"), _req("req-2", "Java 개발 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")],
                 skill_evidence={"Java": ["ev-1"]}),
    )
    assert report.covered_ratio("required") == 1.0, "판정된 것(req-2)만 분모에 든다"


# --- reason 이 판정과 일치해야 한다 (설계 §5) ------------------------------
def test_reason_distinguishes_evidenced_from_claimed():
    """status 가 met 이어도 근거 있음/기재만 됨을 문장에서까지 뭉개면 안 된다."""
    report = get_gap_matcher().match(
        [_req("req-1", "Java 및 Spring Boot 개발 경험")],
        _profile(skills=["Java", "Spring Boot"],
                 evidence=[("ev-1", "Spring Boot 로 API 구현")],
                 skill_evidence={"Spring Boot": ["ev-1"]}),
    )
    m = report.matches[0]
    assert m.status == "met", "둘 다 매치됐으니(기재+근거) met 이다"
    assert "Spring Boot" in m.reason and "근거로 확인" in m.reason
    assert "Java" in m.reason and "근거는 없음" in m.reason


# --- severity 룰 -----------------------------------------------------------
def test_severity_high_only_for_required_not_met():
    report = get_gap_matcher().match(
        [_req("req-1", "AWS 배포 경험"), _req("pref-1", "Docker 경험", "preferred")],
        _profile(),
    )
    gaps = {g["requirementId"]: g["severity"] for g in to_gap_payload(report)["gaps"]}
    assert gaps["req-1"] == "high", "필수인데 못 갖췄으면 high"
    assert gaps["pref-1"] == "low", "우대는 아무리 못 갖춰도 low"


# --- implies 연동 ----------------------------------------------------------
def test_concrete_product_evidence_satisfies_umbrella_requirement():
    """"MySQL 등 RDBMS 설계 및 SQL 활용" 을 MySQL 근거 하나로 충족해야 한다 (§5.1)."""
    report = get_gap_matcher().match(
        [_req("req-1", "MySQL 등 RDBMS 설계 및 SQL 활용 능력")],
        _profile(skills=["MySQL"], evidence=[("ev-2", "MySQL 인덱스 튜닝")],
                 skill_evidence={"MySQL": ["ev-2"], "RDBMS": ["ev-2"], "SQL": ["ev-2"]}),
    )
    assert report.matches[0].status == "met"


# --- scoreBasis ------------------------------------------------------------
def test_score_basis_leaves_uncomputable_fields_none():
    """계산 근거가 없는 항목에 숫자를 만들어 넣으면 그게 지어낸 점수다."""
    report = get_gap_matcher().match(
        [_req("req-1", "Java 개발 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")],
                 skill_evidence={"Java": ["ev-1"]}),
    )
    basis = to_gap_payload(report)["scoreBasis"]
    assert basis["roleRelevance"] is None
    assert basis["domainFit"] is None
    assert basis["techSkill"] == 1.0


def test_score_basis_none_when_nothing_decidable():
    report = get_gap_matcher().match([_req("req-1", "경력 3년 이상")], _profile())
    assert to_gap_payload(report)["scoreBasis"]["techSkill"] is None


def test_domain_fit_computed_from_domain_keyword_matches():
    """domainKeywords 요구사항이 있으면 domainFit 은 그 매칭으로 계산된다(더 이상 무조건 None 아님)."""
    report = get_gap_matcher().match(
        [{"requirementId": "dk-1", "text": "핀테크", "type": "required", "kind": "domain_keyword"}],
        _profile(evidence=[("ev-1", "핀테크 결제 시스템 개발")]),
    )
    basis = to_gap_payload(report)["scoreBasis"]
    assert basis["domainFit"] == 1.0, "근거에 도메인 키워드가 그대로 있으면 met → 1.0"
    assert basis["techSkill"] is None, "도메인 매칭이 techSkill 로 새면 안 된다"


def test_role_relevance_computed_from_seniority_match():
    """seniority 요구사항이 있으면 roleRelevance 는 사다리 비교로 계산된다."""
    report = get_gap_matcher().match(
        [{"requirementId": "sr-1", "text": "주니어급 이상", "type": "required",
          "kind": "seniority", "seniority": "junior"}],
        _profile(),  # 경력 없음 → 0년 → junior → 요구(junior) 충족
    )
    basis = to_gap_payload(report)["scoreBasis"]
    assert basis["roleRelevance"] == 1.0
    assert basis["techSkill"] is None


def test_domain_and_role_stay_none_without_matching_requirements():
    """해당 종류 요구사항이 아예 없으면 여전히 None 이다 — 근거 없으면 숫자를 만들지 않는다."""
    report = get_gap_matcher().match(
        [_req("req-1", "Java 개발 경험")],
        _profile(skills=["Java"], skill_evidence={"Java": ["ev-1"]},
                 evidence=[("ev-1", "Java 로 API 구현")]),
    )
    basis = to_gap_payload(report)["scoreBasis"]
    assert basis["domainFit"] is None
    assert basis["roleRelevance"] is None


# --- 종합 적합도 등급 (overall_fit) ---------------------------------------
def test_overall_fit_high_grade():
    """모든 근거가 강하면 상. 가중 평균 ≥ 0.7."""
    score, grade = overall_fit({"techSkill": 1.0, "projectExperience": 1.0})
    assert score == 1.0
    assert grade == "상"


def test_overall_fit_mid_grade():
    """부분 충족이면 중 (0.4 ~ 0.7 미만)."""
    score, grade = overall_fit({"techSkill": 0.5, "projectExperience": 0.5})
    assert score == 0.5
    assert grade == "중"


def test_overall_fit_low_grade():
    """충족도가 낮으면 하 (< 0.4)."""
    score, grade = overall_fit({"techSkill": 0.2, "projectExperience": 0.0})
    assert grade == "하"


def test_overall_fit_ignores_none_categories():
    """None 카테고리는 분모에서 빠진다 — techSkill 하나만 1.0 이면 종합도 1.0."""
    score, grade = overall_fit(
        {"techSkill": 1.0, "projectExperience": None, "certLanguage": None,
         "roleRelevance": None, "domainFit": None}
    )
    assert score == 1.0
    assert grade == "상"


def test_overall_fit_undecidable_when_no_scores():
    """계산된 카테고리가 하나도 없으면 등급을 단정하지 않는다."""
    score, grade = overall_fit(
        {"techSkill": None, "projectExperience": None, "certLanguage": None,
         "roleRelevance": None, "domainFit": None}
    )
    assert score is None
    assert grade == "판정불가"


def test_grade_boundaries_are_inclusive_at_high_and_mid():
    """경계값: 0.7 은 상, 0.4 는 중 (하한 포함)."""
    assert overall_fit({"techSkill": 0.7})[1] == "상"
    assert overall_fit({"techSkill": 0.4})[1] == "중"
    assert overall_fit({"techSkill": 0.39})[1] == "하"


# --- 강점 ------------------------------------------------------------------
def test_strengths_only_contain_met_requirements():
    report = get_gap_matcher().match(
        [_req("req-1", "Java 개발 경험"), _req("req-2", "AWS 배포 경험")],
        _profile(skills=["Java"], evidence=[("ev-1", "Java 로 API 구현")],
                 skill_evidence={"Java": ["ev-1"]}),
    )
    strengths = to_gap_payload(report)["strengths"]
    assert [s["requirementId"] for s in strengths] == ["req-1"]


def test_empty_requirements_yields_empty_report():
    report = get_gap_matcher().match([], _profile(skills=["Java"]))
    assert report.matches == []
    assert to_gap_payload(report)["gaps"] == []
