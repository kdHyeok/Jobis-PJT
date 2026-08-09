from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.fit import (
    AssessmentBasis,
    ClaimState,
    EvidenceState,
    FitAnalysisRequest,
    FitAnalysisResult,
    FitAnalysisStatus,
    FitAssessment,
    FitAudit,
    FitMetrics,
    FormalFact,
    FormalFactKind,
    FormalFactState,
    RequirementAssessment,
    RequirementStatus,
    UserCompetencyEvidence,
    VerificationState,
    VerdictProposal,
)
from jobis_ai.career_pipeline.contracts.posting import (
    Ambiguity,
    AmbiguityType,
    AtomicRequirement,
    ClarificationQuestion,
    ExperienceKind,
    QuestionInputType,
    QuestionOption,
    RequirementCategory,
    RequirementObligation,
)
from jobis_ai.career_pipeline.llm import JsonProviderError, JsonProviderNotConfigured, StructuredGenerator

from .draft import FitMatchDraft, RequirementMatchDraft, SemanticRelation


MATCHER_VERSION = "fit-matcher-3.0.0"
POLICY_VERSION = "fit-policy-0.1"
MAX_PROMPT_CHARS = 48_000


SYSTEM_PROMPT = """You link verified job-posting requirements to user-scoped evidence candidates.

Your output is a semantic link proposal, not a hiring verdict. Follow these rules:
1. Return exactly one requirementMatches item for every supplied requirementId.
2. Use only competencyId and factId values present in the input. Never invent an ID.
3. DIRECT means the competency or formal fact actually demonstrates the requirement's scope.
4. PARTIAL means only part of the requirement's scope is demonstrated.
5. Similar words alone are not proof. Read displayName, scopeDefinition, labels, and evidence text.
6. Do not infer CLAIMED, EVIDENCED, VERIFIED, NOT_MET, eligibility, readiness, or a verdict.
7. An empty candidate list means that the supplied information cannot support a link. It does not mean the user lacks the skill.
8. Do not use evidence belonging to any person other than the evidence bundle in this request.
9. Keep reason concise and describe only semantic relevance. Do not reveal hidden reasoning.
"""


class FitAnalysisFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _RequirementContext:
    requirement_id: str
    text: str
    category: RequirementCategory
    obligation: RequirementObligation
    evidence_ids: list[str]
    minimum_months: int | None = None
    synthetic_experience: bool = False

    @property
    def required(self) -> bool:
        return self.obligation is RequirementObligation.REQUIRED


class FitAnalysisService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def analyze(self, request: FitAnalysisRequest) -> FitAnalysisResult:
        contexts = _requirements_for_request(request)
        _validate_self_reports(request, contexts)
        prompt = _build_prompt(request, contexts)
        try:
            draft, metadata = self._generator.generate(
                FitMatchDraft,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
            )
        except JsonProviderNotConfigured as exc:
            raise FitAnalysisFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderError as exc:
            timed_out = "timed out" in str(exc).casefold() or "timeout" in str(exc).casefold()
            raise FitAnalysisFailure(
                code=ErrorCode.AI_TIMEOUT if timed_out else ErrorCode.AI_PROVIDER_UNAVAILABLE,
                message=str(exc),
                retryable=True,
            ) from exc

        try:
            matches = _validated_matches(draft, request, contexts)
            assessments = [
                _compile_assessment(context, matches[context.requirement_id], request)
                for context in contexts
            ]
        except ValueError as exc:
            raise FitAnalysisFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc

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
                if assessment.status in {RequirementStatus.VERIFIED_MET, RequirementStatus.EVIDENCED}
            ],
            gaps=[
                context.text
                for context, assessment in zip(contexts, assessments, strict=True)
                if assessment.status in {RequirementStatus.NOT_MET, RequirementStatus.PARTIAL}
            ],
            uncertainties=[
                context.text
                for context, assessment in zip(contexts, assessments, strict=True)
                if assessment.status is RequirementStatus.UNKNOWN
            ],
            verdict_proposal=verdict,
            audit=FitAudit(
                matcher_version=MATCHER_VERSION,
                policy_version=POLICY_VERSION,
                provider=metadata.provider,
                model=metadata.model,
                generation_attempts=metadata.attempts,
                generation_duration_ms=metadata.duration_ms,
                evaluated_requirement_ids=[item.requirement_id for item in assessments],
                used_user_evidence_refs=used_refs,
                ignored_user_evidence_refs=[item for item in all_refs if item not in used_refs],
            ),
        )
        return FitAnalysisResult(status=FitAnalysisStatus.COMPLETED, assessment=fit)


def _requirements_for_request(request: FitAnalysisRequest) -> list[_RequirementContext]:
    position = next(
        item
        for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    contexts = [_atomic_context(item) for item in position.requirements]
    contexts.extend(
        _atomic_context(item)
        for item in request.structured_posting.shared_conditions
        if request.selected_position_id in item.applies_to_position_ids
    )

    minimum_months: int | None = None
    experience = position.experience
    if request.selected_experience_track is not None:
        if request.selected_experience_track.value == "EXPERIENCED":
            if experience.kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
                minimum_months = experience.min_months
            elif experience.kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED:
                minimum_months = experience.experienced_min_months
    elif experience.kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
        minimum_months = experience.min_months

    if minimum_months is not None:
        contexts.insert(0, _RequirementContext(
            requirement_id=f"req-experience-{position.position_id}",
            text=f"{position.source_title}: relevant experience of at least {minimum_months} months",
            category=RequirementCategory.EXPERIENCE,
            obligation=RequirementObligation.REQUIRED,
            evidence_ids=experience.evidence_ids,
            minimum_months=minimum_months,
            synthetic_experience=True,
        ))
    return contexts


def _atomic_context(requirement: AtomicRequirement) -> _RequirementContext:
    return _RequirementContext(
        requirement_id=requirement.requirement_id,
        text=requirement.atomic_text,
        category=requirement.category,
        obligation=requirement.obligation,
        evidence_ids=requirement.evidence_ids,
    )


def _validate_self_reports(
    request: FitAnalysisRequest,
    contexts: list[_RequirementContext],
) -> None:
    known = {context.requirement_id for context in contexts}
    stale = sorted({
        report.requirement_id
        for report in request.user_evidence.requirement_self_reports
        if report.requirement_id not in known
    })
    if stale:
        raise FitAnalysisFailure(
            code=ErrorCode.ANALYSIS_STALE_RESULT,
            message=f"self reports refer to stale or unrelated requirements: {stale}",
            retryable=False,
        )


def _build_prompt(
    request: FitAnalysisRequest,
    contexts: list[_RequirementContext],
) -> str:
    evidence_by_id = {
        item.evidence_id: item
        for item in request.user_evidence.evidence_items
    }
    payload = {
        "selectedPositionId": request.selected_position_id,
        "requirements": [
            {
                "requirementId": item.requirement_id,
                "text": item.text,
                "category": item.category.value,
                "required": item.required,
                "minimumMonths": item.minimum_months,
            }
            for item in contexts
        ],
        "competencies": [
            {
                "competencyId": item.competency_id,
                "displayName": item.display_name,
                "scopeDefinition": item.scope_definition,
                "supportingEvidence": [
                    {
                        "evidenceId": evidence_id,
                        "text": evidence_by_id[evidence_id].text,
                    }
                    for evidence_id in item.evidence_refs
                ],
            }
            for item in request.user_evidence.competencies
        ],
        "formalFacts": [
            {
                "factId": item.fact_id,
                "kind": item.kind.value,
                "label": item.label,
                "durationMonths": item.duration_months,
                "supportingEvidence": [
                    {
                        "evidenceId": evidence_id,
                        "text": evidence_by_id[evidence_id].text,
                    }
                    for evidence_id in item.evidence_refs
                ],
            }
            for item in request.user_evidence.formal_facts
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_PROMPT_CHARS:
        raise FitAnalysisFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message=(
                f"fit analysis input is {len(encoded)} characters; "
                f"the Spring evidence assembler must reduce it below {MAX_PROMPT_CHARS}"
            ),
            retryable=False,
        )
    return encoded


def _validated_matches(
    draft: FitMatchDraft,
    request: FitAnalysisRequest,
    contexts: list[_RequirementContext],
) -> dict[str, RequirementMatchDraft]:
    expected = {item.requirement_id for item in contexts}
    actual = {item.requirement_id for item in draft.requirement_matches}
    if actual != expected:
        raise ValueError(
            "fit matcher must return exactly the requested requirements; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    competency_ids = {item.competency_id for item in request.user_evidence.competencies}
    fact_ids = {item.fact_id for item in request.user_evidence.formal_facts}
    for match in draft.requirement_matches:
        unknown_competencies = {
            item.competency_id for item in match.competency_candidates
        } - competency_ids
        unknown_facts = {item.fact_id for item in match.formal_fact_candidates} - fact_ids
        if unknown_competencies or unknown_facts:
            raise ValueError(
                f"requirement {match.requirement_id} references unknown user evidence candidates: "
                f"competencies={sorted(unknown_competencies)}, facts={sorted(unknown_facts)}"
            )
    return {item.requirement_id: item for item in draft.requirement_matches}


def _compile_assessment(
    context: _RequirementContext,
    match: RequirementMatchDraft,
    request: FitAnalysisRequest,
) -> RequirementAssessment:
    competencies = {item.competency_id: item for item in request.user_evidence.competencies}
    facts = {item.fact_id: item for item in request.user_evidence.formal_facts}
    self_report = next(
        (
            item for item in request.user_evidence.requirement_self_reports
            if item.requirement_id == context.requirement_id
        ),
        None,
    )

    if context.synthetic_experience:
        relevant_facts = [
            facts[item.fact_id]
            for item in match.formal_fact_candidates
            if item.fact_id in facts and facts[item.fact_id].kind is FormalFactKind.ROLE_EXPERIENCE
        ]
        return _compile_experience(context, match, relevant_facts, self_report)

    candidate_assessments: list[RequirementAssessment] = []
    for candidate in match.competency_candidates:
        record = competencies[candidate.competency_id]
        candidate_assessments.append(
            _from_competency(context, match, candidate.relation, candidate.confidence, record)
        )
    for candidate in match.formal_fact_candidates:
        record = facts[candidate.fact_id]
        candidate_assessments.append(
            _from_formal_fact(context, match, candidate.relation, candidate.confidence, record)
        )

    positive = [
        item for item in candidate_assessments
        if item.status not in {RequirementStatus.UNKNOWN, RequirementStatus.NOT_MET}
    ]
    if positive:
        best = max(positive, key=lambda item: _status_rank(item.status))
        combined_competencies = list(dict.fromkeys(
            competency
            for item in positive
            for competency in item.matched_competencies
        ))
        combined_facts = list(dict.fromkeys(
            fact for item in positive for fact in item.matched_formal_facts
        ))
        combined_evidence = list(dict.fromkeys(
            evidence for item in positive for evidence in item.user_evidence_refs
        ))
        return best.model_copy(update={
            "matched_competencies": combined_competencies,
            "matched_formal_facts": combined_facts,
            "user_evidence_refs": combined_evidence,
        })

    if self_report is not None:
        if self_report.claim_state is ClaimState.NOT_CLAIMED:
            return _assessment(
                context,
                status=RequirementStatus.NOT_MET,
                basis=AssessmentBasis.EXPLICIT_ABSENCE,
                reason="The user explicitly reported that this requirement is not currently met.",
                confidence=1.0,
            )
        if self_report.claim_state is ClaimState.CLAIMED:
            has_evidence = bool(self_report.evidence_refs)
            return _assessment(
                context,
                status=(
                    RequirementStatus.EVIDENCED
                    if has_evidence
                    else RequirementStatus.CLAIMED_ONLY
                ),
                basis=(
                    AssessmentBasis.CAREER_EVIDENCE
                    if has_evidence
                    else AssessmentBasis.USER_CLAIM
                ),
                reason=(
                    "The user linked supporting career evidence to this requirement."
                    if has_evidence
                    else "The user reported this experience, but no supporting evidence was linked."
                ),
                confidence=0.8 if has_evidence else 0.65,
                user_evidence_refs=self_report.evidence_refs,
            )

    return _assessment(
        context,
        status=RequirementStatus.UNKNOWN,
        basis=AssessmentBasis.NO_INFORMATION,
        reason="The supplied user evidence is not sufficient to decide this requirement.",
        confidence=match.confidence,
    )


def _from_competency(
    context: _RequirementContext,
    match: RequirementMatchDraft,
    relation: SemanticRelation,
    relation_confidence: float,
    record: UserCompetencyEvidence,
) -> RequirementAssessment:
    confidence = min(match.confidence, relation_confidence, record.confidence)
    if relation is SemanticRelation.PARTIAL:
        if record.verification_state in {
            VerificationState.VERIFIED,
            VerificationState.PARTIALLY_VERIFIED,
        }:
            basis = AssessmentBasis.VERIFIED_PARTIAL
        elif record.evidence_state is EvidenceState.EVIDENCED:
            basis = AssessmentBasis.CAREER_EVIDENCE
        elif record.claim_state is ClaimState.CLAIMED:
            basis = AssessmentBasis.USER_CLAIM
        else:
            return _assessment(
                context,
                status=RequirementStatus.UNKNOWN,
                basis=AssessmentBasis.NO_INFORMATION,
                reason="A partial semantic link exists, but the user state has no supporting information.",
                confidence=confidence,
            )
        return _assessment(
            context,
            status=RequirementStatus.PARTIAL,
            basis=basis,
            reason=f"{record.display_name} covers only part of this requirement's scope.",
            confidence=confidence,
            matched_competencies=[record.competency_id],
            user_evidence_refs=record.evidence_refs,
        )
    if record.verification_state is VerificationState.VERIFIED:
        status, basis = RequirementStatus.VERIFIED_MET, AssessmentBasis.VERIFIED_COMPETENCY
    elif record.verification_state is VerificationState.PARTIALLY_VERIFIED:
        status, basis = RequirementStatus.PARTIAL, AssessmentBasis.VERIFIED_PARTIAL
    elif record.evidence_state is EvidenceState.EVIDENCED:
        status, basis = RequirementStatus.EVIDENCED, AssessmentBasis.CAREER_EVIDENCE
    elif record.claim_state is ClaimState.CLAIMED:
        status, basis = RequirementStatus.CLAIMED_ONLY, AssessmentBasis.USER_CLAIM
    else:
        status, basis = RequirementStatus.UNKNOWN, AssessmentBasis.NO_INFORMATION
    return _assessment(
        context,
        status=status,
        basis=basis,
        reason=f"{record.display_name} is semantically linked to this requirement ({match.reason}).",
        confidence=confidence,
        matched_competencies=[record.competency_id],
        user_evidence_refs=record.evidence_refs,
    )


def _from_formal_fact(
    context: _RequirementContext,
    match: RequirementMatchDraft,
    relation: SemanticRelation,
    relation_confidence: float,
    record: FormalFact,
) -> RequirementAssessment:
    confidence = min(match.confidence, relation_confidence, record.confidence)
    if record.state is FormalFactState.ABSENT:
        return _assessment(
            context,
            status=RequirementStatus.NOT_MET,
            basis=AssessmentBasis.EXPLICIT_ABSENCE,
            reason=f"The user explicitly reported that {record.label} is absent.",
            confidence=confidence,
            matched_formal_facts=[record.fact_id],
        )
    if record.state is FormalFactState.UNKNOWN:
        return _assessment(
            context,
            status=RequirementStatus.UNKNOWN,
            basis=AssessmentBasis.NO_INFORMATION,
            reason=f"The state of {record.label} is unknown.",
            confidence=confidence,
        )
    if relation is SemanticRelation.PARTIAL:
        status = RequirementStatus.PARTIAL
        basis = (
            AssessmentBasis.VERIFIED_PARTIAL
            if record.verification_state in {
                VerificationState.VERIFIED,
                VerificationState.PARTIALLY_VERIFIED,
            }
            else AssessmentBasis.CAREER_EVIDENCE
            if record.evidence_refs
            else AssessmentBasis.USER_CLAIM
        )
    elif record.verification_state is VerificationState.VERIFIED:
        status, basis = RequirementStatus.VERIFIED_MET, AssessmentBasis.VERIFIED_FORMAL_FACT
    elif record.verification_state is VerificationState.PARTIALLY_VERIFIED:
        status, basis = RequirementStatus.PARTIAL, AssessmentBasis.VERIFIED_PARTIAL
    elif record.evidence_refs:
        status, basis = RequirementStatus.EVIDENCED, AssessmentBasis.CAREER_EVIDENCE
    else:
        status, basis = RequirementStatus.CLAIMED_ONLY, AssessmentBasis.USER_CLAIM
    return _assessment(
        context,
        status=status,
        basis=basis,
        reason=f"{record.label} is linked to this formal requirement ({match.reason}).",
        confidence=confidence,
        matched_formal_facts=[record.fact_id],
        user_evidence_refs=record.evidence_refs,
    )


def _compile_experience(
    context: _RequirementContext,
    match: RequirementMatchDraft,
    facts: list[FormalFact],
    self_report,
) -> RequirementAssessment:
    minimum = context.minimum_months or 0
    if facts:
        fact = max(facts, key=lambda item: item.duration_months or -1)
        months = fact.duration_months
        confidence = min(match.confidence, fact.confidence)
        if fact.state is FormalFactState.ABSENT:
            return _assessment(
                context,
                status=RequirementStatus.NOT_MET,
                basis=AssessmentBasis.EXPLICIT_ABSENCE,
                reason="The user explicitly reported no relevant role experience.",
                confidence=confidence,
                matched_formal_facts=[fact.fact_id],
            )
        if months is None:
            return _assessment(
                context,
                status=RequirementStatus.UNKNOWN,
                basis=AssessmentBasis.NO_INFORMATION,
                reason="Relevant experience was mentioned, but its duration is unknown.",
                confidence=confidence,
            )
        if months < minimum:
            if fact.verification_state is VerificationState.VERIFIED:
                return _assessment(
                    context,
                    status=RequirementStatus.NOT_MET,
                    basis=AssessmentBasis.VERIFIED_INSUFFICIENCY,
                    reason=f"Verified relevant experience is {months} months; {minimum} months are required.",
                    confidence=confidence,
                    matched_formal_facts=[fact.fact_id],
                    user_evidence_refs=fact.evidence_refs,
                )
            return _assessment(
                context,
                status=RequirementStatus.PARTIAL,
                basis=(
                    AssessmentBasis.CAREER_EVIDENCE
                    if fact.evidence_refs
                    else AssessmentBasis.USER_CLAIM
                ),
                reason=f"Reported relevant experience is {months} months; {minimum} months are required.",
                confidence=confidence,
                matched_formal_facts=[fact.fact_id],
                user_evidence_refs=fact.evidence_refs,
            )
        if fact.verification_state is VerificationState.VERIFIED:
            status, basis = RequirementStatus.VERIFIED_MET, AssessmentBasis.VERIFIED_FORMAL_FACT
        elif fact.evidence_refs:
            status, basis = RequirementStatus.EVIDENCED, AssessmentBasis.CAREER_EVIDENCE
        else:
            status, basis = RequirementStatus.CLAIMED_ONLY, AssessmentBasis.USER_CLAIM
        return _assessment(
            context,
            status=status,
            basis=basis,
            reason=f"Relevant experience is {months} months; {minimum} months are required.",
            confidence=confidence,
            matched_formal_facts=[fact.fact_id],
            user_evidence_refs=fact.evidence_refs,
        )

    if self_report is not None and self_report.claim_state is ClaimState.NOT_CLAIMED:
        return _assessment(
            context,
            status=RequirementStatus.NOT_MET,
            basis=AssessmentBasis.EXPLICIT_ABSENCE,
            reason="The user explicitly reported no relevant role experience.",
            confidence=1.0,
        )
    return _assessment(
        context,
        status=RequirementStatus.UNKNOWN,
        basis=AssessmentBasis.NO_INFORMATION,
        reason="No relevant role-experience duration was supplied.",
        confidence=match.confidence,
    )


def _assessment(
    context: _RequirementContext,
    *,
    status: RequirementStatus,
    basis: AssessmentBasis,
    reason: str,
    confidence: float,
    matched_competencies: list[str] | None = None,
    matched_formal_facts: list[str] | None = None,
    user_evidence_refs: list[str] | None = None,
) -> RequirementAssessment:
    return RequirementAssessment(
        requirement_id=context.requirement_id,
        status=status,
        required=context.required,
        included_in_denominator=status not in {
            RequirementStatus.UNKNOWN,
            RequirementStatus.NOT_APPLICABLE,
        },
        basis=basis,
        matched_competencies=matched_competencies or [],
        matched_formal_facts=matched_formal_facts or [],
        user_evidence_refs=user_evidence_refs or [],
        posting_evidence_ids=context.evidence_ids,
        reason=reason,
        confidence=max(0.0, min(1.0, confidence)),
    )


def next_formal_evidence_question(
    request: FitAnalysisRequest,
    contexts: list[_RequirementContext],
    assessments: list[RequirementAssessment],
) -> Ambiguity | None:
    answered = {
        item.requirement_id for item in request.user_evidence.requirement_self_reports
    }
    for context, assessment in zip(contexts, assessments, strict=True):
        if (
            context.required
            and context.category in {
                RequirementCategory.CREDENTIAL,
                RequirementCategory.CERTIFICATION,
                RequirementCategory.LANGUAGE,
                RequirementCategory.EXPERIENCE,
            }
            and assessment.status is RequirementStatus.UNKNOWN
            and context.requirement_id not in answered
        ):
            ambiguity_id = _stable_id(
                "user-evidence",
                request.common_analysis_id,
                request.user_evidence.evidence_set_id,
                str(request.user_evidence.revision),
                context.requirement_id,
            )
            return Ambiguity(
                ambiguity_id=ambiguity_id,
                type=AmbiguityType.USER_EVIDENCE,
                blocking=True,
                reason="현재 근거만으로 형식적인 지원 자격을 판정할 수 없습니다.",
                candidate_ids=[context.requirement_id],
                evidence_ids=context.evidence_ids,
                question=ClarificationQuestion(
                    input_type=QuestionInputType.CHOICE,
                    text=f"현재 다음 요건을 충족하나요? {context.text}",
                    options=[
                        QuestionOption(value="claim-present", label="충족해요"),
                        QuestionOption(value="claim-absent", label="아직 충족하지 못했어요"),
                        QuestionOption(value="claim-unknown", label="잘 모르겠어요"),
                    ],
                ),
            )
    return None


def _calculate_metrics(
    contexts: list[_RequirementContext],
    assessments: list[RequirementAssessment],
) -> FitMetrics:
    required = [item for item in assessments if item.required]
    preferred = [
        assessment
        for context, assessment in zip(contexts, assessments, strict=True)
        if context.obligation is RequirementObligation.PREFERRED
    ]
    known = [item for item in required if item.included_in_denominator]
    return FitMetrics(
        required_total=len(required),
        required_known=len(known),
        required_verified_met=sum(
            1 for item in known if item.status is RequirementStatus.VERIFIED_MET
        ),
        preferred_total=len(preferred),
        claimed_readiness_percent=_readiness(known, "claimed"),
        evidenced_readiness_percent=_readiness(known, "evidenced"),
        verified_readiness_percent=_readiness(known, "verified"),
        capability_readiness_percent=_capability_readiness(known),
        readiness_unavailable_reason=(
            "NO_REQUIRED_REQUIREMENTS"
            if not required
            else "REQUIRED_EVIDENCE_UNKNOWN"
            if not known
            else None
        ),
    )


def _readiness(known: list[RequirementAssessment], tier: str) -> float | None:
    if not known:
        return None
    score = 0.0
    for item in known:
        if tier == "claimed":
            if item.status in {
                RequirementStatus.VERIFIED_MET,
                RequirementStatus.EVIDENCED,
                RequirementStatus.CLAIMED_ONLY,
            }:
                score += 1.0
            elif item.status is RequirementStatus.PARTIAL:
                score += 0.5
        elif tier == "evidenced":
            if item.status in {RequirementStatus.VERIFIED_MET, RequirementStatus.EVIDENCED}:
                score += 1.0
            elif item.status is RequirementStatus.PARTIAL and item.basis not in {
                AssessmentBasis.USER_CLAIM,
            }:
                score += 0.5
        elif tier == "verified":
            if item.status is RequirementStatus.VERIFIED_MET:
                score += 1.0
            elif item.status is RequirementStatus.PARTIAL and item.basis in {
                AssessmentBasis.VERIFIED_PARTIAL,
                AssessmentBasis.VERIFIED_INSUFFICIENCY,
            }:
                score += 0.5
    return round(score * 100 / len(known), 1)


def _capability_readiness(known: list[RequirementAssessment]) -> float | None:
    """Return evidence-maturity readiness without treating UNKNOWN as failure.

    The public policy assigns VERIFIED=100, EVIDENCED=70, CLAIMED=30 and
    NOT_MET=0. PARTIAL keeps the evidence maturity of its basis but receives
    half credit because only part of the requirement scope is covered.
    """
    if not known:
        return None
    score = 0.0
    for item in known:
        if item.status is RequirementStatus.VERIFIED_MET:
            score += 100.0
        elif item.status is RequirementStatus.EVIDENCED:
            score += 70.0
        elif item.status is RequirementStatus.CLAIMED_ONLY:
            score += 30.0
        elif item.status is RequirementStatus.PARTIAL:
            if item.basis in {
                AssessmentBasis.VERIFIED_PARTIAL,
                AssessmentBasis.VERIFIED_INSUFFICIENCY,
            }:
                score += 50.0
            elif item.basis is AssessmentBasis.USER_CLAIM:
                score += 15.0
            else:
                score += 35.0
    return round(score / len(known), 1)


def _formal_eligibility(
    contexts: list[_RequirementContext],
    assessments: list[RequirementAssessment],
) -> RequirementStatus:
    formal = [
        assessment
        for context, assessment in zip(contexts, assessments, strict=True)
        if context.required and context.category in {
            RequirementCategory.CREDENTIAL,
            RequirementCategory.CERTIFICATION,
            RequirementCategory.LANGUAGE,
            RequirementCategory.EXPERIENCE,
        }
    ]
    if not formal:
        return RequirementStatus.NOT_APPLICABLE
    statuses = {item.status for item in formal}
    for status in (
        RequirementStatus.NOT_MET,
        RequirementStatus.UNKNOWN,
        RequirementStatus.PARTIAL,
        RequirementStatus.CLAIMED_ONLY,
        RequirementStatus.EVIDENCED,
    ):
        if status in statuses:
            return status
    return RequirementStatus.VERIFIED_MET


def _propose_verdict(
    assessments: list[RequirementAssessment],
    metrics: FitMetrics,
    formal_eligibility: RequirementStatus,
) -> VerdictProposal:
    if formal_eligibility is RequirementStatus.NOT_MET:
        return VerdictProposal.ALTERNATIVE_PATH
    if metrics.required_total == 0 or metrics.required_known == 0:
        return VerdictProposal.UNKNOWN
    unknown_required = sum(
        1
        for item in assessments
        if item.required and item.status is RequirementStatus.UNKNOWN
    )
    if unknown_required / metrics.required_total > 0.5:
        return VerdictProposal.UNKNOWN
    required_failures = any(
        item.required and item.status is RequirementStatus.NOT_MET
        for item in assessments
    )
    if (
        not required_failures
        and formal_eligibility not in {RequirementStatus.UNKNOWN, RequirementStatus.PARTIAL}
        and (metrics.evidenced_readiness_percent or 0) >= 80
    ):
        return VerdictProposal.APPLY_NOW
    return VerdictProposal.STRENGTHEN_THEN_APPLY


def _status_rank(status: RequirementStatus) -> int:
    return {
        RequirementStatus.VERIFIED_MET: 6,
        RequirementStatus.EVIDENCED: 5,
        RequirementStatus.CLAIMED_ONLY: 4,
        RequirementStatus.PARTIAL: 3,
        RequirementStatus.UNKNOWN: 1,
        RequirementStatus.NOT_MET: 0,
        RequirementStatus.NOT_APPLICABLE: 0,
    }[status]


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"
