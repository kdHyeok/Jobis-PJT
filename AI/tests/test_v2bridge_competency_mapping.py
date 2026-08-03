"""요건 판정 → CompetencyProposal 매핑 (`v2bridge/mapping.build_competency_proposal`).

**결정론만 쓰는 단계다.** 분류를 LLM 이 하는 것은 다음 단계이고, 여기서 재는 것은
"백엔드가 로드맵을 만들 수 있는 최소한을 채웠는가" 다.

핵심 불변식 둘:
  · canonicalKey 는 `skill_taxonomy` 를 앵커로 쓴다 — 같은 기술이 공고마다 다른 키를 받으면
    `user_competencies` 가 쪼개져 지도에 중복 노드가 생긴다(조용한 고장).
  · 검증할 수 없는 요건은 `roadmapEligible=false` — 사용자가 영원히 완료 못 하는 칸을
    지도에 만들지 않는다. 모르는 것을 아는 척하지 않는다(§2-1).
"""

from __future__ import annotations

from jobis_ai.v2bridge.mapping import (
    build_competency_proposal,
    experience_requirement,
    track_from_posting,
)

# `graph.nodes.parse_job_posting` 이 내는 모양 그대로다 — 연차는 `minYears`/`maxYears` 로
# 이미 정형화돼 오고, `experience` 칸은 **없다**(실측: 크롤링 행에만 있다).
_POSTING = {
    "companyName": "가나테크",
    "jobTitle": "백엔드 개발자",
    "roleCategory": "backend",
    "seniority": "mid",
    "yearsEvidence": "경력 3년 이상",
    "minYears": 3,
    "maxYears": "",
}


def req(rid: str, text: str, *, type_: str = "required", **over) -> dict:
    return {"requirementId": rid, "text": text, "type": type_, **over}


# --- 트랙 -------------------------------------------------------------------------
def test_track_is_normalized_and_unknown_stays_none():
    assert track_from_posting({"roleCategory": "backend"}) == "BACKEND"
    assert track_from_posting({"roleCategory": "Data-Engineer"}) == "DATA"
    # 짐작해서 BACKEND 로 채우지 않는다 — 백엔드가 자기 기본값을 쓰는 것과 우리가
    # 주장하는 것은 다르다.
    assert track_from_posting({"roleCategory": "기획"}) is None
    assert track_from_posting({}) is None


# --- 경력 관문 재료 ---------------------------------------------------------------
def test_experience_requirement_reads_the_parsed_years():
    """파서가 뽑아 둔 `minYears` 를 쓴다.

    실 모델 검증(2026-08-03)에서 이게 깨져 있었다 — 크롤링 행용 `posting_floor_years` 를
    불렀는데 정규화된 공고에는 `experience` 칸이 없어 항상 None 이었고, **경력 관문 노드가
    통째로 안 생겼다.** 조용한 고장이라 단위 테스트만으로는 안 보였다(§3-7).
    """

    got = experience_requirement(_POSTING)
    assert got is not None
    assert got.type == "REQUIRED"
    assert got.minimum_months == 36
    assert got.maximum_months is None
    assert got.source_text == "경력 3년 이상"


def test_experience_upper_bound_is_carried_when_present():
    got = experience_requirement({**_POSTING, "maxYears": 5,
                                  "yearsEvidence": "경력 3~5년"})
    assert got is not None
    assert (got.minimum_months, got.maximum_months) == (36, 60)


def test_experience_requirement_needs_both_evidence_and_years():
    """둘 중 하나라도 없으면 만들지 않는다 — 모르는 것을 없다고 단정하지 않는다."""

    assert experience_requirement({"minYears": 3}) is None              # 근거 문구 없음
    assert experience_requirement({"yearsEvidence": "경력 3년"}) is None  # 연차 미추출
    assert experience_requirement({**_POSTING, "minYears": ""}) is None


# --- 역량 -------------------------------------------------------------------------
def test_known_skill_uses_the_taxonomy_key_as_anchor():
    """사전이 아는 기술은 반드시 사전 키를 쓴다 — 키가 흔들리면 지도가 쪼개진다."""

    proposal = build_competency_proposal(
        _POSTING, [req("r1", "Java 기반 서버 개발 경험")], [], "BACKEND")
    assert proposal is not None
    java = proposal.competencies[0]
    assert java.canonical_key.startswith("skill.")
    assert java.roadmap_eligible is True
    assert java.verification_method, "로드맵에 올리려면 검증 방법을 대야 한다"
    assert java.stage == "LANGUAGE"
    assert java.domain == "BACKEND", "언어는 주 직무 레인에 둔다(문서 규칙 8)"


def test_database_skill_goes_to_its_own_lane_not_the_track_lane():
    proposal = build_competency_proposal(
        _POSTING, [req("r1", "Java"), req("r2", "MySQL 스키마 설계")], [], "BACKEND")
    assert proposal is not None
    lanes = {c.title.lower(): (c.stage, c.domain) for c in proposal.competencies}
    mysql = next(v for k, v in lanes.items() if "mysql" in k)
    assert mysql == ("DATA", "DATA")


def test_korean_prose_requirement_is_dropped_not_faked(caplog):
    """한글 산문 요건("원활한 커뮤니케이션")은 **뺀다** — 대신 뺀 사실을 남긴다.

    canonicalKey 는 ascii 라 안정된 키를 지을 수 없고(`slug` 가 빈 문자열을 낸다 —
    "위조하지 않는다"), `roadmapEligible=false` 로 남겨도 카탈로그·준비도 분모 어디에도
    쓰이지 않는다. 그래서 남기는 것이 이득이 없다. 다만 조용히 빼면 §2-6 위반이다.
    """

    with caplog.at_level("INFO"):
        proposal = build_competency_proposal(
            _POSTING,
            [req("r1", "Java"), req("r2", "원활한 커뮤니케이션과 책임감")],
            [], "BACKEND")
    assert proposal is not None
    assert len(proposal.competencies) == 1
    assert all(c.roadmap_eligible for c in proposal.competencies)
    assert "옮기지 못한 요건 1건" in caplog.text


def test_english_prose_requirement_survives_as_ineligible():
    """ascii 로 키를 지을 수 있으면 남긴다 — 다만 검증 방법을 모르니 지도에는 안 올린다."""

    proposal = build_competency_proposal(
        _POSTING,
        [req("r1", "Java"), req("r2", "Agile Scrum ceremonies ownership")],
        [], "BACKEND")
    assert proposal is not None
    soft = [c for c in proposal.competencies if not c.roadmap_eligible]
    assert soft, "키를 지을 수 있는 요건은 결과에 남는다"
    assert all(c.verification_method is None for c in soft)
    # 과제가 그것을 증명 대상으로 삼지 않는다
    soft_refs = {c.ref for c in soft}
    assert not (soft_refs & set(proposal.target_project.required_competency_refs))


def test_seniority_requirement_becomes_career_experience():
    """합성 연차 요건은 기술이 아니다 — 백엔드가 경력 관문으로 흡수한다."""

    proposal = build_competency_proposal(
        _POSTING,
        [req("r1", "Java"), req("seniority-1", "경력 3년 이상", kind="seniority")],
        [], "BACKEND")
    assert proposal is not None
    career = [c for c in proposal.competencies if c.domain == "CAREER"]
    assert len(career) == 1
    assert (career[0].stage, career[0].kind) == ("EXPERIENCE", "EXPERIENCE")


def test_same_skill_in_two_requirements_is_one_competency():
    proposal = build_competency_proposal(
        _POSTING,
        [req("r1", "Java 서버 개발"), req("r2", "Java 기반 배치 처리", type_="preferred")],
        [], "BACKEND")
    assert proposal is not None
    assert len(proposal.competencies) == 1, "같은 canonicalKey 를 두 번 만들지 않는다"
    assert {r.relation for r in proposal.requirements} == {"REQUIRED", "PREFERRED"}


def test_preferred_only_skill_is_not_what_the_project_must_prove():
    proposal = build_competency_proposal(
        _POSTING,
        [req("r1", "Java"), req("r2", "Kafka 운영 경험", type_="preferred")],
        [], "BACKEND")
    assert proposal is not None
    titles = {c.ref: c.title.lower() for c in proposal.competencies}
    proven = {titles[r] for r in proposal.target_project.required_competency_refs}
    assert not any("kafka" in t for t in proven), "우대는 본선 증명 대상이 아니다"


def test_no_provable_competency_yields_none_instead_of_a_hollow_proposal():
    """증명할 대상이 없으면 만들지 않는다 — 빈 과제를 지어내느니 실패를 남긴다."""

    assert build_competency_proposal(
        _POSTING, [req("r1", "성실하고 책임감 있는 자세")], [], "BACKEND") is None
    assert build_competency_proposal(_POSTING, [], [], "BACKEND") is None


def test_source_text_is_the_posting_sentence_not_our_paraphrase():
    """근거 문구는 원문 그대로다 — 노드 근거로 화면에 나간다."""

    sentence = "Spring Boot 기반 REST API 설계 및 운영 경험"
    proposal = build_competency_proposal(_POSTING, [req("r1", sentence)], [], "BACKEND")
    assert proposal is not None
    assert proposal.requirements[0].source_text == sentence
