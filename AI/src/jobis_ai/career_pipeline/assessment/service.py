from __future__ import annotations

import hashlib
import json

from jobis_ai.career_pipeline.contracts.assessment import (
    AssessmentGenerationAudit,
    CapabilityAssessmentGrade,
    CapabilityAssessmentQuestion,
    CapabilityGradeRequest,
    CapabilityQuestionRequest,
)
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.llm import JsonProviderError, JsonProviderNotConfigured, StructuredGenerator

from .draft import CapabilityGradeDraft, CapabilityQuestionDraft


ASSESSMENT_VERSION = "atomic-capability-assessment-3.0.0"
QUESTION_PASS_SCORE = 60

QUESTION_SYSTEM_PROMPT = """You create one assessment question for exactly one approved atomic capability.

Hard rules:
1. Test only the supplied objective and scopeDefinition. Never test an excludedScope item.
2. The company, role, project task, current goal, and final goal may make the scenario concrete, but must not expand the scored knowledge boundary.
3. Use exactly the requested verificationMethod. Do not replace an implementation task with trivia or an explanation task with unrelated architecture design.
4. coreCriteria are the only scored criteria. Each must be observable from the answer and must fit inside scopeDefinition.
5. Put useful but out-of-scope advanced ideas only in futureExtensions. They never affect pass/fail.
6. Do not test frameworks, databases, distributed systems, transactions, or operations unless they are explicitly inside scopeDefinition.
7. Avoid repeating the completed questions. A repeated method must use a meaningfully different example inside the same scope.
8. Return only the requested structured draft and never reveal hidden reasoning.
"""

GRADE_SYSTEM_PROMPT = """You grade an answer to one atomic capability assessment question.

Hard rules:
1. Grade only the supplied coreCriteria and answer. futureExtensions never affect the score.
2. Return exactly one criterionGrades item for every core criterion, using its zero-based index.
3. Do not reward claims that are not demonstrated in the answer.
4. Company context is scenario decoration, not a reason to demand adjacent frameworks or architecture.
5. Set scopeViolationDetected only if the question itself requires knowledge outside the supplied atomic scope; explain that problem in gaps.
6. Be specific and educational. Return only the requested structured draft and never reveal hidden reasoning.
"""


class AssessmentFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class AtomicCapabilityAssessmentService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def question(self, request: CapabilityQuestionRequest) -> CapabilityAssessmentQuestion:
        method = request.capability.verification_methods[
            (request.ordinal - 1) % len(request.capability.verification_methods)
        ]
        try:
            draft, metadata = self._generator.generate(
                CapabilityQuestionDraft,
                system_prompt=QUESTION_SYSTEM_PROMPT,
                user_prompt=json.dumps({
                    "verificationMethod": method.value,
                    "atomicCapability": request.capability.model_dump(mode="json", by_alias=True),
                    "targetContext": request.target.model_dump(mode="json", by_alias=True),
                    "completedTurns": [
                        {
                            "ordinal": item.ordinal,
                            "method": item.method.value,
                            "prompt": item.prompt,
                            "score": item.score,
                            "gaps": item.gaps,
                        }
                        for item in request.completed_turns
                    ],
                }, ensure_ascii=False),
            )
        except (JsonProviderNotConfigured, JsonProviderError) as exc:
            raise _provider_failure(exc) from exc

        question_id = _stable_id(
            "atomic-question",
            request.session_id,
            request.capability.canonical_key,
            str(request.ordinal),
            method.value,
            draft.prompt,
        )
        return CapabilityAssessmentQuestion(
            question_id=question_id,
            session_id=request.session_id,
            capability_key=request.capability.canonical_key,
            ordinal=request.ordinal,
            method=method,
            prompt=draft.prompt,
            starter_code=draft.starter_code,
            answer_instructions=draft.answer_instructions,
            core_criteria=draft.core_criteria,
            future_extensions=draft.future_extensions,
            audit=_audit(metadata),
        )

    def grade(self, request: CapabilityGradeRequest) -> CapabilityAssessmentGrade:
        try:
            draft, metadata = self._generator.generate(
                CapabilityGradeDraft,
                system_prompt=GRADE_SYSTEM_PROMPT,
                user_prompt=json.dumps({
                    "atomicCapability": request.capability.model_dump(mode="json", by_alias=True),
                    "targetContext": request.target.model_dump(mode="json", by_alias=True),
                    "question": request.question.model_dump(mode="json", by_alias=True),
                    "answer": request.answer,
                }, ensure_ascii=False),
            )
        except (JsonProviderNotConfigured, JsonProviderError) as exc:
            raise _provider_failure(exc) from exc

        expected_indexes = list(range(len(request.question.core_criteria)))
        actual_indexes = sorted(item.criterion_index for item in draft.criterion_grades)
        if actual_indexes != expected_indexes:
            raise AssessmentFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message="grader did not return exactly one score for every core criterion",
                retryable=False,
            )
        score = round(sum(item.score for item in draft.criterion_grades) / len(draft.criterion_grades))
        passed = score >= QUESTION_PASS_SCORE and not draft.scope_violation_detected
        return CapabilityAssessmentGrade(
            question_id=request.question.question_id,
            criterion_grades=sorted(
                draft.criterion_grades,
                key=lambda item: item.criterion_index,
            ),
            score=score,
            passed=passed,
            strengths=draft.strengths,
            gaps=draft.gaps,
            feedback=draft.feedback,
            scope_violation_detected=draft.scope_violation_detected,
            audit=_audit(metadata),
        )


def _provider_failure(exc: Exception) -> AssessmentFailure:
    if isinstance(exc, JsonProviderNotConfigured):
        return AssessmentFailure(
            code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
            message=str(exc),
            retryable=False,
        )
    timed_out = "timed out" in str(exc).casefold() or "timeout" in str(exc).casefold()
    return AssessmentFailure(
        code=ErrorCode.AI_TIMEOUT if timed_out else ErrorCode.AI_PROVIDER_UNAVAILABLE,
        message=str(exc),
        retryable=True,
    )


def _audit(metadata) -> AssessmentGenerationAudit:
    return AssessmentGenerationAudit(
        generator_version=ASSESSMENT_VERSION,
        provider=metadata.provider,
        model=metadata.model,
        attempts=metadata.attempts,
        duration_ms=metadata.duration_ms,
    )


def _stable_id(*values: str) -> str:
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:24]
    return f"{values[0]}:{digest}"
