"""sufficiency_rules 유닛 테스트.

이 모듈의 경계선(설계 §5.3)을 못 박는다:
    ✅ "이 사람을 **분석하기에 정보가 충분한가?**"
    ❌ "이 사람이 **이 공고에 충분한가?**"
섞으면 역량이 부족한 사용자에게 질문을 퍼붓는 무례한 제품이 된다.
"""

from jobis_ai.gap_matcher import get_gap_matcher
from jobis_ai.sufficiency_rules import assess, build_questions


def _assess(requirements, profile):
    report = get_gap_matcher().match(requirements, profile)
    return assess(report, profile)


def _req(rid, text, rtype="required"):
    return {"requirementId": rid, "text": text, "type": rtype}


_RICH_PROFILE = {
    "skills": [{"name": "Java"}, {"name": "Spring Boot"}, {"name": "MySQL"}],
    "evidenceMap": [
        {"evidenceId": "ev-1", "text": "Spring Boot 로 주문 API 를 구현했습니다."},
        {"evidenceId": "ev-2", "text": "MySQL 인덱스 튜닝으로 응답시간을 단축했습니다."},
        {"evidenceId": "ev-3", "text": "Docker 로 개발환경을 컨테이너화했습니다."},
    ],
    "skillEvidence": {
        "Spring Boot": ["ev-1"], "MySQL": ["ev-2"], "RDBMS": ["ev-2"],
        "SQL": ["ev-2"], "Docker": ["ev-3"],
    },
}


# --- 충분한 경우: 방해하지 않는다 -----------------------------------------
def test_rich_profile_is_sufficient_and_asks_nothing():
    """근거가 탄탄하면 분석을 진행한다. 스킬 하나(Java)에 근거가 없다고 막지 않는다.

    이걸 막으면 근거가 충분한 사용자한테까지 되묻게 된다(§5.3).
    Java 의 근거 부재는 갭 분석의 reason 이 이미 알려주므로 되묻는 건 중복이다.
    """
    verdict = _assess([_req("req-1", "Java 및 Spring Boot 개발 경험")], _RICH_PROFILE)
    assert verdict.sufficient is True
    assert build_questions(verdict) == [], "진행 가능한데 되묻는 건 방해다"


def test_unevidenced_claim_alone_is_not_blocking():
    verdict = _assess([_req("req-1", "Java 및 Spring Boot 개발 경험")], _RICH_PROFILE)
    codes = {m.code for m in verdict.missing}
    assert "unevidenced_claim" in codes, "질문거리로는 기록한다"
    assert verdict.blocking == [], "다만 분석을 막지는 않는다"


def test_low_qualification_does_not_make_info_insufficient():
    """요구사항을 못 갖춘 것과 정보가 부족한 것은 다르다.

    근거는 풍부한데 요구 역량이 없는 사람은 **정보가 충분**하다 — 그건 갭 분석이 답할 일이지
    질문을 더 던질 일이 아니다.
    """
    verdict = _assess([_req("req-1", "Kubernetes 운영 경험"), _req("req-2", "Terraform 경험")],
                      _RICH_PROFILE)
    assert verdict.sufficient is True


# --- 부족한 경우: 막고 묻는다 ----------------------------------------------
def test_no_evidence_blocks_and_asks():
    thin = {"skills": [{"name": "Java"}], "evidenceMap": [], "skillEvidence": {}}
    verdict = _assess([_req("req-1", "Java 개발 경험")], thin)

    assert verdict.sufficient is False
    assert any(m.code == "no_evidence" and m.blocking for m in verdict.missing)
    questions = build_questions(verdict)
    assert questions, "막았으면 무엇을 알려줘야 하는지 물어야 한다"
    assert all("questionId" in q and q["text"] for q in questions)


def test_few_evidence_blocks():
    thin = {
        "skills": [{"name": "Java"}],
        "evidenceMap": [{"evidenceId": "ev-1", "text": "Java 로 뭔가 했습니다"}],
        "skillEvidence": {"Java": ["ev-1"]},
    }
    verdict = _assess([_req("req-1", "Java 개발 경험")], thin)
    assert verdict.sufficient is False
    assert any(m.code == "few_evidence" for m in verdict.missing)


def test_mostly_undecidable_required_blocks_and_asks_about_them():
    """필수 요구사항을 판정조차 못 했으면 사용자에게 직접 묻는 게 유일한 해결책이다."""
    verdict = _assess(
        [_req("req-1", "경력 3년 이상"), _req("req-2", "원활한 커뮤니케이션 능력")],
        _RICH_PROFILE,
    )
    assert verdict.sufficient is False
    assert verdict.undecidableRequiredCount == 2
    texts = " ".join(q["text"] for q in build_questions(verdict))
    assert "경력 3년 이상" in texts, "판정 못 한 요구사항을 그대로 물어야 한다"


# --- 질문 품질 -------------------------------------------------------------
def test_implied_skills_are_not_asked_separately():
    """"MySQL 경험 알려주세요"와 "SQL 경험 알려주세요"를 따로 물으면 같은 걸 두 번 묻는 꼴이다."""
    thin = {
        "skills": [{"name": "MySQL"}, {"name": "RDBMS"}, {"name": "SQL"}],
        "evidenceMap": [],
        "skillEvidence": {},
    }
    verdict = _assess([_req("req-1", "MySQL 등 RDBMS 설계 및 SQL 활용")], thin)
    subjects = {m.subject for m in verdict.missing if m.code == "unevidenced_claim"}
    assert "MySQL" in subjects
    assert "SQL" not in subjects and "RDBMS" not in subjects, "수반 스킬은 따로 묻지 않는다"


def test_questions_are_capped():
    thin = {
        "skills": [{"name": s} for s in ["Java", "Spring Boot", "AWS", "Docker",
                                         "Kubernetes", "Redis", "Kafka"]],
        "evidenceMap": [],
        "skillEvidence": {},
    }
    reqs = [_req(f"req-{i}", s) for i, s in enumerate(
        ["Java", "Spring Boot", "AWS", "Docker", "Kubernetes", "Redis", "Kafka"], start=1)]
    verdict = _assess(reqs, thin)
    assert len(build_questions(verdict)) <= 5, "너무 많이 물으면 사용자가 이탈한다"
