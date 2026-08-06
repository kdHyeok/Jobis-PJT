from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jobis_ai_v3.contracts.capability_graph import ProjectNecessity
from jobis_ai_v3.contracts.errors import ErrorCode
from jobis_ai_v3.contracts.posting import (
    RequirementCategory,
    RequirementObligation,
)
from jobis_ai_v3.contracts.project_planning import (
    CompanyProjectBlueprint,
    PlannedProjectTask,
    ProjectPlanningAudit,
    ProjectPlanningRequest,
)
from jobis_ai_v3.contracts.common import WarningItem
from jobis_ai_v3.llm import (
    JsonProviderError,
    JsonProviderNotConfigured,
    LlmProgressCallback,
    StructuredGenerator,
)

from .draft import CompanyProjectBlueprintDraft


PLANNER_VERSION = "company-project-planner-3.3.0"
MAX_PROMPT_CHARS = 96_000
LEARNING_CATEGORIES = {
    RequirementCategory.TECHNOLOGY,
    RequirementCategory.TECHNICAL_CAPABILITY,
    RequirementCategory.DOMAIN_KNOWLEDGE,
}


@dataclass(frozen=True, slots=True)
class _PlanningRequirement:
    requirement_id: str
    text: str
    category: RequirementCategory
    obligation: RequirementObligation
    evidence_ids: list[str]


SYSTEM_PROMPT = """You design one company-target portfolio project and then map its tasks to approved atomic capabilities.

Rules:
1. First design one coherent project with 2-8 meaningful tasks from the posting's actual responsibilities and domain. Do not reshape or omit a valid task merely because the capability catalog lacks an entry.
2. After the tasks are defined, use only canonicalKey values supplied in atomicCapabilities. Never invent or alter a capability key.
3. A broad posting term such as Java, Spring, Kafka, testing, or SQL may require several atomic capabilities. Select only the smallest set actually demonstrated by the task.
4. Every selected capability must be demonstrated by the task objective or acceptance criteria.
5. A task may have an empty capabilityKeys list when no approved capability safely represents its required scope.
6. Every item in learnableRequirements must be referenced by at least one task or listed in unresolvedRequirementIds.
7. List a learnable requirement in unresolvedRequirementIds whenever any of its required learning scope lacks a safe approved mapping. It may still be referenced by a valid project task.
8. Only IDs from learnableRequirements may appear in unresolvedRequirementIds.
9. Items in projectContext shape the project and may be referenced by a task, but they must never appear in unresolvedRequirementIds.
10. Responsibilities and portfolio requirements shape tasks, but attitudes, employment conditions, years of experience, and certificates are never capabilities.
11. Keep the source requirementId references. Do not attach a task to an unrelated requirement merely to satisfy coverage.
12. Acceptance criteria must be observable outputs, tests, measurements, or documents. Avoid vague criteria such as 'understands well'.
13. If the approved graph lacks a suitable atomic capability, keep the task and list the learnable requirementId as unresolved instead of choosing a similar-looking key.
14. Do not assign skill levels or invent prerequisite order. The graph service owns learning order.
15. Return only the requested structured draft and do not reveal hidden reasoning.
"""


class ProjectPlanningFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class ProjectPlanningService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def plan(
        self,
        request: ProjectPlanningRequest,
        *,
        progress_callback: LlmProgressCallback | None = None,
    ) -> CompanyProjectBlueprint:
        requirements = _requirements(request)
        prompt = _prompt(request, requirements)
        try:
            draft, metadata = self._generator.generate(
                CompanyProjectBlueprintDraft,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                progress_callback=progress_callback,
            )
        except JsonProviderNotConfigured as exc:
            raise ProjectPlanningFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderError as exc:
            timed_out = "timed out" in str(exc).casefold() or "timeout" in str(exc).casefold()
            raise ProjectPlanningFailure(
                code=ErrorCode.AI_TIMEOUT if timed_out else ErrorCode.AI_PROVIDER_UNAVAILABLE,
                message=str(exc),
                retryable=True,
            ) from exc

        try:
            tasks, unresolved, ignored_context_ids = _compile_draft(
                request, requirements, draft
            )
        except ValueError as exc:
            raise ProjectPlanningFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc

        blueprint_id = _stable_id(
            "project-blueprint",
            request.common_analysis_id,
            request.selected_position_id,
            request.graph_catalog.graph_version,
            *[task.task_key for task in tasks],
        )
        warnings = [
            WarningItem(
                code="ATOMIC_CAPABILITY_REVIEW_REQUIRED",
                message=(
                    f"Requirement {requirement_id} has no safe approved atomic capability; "
                    "it remains user-scoped until catalog review."
                ),
                evidence_ids=requirements[requirement_id].evidence_ids,
            )
            for requirement_id in unresolved
        ]
        if ignored_context_ids:
            warnings.append(WarningItem(
                code="PROJECT_CONTEXT_WAS_NOT_TREATED_AS_LEARNING_GAP",
                message=(
                    "The model returned project-context IDs as unresolved learning requirements; "
                    "they were excluded without discarding the valid project plan."
                ),
                evidence_ids=list(dict.fromkeys(
                    evidence_id
                    for requirement_id in ignored_context_ids
                    for evidence_id in requirements[requirement_id].evidence_ids
                )),
            ))
        return CompanyProjectBlueprint(
            blueprint_id=blueprint_id,
            common_analysis_id=request.common_analysis_id,
            selected_position_id=request.selected_position_id,
            title=draft.title,
            objective=draft.objective,
            domain_context=draft.domain_context,
            tasks=tasks,
            unresolved_requirement_ids=unresolved,
            audit=ProjectPlanningAudit(
                planner_version=PLANNER_VERSION,
                graph_version=request.graph_catalog.graph_version,
                graph_content_hash=request.graph_catalog.content_hash,
                provider=metadata.provider,
                model=metadata.model,
                generation_attempts=metadata.attempts,
                generation_duration_ms=metadata.duration_ms,
                generation_effort=metadata.final_effort,
                generation_effort_history=list(metadata.effort_history),
                provider_duration_ms=metadata.provider_duration_ms,
                provider_api_duration_ms=metadata.provider_api_duration_ms,
                input_tokens=metadata.input_tokens,
                output_tokens=metadata.output_tokens,
                cache_creation_input_tokens=metadata.cache_creation_input_tokens,
                cache_read_input_tokens=metadata.cache_read_input_tokens,
                total_cost_usd=metadata.total_cost_usd,
                provider_session_ids=list(metadata.session_ids),
            ),
            warnings=warnings,
        )


def _requirements(request: ProjectPlanningRequest) -> dict[str, _PlanningRequirement]:
    position = next(
        item
        for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    atomic_requirements = [
        *position.requirements,
        *[
            item
            for item in request.structured_posting.shared_conditions
            if request.selected_position_id in item.applies_to_position_ids
        ],
    ]
    result = {
        item.requirement_id: _PlanningRequirement(
            requirement_id=item.requirement_id,
            text=item.atomic_text,
            category=item.category,
            obligation=item.obligation,
            evidence_ids=item.evidence_ids,
        )
        for item in atomic_requirements
    }
    result.update({
        item.responsibility_id: _PlanningRequirement(
            requirement_id=item.responsibility_id,
            text=item.atomic_text,
            category=RequirementCategory.RESPONSIBILITY,
            obligation=RequirementObligation.REQUIRED,
            evidence_ids=item.evidence_ids,
        )
        for item in position.responsibilities
    })
    return result


def _prompt(
    request: ProjectPlanningRequest,
    requirements: dict[str, _PlanningRequirement],
) -> str:
    position = next(
        item
        for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    company = request.structured_posting.company
    payload = {
        "company": company.display_name if company else None,
        "postingTitle": request.structured_posting.posting_title,
        "position": {
            "title": position.source_title,
            "roleFamily": position.role.family,
            "roleSpecialization": position.role.specialization,
        },
        "learnableRequirements": [
            {
                "requirementId": item.requirement_id,
                "text": item.text,
                "category": item.category.value,
                "obligation": item.obligation.value,
            }
            for item in requirements.values()
            if item.category in LEARNING_CATEGORIES
            and item.obligation in {
                RequirementObligation.REQUIRED,
                RequirementObligation.PREFERRED,
            }
        ],
        "projectContext": [
            {
                "contextId": item.requirement_id,
                "text": item.text,
                "category": item.category.value,
                "obligation": item.obligation.value,
                "instruction": "May shape and be referenced by tasks; never mark unresolved.",
            }
            for item in requirements.values()
            if not (
                item.category in LEARNING_CATEGORIES
                and item.obligation in {
                    RequirementObligation.REQUIRED,
                    RequirementObligation.PREFERRED,
                }
            )
        ],
        "atomicCapabilities": [
            {
                "canonicalKey": item.canonical_key,
                "technologyKey": item.technology_key,
                "displayName": item.display_name,
                "kind": item.kind.value,
                "objective": item.objective,
                "scopeDefinition": item.scope_definition,
                "excludedScope": item.excluded_scope,
                "verificationMethods": [value.value for value in item.verification_methods],
                "aliases": item.aliases,
            }
            for item in request.graph_catalog.capabilities
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_PROMPT_CHARS:
        raise ProjectPlanningFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message=(
                f"project planning input is {len(encoded)} characters; "
                "a graph catalog search adapter is required"
            ),
            retryable=False,
        )
    return encoded


def _compile_draft(request, requirements, draft):
    catalog_keys = {item.canonical_key for item in request.graph_catalog.capabilities}
    requirement_ids = set(requirements)
    learning_ids = {
        item.requirement_id
        for item in requirements.values()
        if item.category in LEARNING_CATEGORIES
        and item.obligation in {
            RequirementObligation.REQUIRED,
            RequirementObligation.PREFERRED,
        }
    }
    proposed_unresolved = list(dict.fromkeys(draft.unresolved_requirement_ids))
    unknown_unresolved = set(proposed_unresolved) - requirement_ids
    if unknown_unresolved:
        raise ValueError(
            f"unresolvedRequirementIds contain unknown requirements: {sorted(unknown_unresolved)}"
        )
    ignored_context_ids = [
        requirement_id
        for requirement_id in proposed_unresolved
        if requirement_id not in learning_ids
    ]
    unresolved = [
        requirement_id
        for requirement_id in proposed_unresolved
        if requirement_id in learning_ids
    ]

    tasks = []
    covered_learning: set[str] = set()
    for index, item in enumerate(draft.tasks, start=1):
        unknown_capabilities = set(item.capability_keys) - catalog_keys
        if unknown_capabilities:
            raise ValueError(
                f"project task proposed unknown capability keys: {sorted(unknown_capabilities)}"
            )
        unknown_requirements = set(item.requirement_ids) - requirement_ids
        if unknown_requirements:
            raise ValueError(
                f"project task refers to unknown requirements: {sorted(unknown_requirements)}"
            )
        task_learning_ids = set(item.requirement_ids) & learning_ids
        covered_learning.update(task_learning_ids)
        necessity = _necessity(
            [requirements[requirement_id] for requirement_id in item.requirement_ids]
        )
        task_key = _stable_key(
            request.common_analysis_id,
            request.selected_position_id,
            str(index),
            item.title,
        )
        tasks.append(PlannedProjectTask(
            task_key=task_key,
            necessity=necessity,
            title=item.title,
            objective=item.objective,
            acceptance_criteria=item.acceptance_criteria,
            capability_keys=list(dict.fromkeys(item.capability_keys)),
            requirement_ids=list(dict.fromkeys(item.requirement_ids)),
        ))

    missing = learning_ids - covered_learning - set(unresolved)
    if missing:
        raise ValueError(
            "project planner omitted learnable requirements without marking them unresolved: "
            f"{sorted(missing)}"
        )
    return tasks, unresolved, ignored_context_ids


def _necessity(requirements) -> ProjectNecessity:
    obligations = {item.obligation for item in requirements}
    if RequirementObligation.REQUIRED in obligations:
        return ProjectNecessity.REQUIRED
    if RequirementObligation.PREFERRED in obligations:
        return ProjectNecessity.RECOMMENDED
    return ProjectNecessity.EXTENSION


def _stable_key(*parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:20]
    return f"task.draft.{digest}"


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"
