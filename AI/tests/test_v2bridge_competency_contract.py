"""역량 제안 계약 — 지도의 재료가 되는 값의 형태와 무결성 (`v2bridge/models.py`).

정본은 백엔드 코드다(`AiContracts.java` · `RoadmapService` · V10/V12 마이그레이션 CHECK).
여기서 잡는 것은 **백엔드에 닿기 전에 걸러야 하는 위반**이다 — 나가고 나면 502(계약 검증
실패)나, 더 나쁘게는 조용히 이상한 지도가 된다.

초기 계약 모델과 같은 제약을 쓰지만 삭제된 어댑터와 동기화할 의무는 없다(팀원의 답변
테스트용 서버다). 어긋나면 백엔드 코드를 따른다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.v2bridge.models import (
    AnalysisResponse,
    AnalyzedCompetency,
    AnalyzedRequirement,
    CompetencyProposal,
    ExperienceRequirement,
    TargetProjectBrief,
)


def competency(ref: str, **over) -> AnalyzedCompetency:
    return AnalyzedCompetency(**{
        "ref": ref,
        "canonicalKey": f"lang.{ref}",
        "title": ref,
        "domain": "BACKEND",
        "kind": "TECHNOLOGY",
        "stage": "LANGUAGE",
        "scopeDefinition": "서비스 코드를 작성할 수 있다.",
        "requiredLevel": 3,
        "roadmapEligible": True,
        "verificationMethod": "저장소와 테스트로 확인한다.",
        **over,
    })


def proposal(competencies=None, **over) -> CompetencyProposal:
    competencies = competencies or [competency("java")]
    first = competencies[0].ref
    return CompetencyProposal(**{
        "competencies": competencies,
        "requirements": [AnalyzedRequirement(
            competencyRef=first, relation="REQUIRED",
            sourceText="Java 실무 경험 2년 이상", confidence="0.9")],
        "targetProject": TargetProjectBrief(
            title="검증 과제", objective="필수 역량을 통합해 증명한다.",
            domainContext="사내 서비스", requiredCompetencyRefs=[first],
            deliverables=["저장소"], acceptanceCriteria=["테스트 통과"]),
        **over,
    })


# --- 역량 하나 -------------------------------------------------------------------
def test_roadmap_eligible_competency_must_say_how_it_is_verified():
    """검증 방법 없는 역량은 사용자가 영원히 완료 처리할 수 없는 노드가 된다."""

    with pytest.raises(ValidationError, match="verification method"):
        competency("java", verificationMethod=None)
    # 정성 조건은 지도에서 빼는 것이 정답 — 그때는 검증 방법이 없어도 된다
    assert competency("teamwork", roadmapEligible=False, verificationMethod=None)


def test_domain_and_stage_are_closed_sets():
    """V10 마이그레이션에 DB CHECK 가 있다 — 여기서 안 막으면 **DB 가** 거부한다."""

    with pytest.raises(ValidationError):
        competency("java", domain="PAYMENT")
    with pytest.raises(ValidationError):
        competency("java", stage="DEPLOY")


def test_canonical_key_pattern_is_enforced():
    """`user_competencies` 유일키 — 대문자·공백이 섞이면 같은 기술이 갈린다."""

    with pytest.raises(ValidationError):
        competency("java", canonicalKey="Lang.Java")


# --- 제안 전체의 무결성 -----------------------------------------------------------
def test_duplicate_refs_and_keys_are_rejected():
    with pytest.raises(ValidationError, match="refs must be unique"):
        proposal([competency("java"), competency("java")])
    with pytest.raises(ValidationError, match="keys must be unique"):
        proposal([competency("java"), competency("java2", canonicalKey="lang.java")])


def test_requirement_must_point_at_an_analyzed_competency():
    with pytest.raises(ValidationError, match="requirement references"):
        proposal(requirements=[AnalyzedRequirement(
            competencyRef="nope", relation="REQUIRED",
            sourceText="없는 역량", confidence="0.5")])


def test_same_competency_and_relation_is_not_repeated():
    dup = [AnalyzedRequirement(competencyRef="java", relation="REQUIRED",
                               sourceText="원문 A", confidence="0.9"),
           AnalyzedRequirement(competencyRef="java", relation="REQUIRED",
                               sourceText="원문 B", confidence="0.8")]
    with pytest.raises(ValidationError, match="deduplicated"):
        proposal(requirements=dup)
    # 강도가 다르면 같은 역량이라도 별개다
    ok = [dup[0], AnalyzedRequirement(competencyRef="java", relation="PREFERRED",
                                      sourceText="원문 B", confidence="0.8")]
    assert len(proposal(requirements=ok).requirements) == 2


def test_target_project_cannot_be_proven_by_a_qualitative_competency():
    """로드맵에서 빠진 역량을 과제가 참조하면 완료 판정이 영원히 성립하지 않는다."""

    soft = competency("teamwork", roadmapEligible=False, verificationMethod=None)
    with pytest.raises(ValidationError, match="qualitative"):
        proposal([soft], targetProject=TargetProjectBrief(
            title="과제", objective="증명", domainContext="맥락",
            requiredCompetencyRefs=["teamwork"],
            deliverables=["저장소"], acceptanceCriteria=["통과"]))


def test_target_project_is_not_optional():
    """PROJECT 노드가 없으면 지도에서 회사 가지가 완성되지 않는다."""

    with pytest.raises(ValidationError):
        CompetencyProposal(competencies=[competency("java")], requirements=[
            AnalyzedRequirement(competencyRef="java", relation="REQUIRED",
                                sourceText="원문", confidence="0.9")])


# --- 경력 관문 재료 ---------------------------------------------------------------
def test_experience_requirement_ranges():
    assert ExperienceRequirement(type="REQUIRED", minimumMonths=24,
                                 maximumMonths=48, sourceText="2~4년")
    with pytest.raises(ValidationError, match="must start at zero"):
        ExperienceRequirement(type="NONE", minimumMonths=12, sourceText="신입")
    with pytest.raises(ValidationError, match="below minimum"):
        ExperienceRequirement(type="REQUIRED", minimumMonths=48,
                              maximumMonths=24, sourceText="뒤집힘")


# --- 응답 골격 --------------------------------------------------------------------
def test_needs_input_cannot_smuggle_a_competency_proposal():
    """되묻는 중에는 결과가 없다 — 부분 결과를 보내면 백엔드가 반쪽 상태를 저장한다."""

    with pytest.raises(ValidationError, match="cannot contain a final result"):
        AnalysisResponse(
            status="NEEDS_INPUT",
            question={"key": "target_track", "text": "어느 직무로 보시나요?",
                      "reason": "직무에 따라 요건이 갈립니다",
                      "options": [{"value": "backend", "label": "백엔드", "description": "서버"},
                                  {"value": "frontend", "label": "프론트", "description": "UI"}]},
            competencyProposal=proposal())


def test_completed_requires_a_competency_proposal():
    """**성공을 가장한 실패를 막는다.**

    백엔드 워커는 `competencyProposal` 이 없으면 job 을 FAILED 로 끝낸다. 그걸 알면서
    COMPLETED 를 내보내면 "분석은 됐는데 지도는 안 생긴다"가 되고, 원인이 응답 어디에도
    안 남는다. 없으면 서비스가 먼저 EngineFailed 로 알린다.

    (이 테스트는 1단계에서 정반대 내용이었다 — 생산자가 붙는 순간 뒤집으려고 심어 둔 자리다.)
    """

    payload = {
        "status": "COMPLETED",
        "job": {"primaryTrack": "BACKEND", "parsedData": {}},
        "evaluation": {"verdict": "APPLY_NOW", "summary": "적합", "reasons": ["근거"]},
        "changeProposal": {"baseGraphVersion": 1, "nodes": [], "edges": [],
                           "requirements": []},
    }
    with pytest.raises(ValidationError, match="complete result"):
        AnalysisResponse(**payload)
    assert AnalysisResponse(**payload, competencyProposal=proposal())
