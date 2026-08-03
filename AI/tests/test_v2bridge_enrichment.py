"""공고 읽기(LLM 분류)가 지도 재료를 채운다 — 그리고 **어디까지만** 채우는가.

`enrich.classify_posting` 은 읽기 계층이다(§1). 여기서 못 박는 것은 자율의 **경계**다:
분류는 LLM 이 정하되, 이름(canonicalKey)·근거(sourceText)·증명 대상은 결정론이 정한다.
경계가 무너지면 조용히 고장난다 — 키가 흔들리면 지도에 중복 노드가 생기고, 증명 대상이
정성 역량으로 새면 계약 검증(502)에 걸린다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.v2bridge import enrich, mapping
from jobis_ai.v2bridge.enrich import (
    CompetencyClassification,
    PostingEnrichment,
    TargetProjectDraft,
)

_POSTING = {
    "companyName": "가나테크", "jobTitle": "백엔드 개발자",
    "roleCategory": "backend", "yearsEvidence": "경력 3년 이상",
    "experience": "경력 3년 이상", "industry": "핀테크",
}
_REQS = [
    {"requirementId": "r1", "type": "required", "text": "Java 기반 서버 개발"},
    {"requirementId": "r2", "type": "required", "text": "Agile Scrum ceremonies ownership"},
]


def _project(**over) -> TargetProjectDraft:
    return TargetProjectDraft(**{
        "title": "핀테크 정산 API", "objective": "정산 도메인을 API 로 구현해 보인다.",
        "domainContext": "핀테크 정산", "deliverables": ["저장소", "부하 테스트 결과"],
        "acceptanceCriteria": ["정산 시나리오 통과"], **over})


def _classification(ref: str, **over) -> CompetencyClassification:
    return CompetencyClassification(**{
        "ref": ref, "stage": "FRAMEWORK", "domain": "BACKEND", "kind": "TECHNOLOGY",
        "requiredLevel": 4, "roadmapEligible": True,
        "verificationMethod": "구현한 API 와 테스트로 확인한다.", **over})


# --- 스키마가 곧 금지다 -----------------------------------------------------------
def test_llm_schema_has_no_place_to_name_a_competency():
    """**canonicalKey 필드가 없다.** 프롬프트로 "짓지 마라"가 아니라 칸을 없앤 것이다(§2-2).

    LLM 이 키를 지으면 같은 기술이 공고마다 다른 키를 받아 `user_competencies` 가 쪼개진다.
    """

    fields = set(CompetencyClassification.model_fields)
    assert "canonicalKey" not in fields and "canonical_key" not in fields
    assert "title" not in fields, "이름도 짓지 않는다 — ref 로만 지목한다"
    assert "sourceText" not in fields, "근거 문구는 공고 원문이다"
    # 과제도 증명 대상을 못 고른다 — 그건 '필수이면서 검증 가능'이라는 계산이다.
    assert "requiredCompetencyRefs" not in set(TargetProjectDraft.model_fields)


# --- 분류가 결정론 자리채움을 이긴다 -----------------------------------------------
def test_classification_overrides_the_placeholder_level_and_stage():
    drafts, _ = mapping.draft_competencies(_POSTING, _REQS, [], "BACKEND")
    java = next(d for d in drafts if "java" in d["canonicalKey"])
    assert java["stage"] == "LANGUAGE"      # 결정론 값

    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(
            primaryTrack="BACKEND", targetProject=_project(),
            competencies=[_classification(java["ref"], stage="SCALE", requiredLevel=5)]))
    assert enriched is not None
    got = next(c for c in enriched.competencies if c.ref == java["ref"])
    assert (got.stage, got.required_level) == ("SCALE", 5)


def test_classification_cannot_change_the_key_or_the_evidence():
    """분류가 바뀌어도 정체성과 근거는 그대로다."""

    drafts, _ = mapping.draft_competencies(_POSTING, _REQS, [], "BACKEND")
    java = next(d for d in drafts if "java" in d["canonicalKey"])
    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(primaryTrack="BACKEND", targetProject=_project(),
                          competencies=[_classification(java["ref"], domain="AI")]))
    assert enriched is not None
    got = next(c for c in enriched.competencies if c.ref == java["ref"])
    assert got.canonical_key == java["canonicalKey"]
    assert got.title == java["title"]
    assert got.scope_definition == "Java 기반 서버 개발"


def test_unknown_requirement_can_be_promoted_onto_the_roadmap():
    """사전 밖 요건은 결정론에선 지도 밖이다 — 읽어 보고 검증 가능하면 올린다.

    이게 이 층의 값어치다: 결정론은 "모르니 뺀다"까지밖에 못 한다.
    """

    drafts, _ = mapping.draft_competencies(_POSTING, _REQS, [], "BACKEND")
    scrum = next(d for d in drafts if not d["known"])
    assert scrum["roadmapEligible"] is False

    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(
            primaryTrack="BACKEND", targetProject=_project(),
            competencies=[_classification(
                scrum["ref"], kind="PRACTICE", stage="QUALITY",
                verificationMethod="스프린트 회고 기록과 이슈 트래커로 확인한다.")]))
    assert enriched is not None
    got = next(c for c in enriched.competencies if c.ref == scrum["ref"])
    assert got.roadmap_eligible is True
    assert "회고" in got.verification_method


def test_eligible_without_a_method_is_filled_not_rejected():
    """모델이 검증 방법을 비운 채 eligible 만 켜도 계약을 깨지 않는다."""

    drafts, _ = mapping.draft_competencies(_POSTING, _REQS, [], "BACKEND")
    scrum = next(d for d in drafts if not d["known"])
    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(
            primaryTrack="BACKEND", targetProject=_project(),
            competencies=[_classification(scrum["ref"], verificationMethod="")]))
    assert enriched is not None
    got = next(c for c in enriched.competencies if c.ref == scrum["ref"])
    assert got.roadmap_eligible is True and got.verification_method


def test_unknown_ref_from_the_model_is_ignored():
    """목록에 없는 ref 를 골라도 새 역량이 생기지 않는다 — 분류는 지목일 뿐이다."""

    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(primaryTrack="BACKEND", targetProject=_project(),
                          competencies=[_classification("made-up-ref")]))
    assert enriched is not None
    assert all(c.ref != "made-up-ref" for c in enriched.competencies)


# --- 과제 ---------------------------------------------------------------------
def test_read_project_replaces_the_formulaic_one_but_not_its_targets():
    plain = mapping.build_competency_proposal(_POSTING, _REQS, [], "BACKEND")
    enriched = mapping.build_competency_proposal(
        _POSTING, _REQS, [], "BACKEND",
        PostingEnrichment(primaryTrack="BACKEND", targetProject=_project(),
                          competencies=[]))
    assert plain is not None and enriched is not None
    assert "필수 요건 검증 과제" in plain.target_project.title      # 정형 폴백
    assert enriched.target_project.title == "핀테크 정산 API"
    assert enriched.target_project.domain_context == "핀테크 정산"
    # 증명 대상은 결정론이 정한다 — 읽은 과제로 바뀌어도 그대로다.
    assert (enriched.target_project.required_competency_refs
            == plain.target_project.required_competency_refs)


# --- 폴백 ---------------------------------------------------------------------
def test_no_drafts_means_no_llm_call():
    assert enrich.classify_posting(_POSTING, []) == (None, [])


def test_without_an_llm_the_deterministic_result_stands():
    """LLM 미설정이면 (None, warnings) — 분석이 죽지 않는다."""

    got, _ = enrich.classify_posting(_POSTING, [{"ref": "req-01", "title": "Java"}])
    assert got is None
    assert mapping.build_competency_proposal(_POSTING, _REQS, [], "BACKEND") is not None


@pytest.mark.parametrize("bad", [0, 6])
def test_required_level_stays_inside_the_scale(bad):
    with pytest.raises(ValidationError):
        _classification("req-01", requiredLevel=bad)
