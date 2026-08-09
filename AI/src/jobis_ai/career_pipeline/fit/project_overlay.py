from __future__ import annotations

import re

from jobis_ai.career_pipeline.contracts.fit import (
    ClaimState,
    EvidenceState,
    FitAnalysisRequest,
    FitAnalysisResult,
    FitAnalysisStatus,
    FitAssessment,
    FitAudit,
    FormalFactKind,
    VerificationState,
)
from jobis_ai.career_pipeline.contracts.posting import RequirementCategory
from jobis_ai.career_pipeline.contracts.project_planning import CompanyProjectBlueprint

from .draft import (
    CompetencyMatchCandidate,
    FormalFactMatchCandidate,
    RequirementMatchDraft,
    SemanticRelation,
)
from .service import (
    POLICY_VERSION,
    _calculate_metrics,
    _compile_assessment,
    _formal_eligibility,
    next_formal_evidence_question,
    _propose_verdict,
    _requirements_for_request,
    _stable_id,
)


PROJECT_OVERLAY_VERSION = "project-evidence-overlay-3.3.0"
_TOKEN = re.compile(r"[A-Za-z0-9가-힣+#.]{2,}")
_GENERIC_ROLE_TOKENS = {
    "개발", "개발자", "경력", "관련", "직무", "업무", "engineer", "developer",
    "software", "experience", "required",
}
_MAJOR_TERM_GROUPS = (
    {"it", "컴퓨터", "컴퓨터공학", "소프트웨어", "전산", "정보기술", "인공지능", "ai", "데이터"},
    {"기계", "기계공학", "로봇", "자동화", "메카트로닉스"},
    {"전자", "전기", "전자공학", "전기공학", "임베디드"},
)


def compile_project_fit(
    request: FitAnalysisRequest,
    blueprint: CompanyProjectBlueprint,
) -> FitAnalysisResult:
    """Overlay one user's evidence after the project curriculum is fixed.

    Project tasks already provide the approved requirement-to-capability links.
    Re-asking an LLM to rediscover those links is slower and can contradict the
    roadmap. Formal facts are linked only with conservative, observable type and
    text evidence; uncertain gates remain UNKNOWN rather than being guessed.
    """
    if blueprint.common_analysis_id != request.common_analysis_id:
        raise ValueError("project blueprint belongs to a different commonAnalysisId")
    if blueprint.selected_position_id != request.selected_position_id:
        raise ValueError("project blueprint belongs to a different selectedPositionId")

    contexts = _requirements_for_request(request)
    keys_by_requirement: dict[str, set[str]] = {}
    for task in blueprint.tasks:
        for requirement_id in task.requirement_ids:
            keys_by_requirement.setdefault(requirement_id, set()).update(
                task.capability_keys
            )

    competency_by_key = {
        item.competency_id: item for item in request.user_evidence.competencies
    }
    position = next(
        item for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    assessments = []
    for context in contexts:
        mapped_keys = sorted(keys_by_requirement.get(context.requirement_id, set()))
        present_records = [
            competency_by_key[key]
            for key in mapped_keys
            if key in competency_by_key
        ]
        all_supported = bool(mapped_keys) and all(
            key in competency_by_key and _has_user_state(competency_by_key[key])
            for key in mapped_keys
        )
        competency_candidates = [
            CompetencyMatchCandidate(
                competency_id=item.competency_id,
                relation=(
                    SemanticRelation.DIRECT
                    if all_supported
                    else SemanticRelation.PARTIAL
                ),
                confidence=1.0,
            )
            for item in present_records
        ]
        formal_fact_candidates = [
            FormalFactMatchCandidate(
                fact_id=fact.fact_id,
                relation=SemanticRelation.DIRECT,
                confidence=1.0,
            )
            for fact in request.user_evidence.formal_facts
            if _formal_fact_matches(context, fact, position)
        ]
        match = RequirementMatchDraft(
            requirement_id=context.requirement_id,
            competency_candidates=competency_candidates,
            formal_fact_candidates=formal_fact_candidates,
            confidence=1.0,
            reason=(
                "The company-target project supplies the approved capability link."
                if mapped_keys
                else "No deterministic project or formal-fact link was available."
            ),
        )
        assessments.append(_compile_assessment(context, match, request))

    if not request.skip_remaining_evidence_questions:
        question = next_formal_evidence_question(request, contexts, assessments)
        if question is not None:
            return FitAnalysisResult(
                status=FitAnalysisStatus.AWAITING_USER_EVIDENCE,
                active_ambiguity=question,
            )

    metrics = _calculate_metrics(contexts, assessments)
    formal_eligibility = _formal_eligibility(contexts, assessments)
    verdict = _propose_verdict(assessments, metrics, formal_eligibility)
    used_refs = sorted({
        evidence_id
        for assessment in assessments
        for evidence_id in assessment.user_evidence_refs
    })
    all_refs = [item.evidence_id for item in request.user_evidence.evidence_items]
    assessment_id = _stable_id(
        "fit",
        request.common_analysis_id,
        request.selected_position_id,
        request.user_evidence.evidence_set_id,
        str(request.user_evidence.revision),
        blueprint.blueprint_id,
        *[f"{item.requirement_id}:{item.status.value}" for item in assessments],
    )
    fit = FitAssessment(
        fit_assessment_id=assessment_id,
        common_analysis_id=request.common_analysis_id,
        selected_position_id=request.selected_position_id,
        selected_experience_track=request.selected_experience_track,
        user_evidence_set_id=request.user_evidence.evidence_set_id,
        user_evidence_revision=request.user_evidence.revision,
        policy_version=POLICY_VERSION,
        formal_eligibility=formal_eligibility,
        requirement_assessments=assessments,
        metrics=metrics,
        strengths=[
            context.text
            for context, assessment in zip(contexts, assessments, strict=True)
            if assessment.status.value in {"VERIFIED_MET", "EVIDENCED"}
        ],
        gaps=[
            context.text
            for context, assessment in zip(contexts, assessments, strict=True)
            if assessment.status.value in {"NOT_MET", "PARTIAL"}
        ],
        uncertainties=[
            context.text
            for context, assessment in zip(contexts, assessments, strict=True)
            if assessment.status.value == "UNKNOWN"
        ],
        verdict_proposal=verdict,
        audit=FitAudit(
            matcher_version=PROJECT_OVERLAY_VERSION,
            policy_version=POLICY_VERSION,
            provider="deterministic",
            model="project-capability-evidence-overlay",
            generation_attempts=1,
            generation_duration_ms=0,
            evaluated_requirement_ids=[item.requirement_id for item in assessments],
            used_user_evidence_refs=used_refs,
            ignored_user_evidence_refs=[item for item in all_refs if item not in used_refs],
        ),
    )
    return FitAnalysisResult(status=FitAnalysisStatus.COMPLETED, assessment=fit)


def _has_user_state(competency) -> bool:
    return (
        competency.verification_state in {
            VerificationState.VERIFIED,
            VerificationState.PARTIALLY_VERIFIED,
        }
        or competency.evidence_state is EvidenceState.EVIDENCED
        or competency.claim_state is ClaimState.CLAIMED
    )


def _formal_fact_matches(context, fact, position) -> bool:
    if context.synthetic_experience:
        return (
            fact.kind is FormalFactKind.ROLE_EXPERIENCE
            and _role_fact_matches(fact.label, position)
        )
    if context.category is RequirementCategory.EXPERIENCE:
        return (
            fact.kind is FormalFactKind.ROLE_EXPERIENCE
            and _role_fact_matches(fact.label, position)
        )
    if context.category is RequirementCategory.CREDENTIAL:
        if fact.kind is FormalFactKind.EDUCATION:
            return _education_fact_matches(context.text, fact.label)
        # Backward compatibility for postings analyzed before CERTIFICATION
        # became a distinct requirement category.
        return fact.kind is FormalFactKind.CERTIFICATE and _meaningful_overlap(
            context.text, fact.label
        )
    if context.category is RequirementCategory.CERTIFICATION:
        return fact.kind is FormalFactKind.CERTIFICATE and _meaningful_overlap(
            context.text, fact.label
        )
    if context.category is RequirementCategory.PORTFOLIO:
        return fact.kind is FormalFactKind.PORTFOLIO
    return False


def _role_fact_matches(label: str, position) -> bool:
    folded = label.casefold()
    if "관련 직무" in folded or "relevant role" in folded:
        return True
    role_text = " ".join((
        position.source_title,
        position.role.family,
        position.role.specialization,
        position.role.canonical_role_id or "",
    ))
    return _meaningful_overlap(role_text, label)


def _meaningful_overlap(left: str, right: str) -> bool:
    left_tokens = {
        item.casefold() for item in _TOKEN.findall(left)
        if item.casefold() not in _GENERIC_ROLE_TOKENS
    }
    right_tokens = {
        item.casefold() for item in _TOKEN.findall(right)
        if item.casefold() not in _GENERIC_ROLE_TOKENS
    }
    return bool(left_tokens & right_tokens)


def _education_fact_matches(requirement_text: str, fact_label: str) -> bool:
    """Match observable degree and major facts without treating every education as equal.

    Posting interpretation currently groups degrees, majors, and certificates under
    CREDENTIAL.  The evidence assembler therefore preserves the education description
    in the fact label, and this matcher resolves only explicit degree levels or known
    major families.  If neither can be established, the requirement remains UNKNOWN.
    """
    requirement = requirement_text.casefold().replace(" ", "")
    fact = fact_label.casefold().replace(" ", "")
    required_level = _degree_level(requirement, requirement=True)
    if required_level is not None:
        fact_level = _degree_level(fact, requirement=False)
        return fact_level is not None and fact_level >= required_level

    if "전공" in requirement or "계열" in requirement or "major" in requirement:
        if _meaningful_overlap(requirement_text, fact_label):
            return True
        return any(
            any(term in requirement for term in group)
            and any(term in fact for term in group)
            for group in _MAJOR_TERM_GROUPS
        )
    return _meaningful_overlap(requirement_text, fact_label)


def _degree_level(value: str, *, requirement: bool) -> int | None:
    if "박사" in value or "doctor" in value or "phd" in value:
        return 4
    if "석사" in value or "master" in value:
        return 3
    if "전문학사" in value or "전문대" in value or "초대졸" in value:
        return 1
    if any(term in value for term in ("대졸", "학사", "4년제", "대학교", "bachelor")):
        return 2
    if any(term in value for term in ("고졸", "고등학교", "highschool")):
        return 0
    if requirement and "학력" in value:
        return 0
    return None
