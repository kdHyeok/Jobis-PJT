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


def test_few_evidence_warns_but_does_not_block():
    """**정책이 뒤집혔다** (2026-08-03). 전에는 근거 1건이면 분석을 멈췄다.

    근거가 1건이라도 있으면 판정할 재료는 있는 것이고, 신뢰도가 낮다는 사실은 이미
    `confidence` 와 이 경고에 남는다. 1건 때문에 멈추면 사용자는 "이력서를 냈는데
    아무것도 안 나온다"를 겪는다 — 실측에서 지도가 통째로 안 생긴 경로가 이것이었다.
    """

    thin = {
        "skills": [{"name": "Java"}],
        "evidenceMap": [{"evidenceId": "ev-1", "text": "Java 로 뭔가 했습니다"}],
        "skillEvidence": {"Java": ["ev-1"]},
    }
    verdict = _assess([_req("req-1", "Java 개발 경험")], thin)
    assert verdict.sufficient is True
    # 낮은 신뢰도라는 사실 자체는 삼키지 않는다(§2-6).
    assert any(m.code == "few_evidence" and not m.blocking for m in verdict.missing)


def test_zero_evidence_still_blocks():
    """0건은 신뢰도가 낮은 게 아니라 **잴 것이 없는** 것이다 — 여기서는 막고 묻는다."""

    verdict = _assess([_req("req-1", "Java 개발 경험")],
                      {"skills": [], "evidenceMap": [], "skillEvidence": {}})
    assert verdict.sufficient is False
    assert any(m.code == "no_evidence" and m.blocking for m in verdict.missing)


def test_undecidable_required_does_not_block_when_there_is_evidence():
    """**정책이 뒤집혔다** (2026-08-03). 전에는 "묻는 게 유일한 해결책"이라 막았다.

    뒤집은 이유 둘:
      · 유일하지 않다 — `gap_matcher` 가 이미 LLM 으로 두 번 읽는다(배치 의미 판정 +
        실패분 개별 재시도). 여기까지 남은 uncertain 은 물어보기 전이라 모르는 게 아니라
        읽어도 모르는 것이다.
      · 되물어도 못 묻는다 — 이 결핍의 질문에는 선택지가 없어 v2 `NEEDS_INPUT`
        (선택지 2~4개 필수)으로 나갈 수 없다. 서비스가 스스로 "정보 없음"으로 답하며
        왕복 상한까지 반복하고 **분석이 통째로 실패했다**(실측: fit_analysis 4회 반복 →
        `AI_PROVIDER_UNAVAILABLE`).

    남은 uncertain 은 점수 분모에서 빠지므로 미충족으로 둔갑하지 않는다(§2-1).
    """

    verdict = _assess(
        [_req("req-1", "경력 3년 이상"), _req("req-2", "원활한 커뮤니케이션 능력")],
        _RICH_PROFILE,
    )
    assert verdict.sufficient is True, "한 줄 못 읽었다고 지도를 통째로 안 만들지 않는다"
    assert verdict.undecidableRequiredCount == 2
    # 그래도 **무엇을 못 읽었는지는 남는다** — 삼키지 않는다(§2-6).
    assert [m.code for m in verdict.missing] == ["undecidable_requirement"] * 2
    assert all(not m.blocking for m in verdict.missing)


def test_undecidable_required_still_blocks_without_evidence():
    """근거가 아예 없으면 여전히 막는다 — 판정할 재료 자체가 없는 것이다."""

    bare = {**_RICH_PROFILE, "evidenceMap": []}
    verdict = _assess(
        [_req("req-1", "경력 3년 이상"), _req("req-2", "원활한 커뮤니케이션 능력")],
        bare,
    )
    assert verdict.sufficient is False
    assert any(m.code == "no_evidence" and m.blocking for m in verdict.missing)
    texts = " ".join(q["text"] for q in build_questions(verdict))
    assert "경력 3년 이상" in texts, "막을 때는 판정 못 한 요구사항을 그대로 묻는다"


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
