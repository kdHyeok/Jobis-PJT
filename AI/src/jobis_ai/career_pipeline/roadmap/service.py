from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from jobis_ai.career_pipeline.capability_graph import validate_closure_hash
from jobis_ai.career_pipeline.contracts.capability_graph import CapabilityRelationType, ProjectNecessity
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.common import WarningItem
from jobis_ai.career_pipeline.contracts.fit import (
    ClaimState,
    EvidenceState,
    RequirementStatus,
    VerificationState,
)
from jobis_ai.career_pipeline.contracts.normalization import (
    NormalizationDecision,
    RoadmapDisposition,
)
from jobis_ai.career_pipeline.contracts.posting import (
    ExperienceKind,
    RequirementCategory,
    RequirementObligation,
)
from jobis_ai.career_pipeline.contracts.roadmap import (
    CareerGateType,
    ExcludedRequirement,
    GateSpec,
    OpportunitySpec,
    OpportunityGoalMode,
    ProjectSpec,
    RoadmapAction,
    RoadmapAudit,
    RoadmapDraftRequest,
    RoadmapNodeKind,
    RoadmapOperation,
    RoadmapProgressState,
    RoadmapProposal,
    RoadmapRelation,
    RoadmapRelationType,
    SectionMembership,
)
from jobis_ai.career_pipeline.contracts.posting import PostingStatus
from jobis_ai.career_pipeline.llm import JsonProviderError, JsonProviderNotConfigured, StructuredGenerator

from .draft import RoadmapContentDraft


COMPOSER_VERSION = "roadmap-composer-3.1.0"
MAX_PROMPT_CHARS = 48_000


SYSTEM_PROMPT = """You design one company-target project brief from atomic capabilities.

Rules:
1. Use only capability keys and provisional candidate IDs supplied in the input.
2. Keep required and preferred capabilities separate. Return every supplied target capability in the same group.
3. The project is a future, company-target preparation project. Do not copy a past resume project into the roadmap.
4. Reflect the position's technical requirements, responsibilities, and domain, but do not copy a whole job posting as a title.
5. Prefer one coherent project over many tiny exercises. It must produce concrete deliverables and verifiable criteria.
6. Do not treat attitudes, years of experience, certificates, or employment conditions as technologies.
7. Do not invent prerequisite relations. The approved capability graph is the only source of learning order.
8. Treat every supplied capability scope as one atomic, independently verifiable unit. Do not assign levels.
9. Do not reveal hidden reasoning. Return only the requested structured draft.
"""


class RoadmapDraftFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class RoadmapDraftService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def compose(self, request: RoadmapDraftRequest) -> RoadmapProposal:
        try:
            validate_closure_hash(request.capability_graph)
        except RuntimeError as exc:
            raise RoadmapDraftFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc

        requirement_by_id = _requirements_by_id(request)
        position = next(
            item for item in request.structured_posting.positions
            if item.position_id == request.selected_position_id
        )
        (
            required_keys,
            preferred_keys,
            required_provisional,
            preferred_provisional,
            provisional_items,
            requirement_keys,
            excluded,
        ) = _curriculum_targets(request, requirement_by_id)
        graph_targets = set(request.capability_graph.target_capability_keys)
        missing_graph_targets = (required_keys | preferred_keys) - graph_targets
        if missing_graph_targets:
            raise RoadmapDraftFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=(
                    "capability graph closure is missing normalized targets: "
                    f"{sorted(missing_graph_targets)}"
                ),
                retryable=False,
            )

        draft = request.project_blueprint
        metadata = draft.audit
        _validate_blueprint_references(draft, required_keys, preferred_keys)

        operations: list[RoadmapOperation] = []
        existing_by_key = {
            node.canonical_key: node
            for node in request.current_roadmap.nodes
            if node.canonical_key is not None
        }
        existing_by_candidate = {
            node.provisional_candidate_id: node
            for node in request.current_roadmap.nodes
            if node.provisional_candidate_id is not None
        }
        existing_by_target = {
            (node.node_kind, node.target_ref): node
            for node in request.current_roadmap.nodes
            if node.target_ref is not None
        }
        operation_by_capability: dict[str, str] = {}
        preserved_ids: list[str] = []
        role_section = _role_section(request)
        competency_by_key = {
            item.competency_id: item
            for item in (request.user_evidence.competencies if request.user_evidence else [])
        }

        for node in request.capability_graph.nodes:
            existing = existing_by_key.get(node.canonical_key)
            operation_id = _stable_id("op-capability", node.canonical_key)
            operation_by_capability[node.canonical_key] = operation_id
            req_ids = requirement_keys.get(node.canonical_key, [])
            if existing is not None:
                preserved_ids.append(existing.node_id)
            operations.append(RoadmapOperation(
                operation_id=operation_id,
                action=(RoadmapAction.REUSE_NODE if existing else RoadmapAction.CREATE_NODE),
                node_kind=RoadmapNodeKind.CAPABILITY,
                canonical_key=node.canonical_key,
                technology_key=node.technology_key,
                graph_node_version=node.version,
                verification_methods=node.verification_methods,
                objective=node.objective,
                excluded_scope=node.excluded_scope,
                completion_policy=node.completion_policy,
                existing_node_id=existing.node_id if existing else None,
                title=node.display_name,
                scope_definition=node.scope_definition,
                section_key=(existing.section_key if existing else role_section),
                initial_progress_state=(
                    existing.progress_state
                    if existing
                    else _progress_from_competency(competency_by_key.get(node.canonical_key))
                ),
                progress_evidence_set_id=(
                    request.user_evidence.evidence_set_id
                    if existing is None
                    and request.user_evidence is not None
                    and _progress_from_competency(
                        competency_by_key.get(node.canonical_key)
                    ) is not RoadmapProgressState.NOT_STARTED
                    else None
                ),
                preserve_existing_progress=True,
                requirement_ids=req_ids,
                required_for=(
                    [request.opportunity.opportunity_id]
                    if node.canonical_key in required_keys else []
                ),
                preferred_for=(
                    [request.opportunity.opportunity_id]
                    if node.canonical_key in preferred_keys else []
                ),
                section_memberships=_section_memberships(
                    draft,
                    role_section,
                    request.opportunity.opportunity_id,
                    capability_key=node.canonical_key,
                    requirement_ids=req_ids,
                ),
                reason=(
                    "Existing user capability node is reused without changing its progress."
                    if existing
                    else "Approved capability graph node is added to the draft."
                ),
            ))

        for candidate_id, item in provisional_items.items():
            existing = existing_by_candidate.get(candidate_id)
            operation_id = _stable_id("op-provisional", candidate_id)
            operation_by_capability[candidate_id] = operation_id
            requirement_id = item.requirement_id
            if existing is not None:
                preserved_ids.append(existing.node_id)
            operations.append(RoadmapOperation(
                operation_id=operation_id,
                action=(RoadmapAction.REUSE_NODE if existing else RoadmapAction.CREATE_NODE),
                node_kind=RoadmapNodeKind.CAPABILITY,
                provisional_candidate_id=candidate_id,
                existing_node_id=existing.node_id if existing else None,
                title=item.new_candidate.display_name,
                scope_definition=item.new_candidate.scope_definition,
                section_key=role_section,
                initial_progress_state=(
                    existing.progress_state if existing else RoadmapProgressState.NOT_STARTED
                ),
                requirement_ids=[requirement_id],
                required_for=(
                    [request.opportunity.opportunity_id]
                    if candidate_id in required_provisional else []
                ),
                preferred_for=(
                    [request.opportunity.opportunity_id]
                    if candidate_id in preferred_provisional else []
                ),
                section_memberships=_section_memberships(
                    draft,
                    role_section,
                    request.opportunity.opportunity_id,
                    capability_key=None,
                    requirement_ids=[requirement_id],
                ),
                reason=(
                    "Existing provisional capability is reused while catalog review remains pending."
                    if existing
                    else "A user-scoped provisional capability is added without approving it globally."
                ),
            ))

        relations = _graph_relations(request, operation_by_capability)
        project_target = f"project:{request.opportunity.opportunity_id}"
        project_existing = existing_by_target.get((RoadmapNodeKind.TARGET_PROJECT, project_target))
        project_operation_id = _stable_id("op-project", project_target)
        if project_existing:
            preserved_ids.append(project_existing.node_id)
            operations.append(_reuse_non_capability(
                project_operation_id,
                project_existing,
                target_ref=project_target,
                reason="Existing company-target project is reused.",
            ))
        else:
            operations.append(RoadmapOperation(
                operation_id=project_operation_id,
                action=RoadmapAction.CREATE_TARGET_PROJECT,
                node_kind=RoadmapNodeKind.TARGET_PROJECT,
                target_ref=project_target,
                title=draft.title,
                scope_definition=draft.objective,
                section_key=role_section,
                project_spec=ProjectSpec(
                    objective=draft.objective,
                    deliverables=(
                        [task.title for task in draft.tasks]
                        if len(draft.tasks) >= 2
                        else [
                            *(task.title for task in draft.tasks),
                            "미분류 역량의 범위와 검증 기준 문서",
                            "실행 가능한 회사 맞춤 프로젝트 결과물",
                        ][:2]
                    ),
                    verification_criteria=([ 
                        criterion
                        for task in draft.tasks
                        for criterion in task.acceptance_criteria
                    ] or [
                        "미분류 역량은 운영자 검토 전 공용 역량으로 확정하지 않는다.",
                        "프로젝트 실행 방법과 검증 결과를 문서화한다.",
                    ]),
                    required_capability_keys=sorted(required_keys),
                    preferred_capability_keys=sorted(preferred_keys),
                    required_provisional_candidate_ids=sorted(required_provisional),
                    preferred_provisional_candidate_ids=sorted(preferred_provisional),
                    domain_context=draft.domain_context,
                    tasks=draft.tasks,
                ),
                required_for=[request.opportunity.opportunity_id],
                reason="A single company-target project consolidates the required capabilities.",
            ))

        for key in sorted(required_keys):
            relations.append(_relation(
                operation_by_capability[key],
                project_operation_id,
                RoadmapRelationType.UNLOCKS_PROJECT,
                f"{key} is required before completing the target project.",
            ))
        for key in sorted(preferred_keys):
            relations.append(_relation(
                operation_by_capability[key],
                project_operation_id,
                RoadmapRelationType.BONUS_SUPPORTS_PROJECT,
                f"{key} strengthens the target project but does not block it.",
            ))
        for candidate_id in sorted(required_provisional):
            relations.append(_relation(
                operation_by_capability[candidate_id],
                project_operation_id,
                RoadmapRelationType.UNLOCKS_PROJECT,
                "The provisional capability is required for the target project.",
            ))
        for candidate_id in sorted(preferred_provisional):
            relations.append(_relation(
                operation_by_capability[candidate_id],
                project_operation_id,
                RoadmapRelationType.BONUS_SUPPORTS_PROJECT,
                "The provisional capability is a bonus for the target project.",
            ))

        gate_operation_ids = _add_gates(
            request,
            operations,
            existing_by_target,
            role_section,
            preserved_ids,
            requirement_by_id,
        )
        opportunity_target = request.opportunity.opportunity_id
        opportunity_existing = existing_by_target.get(
            (RoadmapNodeKind.OPPORTUNITY, opportunity_target)
        )
        opportunity_operation_id = _stable_id("op-opportunity", opportunity_target)
        if opportunity_existing:
            preserved_ids.append(opportunity_existing.node_id)
            operations.append(_reuse_non_capability(
                opportunity_operation_id,
                opportunity_existing,
                target_ref=opportunity_target,
                reason="Existing company opportunity is reused.",
            ))
        else:
            operations.append(RoadmapOperation(
                operation_id=opportunity_operation_id,
                action=RoadmapAction.ADD_OPPORTUNITY,
                node_kind=RoadmapNodeKind.OPPORTUNITY,
                target_ref=opportunity_target,
                title=f"{request.opportunity.company_name} · {request.opportunity.position_title}",
                section_key=role_section,
                opportunity_spec=OpportunitySpec(
                    opportunity_id=request.opportunity.opportunity_id,
                    company_name=request.opportunity.company_name,
                    position_title=request.opportunity.position_title,
                    posting_title=request.opportunity.posting_title,
                    role_family=position.role.family,
                    role_specialization=position.role.specialization,
                    canonical_role_id=position.role.canonical_role_id,
                    source_experience_kind=position.experience.kind,
                    selected_experience_track=(
                        request.fit_assessment.selected_experience_track
                    ),
                    minimum_experience_months=_minimum_experience_months(
                        position.experience,
                        request.fit_assessment.selected_experience_track,
                    ),
                    maximum_experience_months=_maximum_experience_months(
                        position.experience,
                        request.fit_assessment.selected_experience_track,
                    ),
                    posting_status=request.structured_posting.posting_status,
                    application_deadline=request.structured_posting.application_deadline,
                    goal_mode={
                        PostingStatus.ACTIVE: OpportunityGoalMode.ACTIVE_APPLICATION,
                        PostingStatus.CLOSED: OpportunityGoalMode.REOPENING_PREPARATION,
                        PostingStatus.UNKNOWN: OpportunityGoalMode.REFERENCE_TARGET,
                    }[request.structured_posting.posting_status],
                ),
                reason="The analyzed posting becomes a company opportunity at the end of this branch.",
            ))
        relations.append(_relation(
            project_operation_id,
            opportunity_operation_id,
            RoadmapRelationType.UNLOCKS_OPPORTUNITY,
            "Completing the company-target project unlocks the opportunity milestone.",
        ))
        for gate_operation_id in gate_operation_ids:
            relations.append(_relation(
                gate_operation_id,
                opportunity_operation_id,
                RoadmapRelationType.REQUIRES_GATE,
                "The formal career gate must be met for this opportunity.",
            ))

        proposal_id = _stable_id(
            "roadmap-proposal",
            request.common_analysis_id,
            request.fit_assessment.fit_assessment_id,
            request.normalization.normalization_id,
            str(request.current_roadmap.roadmap_version),
            request.opportunity.opportunity_id,
        )
        return RoadmapProposal(
            proposal_id=proposal_id,
            based_on_analysis_id=request.common_analysis_id,
            based_on_fit_assessment_id=request.fit_assessment.fit_assessment_id,
            based_on_normalization_id=request.normalization.normalization_id,
            based_on_roadmap_version=request.current_roadmap.roadmap_version,
            selected_position_id=request.selected_position_id,
            capability_graph_version=request.capability_graph.graph_version,
            operations=operations,
            relations=relations,
            excluded_requirements=excluded,
            warnings=_roadmap_warnings(request),
            audit=RoadmapAudit(
                composer_version=COMPOSER_VERSION,
                provider=metadata.provider,
                model=metadata.model,
                generation_attempts=metadata.generation_attempts,
                generation_duration_ms=metadata.generation_duration_ms,
                graph_content_hash=request.capability_graph.content_hash,
                preserved_existing_node_ids=sorted(set(preserved_ids)),
            ),
        )


def _requirements_by_id(request: RoadmapDraftRequest) -> dict:
    position = next(
        item for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    requirements = [
        *position.requirements,
        *[
            item for item in request.structured_posting.shared_conditions
            if request.selected_position_id in item.applies_to_position_ids
        ],
    ]
    return {item.requirement_id: item for item in requirements}


def _roadmap_warnings(request: RoadmapDraftRequest) -> list[WarningItem]:
    warnings: list[WarningItem] = list(request.project_blueprint.warnings)
    unresolved = set(request.project_blueprint.unresolved_requirement_ids)
    for item in request.normalization.items:
        if item.requirement_id not in unresolved:
            continue
        if item.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED:
            warnings.append(WarningItem(
                code="PROVISIONAL_CAPABILITY_PENDING_REVIEW",
                message=(
                    f"{item.new_candidate.display_name} is user-scoped in this draft; "
                    "no prerequisite relation is invented before catalog approval."
                ),
                evidence_ids=item.evidence_ids,
            ))
        elif item.decision is NormalizationDecision.CANDIDATES_PROPOSED and len(item.candidates) == 1:
            warnings.append(WarningItem(
                code="CAPABILITY_LINK_PENDING_REVIEW",
                message=(
                    f"The proposed link to {item.candidates[0].canonical_key} is used only in this "
                    "draft until an operator reviews the catalog mapping."
                ),
                evidence_ids=item.evidence_ids,
            ))
    return warnings


def _curriculum_targets(request: RoadmapDraftRequest, requirement_by_id: dict):
    required_keys: set[str] = set()
    preferred_keys: set[str] = set()
    required_provisional: set[str] = set()
    preferred_provisional: set[str] = set()
    provisional_items: dict[str, object] = {}
    requirement_keys: dict[str, list[str]] = defaultdict(list)
    excluded: list[ExcludedRequirement] = []
    for task in request.project_blueprint.tasks:
        target = (
            required_keys
            if task.necessity is ProjectNecessity.REQUIRED
            else preferred_keys
        )
        target.update(task.capability_keys)
        for key in task.capability_keys:
            requirement_keys[key].extend(task.requirement_ids)

    mapped_requirement_ids = {
        requirement_id
        for task in request.project_blueprint.tasks
        for requirement_id in task.requirement_ids
    }
    unresolved_requirement_ids = set(
        request.project_blueprint.unresolved_requirement_ids
    )
    for item in request.normalization.items:
        requirement = requirement_by_id.get(item.requirement_id)
        if item.disposition is not RoadmapDisposition.LEARNING_CAPABILITY:
            excluded.append(ExcludedRequirement(
                requirement_id=item.requirement_id,
                reason_code=item.disposition.value,
                explanation=item.reason,
            ))
            continue
        if requirement is None:
            raise RoadmapDraftFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=f"normalization refers to unknown requirement {item.requirement_id}",
                retryable=False,
            )
        required = requirement.obligation is RequirementObligation.REQUIRED
        preferred = requirement.obligation is RequirementObligation.PREFERRED
        if not required and not preferred:
            excluded.append(ExcludedRequirement(
                requirement_id=item.requirement_id,
                reason_code="INFORMATIONAL_REQUIREMENT",
                explanation="Informational requirements do not create roadmap targets.",
            ))
            continue
        if (
            item.requirement_id in unresolved_requirement_ids
            and item.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED
        ):
            candidate_id = item.new_candidate.candidate_id
            provisional_items[candidate_id] = item
            (required_provisional if required else preferred_provisional).add(candidate_id)
        elif item.requirement_id in mapped_requirement_ids:
            continue
        else:
            excluded.append(ExcludedRequirement(
                requirement_id=item.requirement_id,
                reason_code=item.decision.value,
                explanation="The capability target is unresolved or requires source splitting.",
            ))
    preferred_keys -= required_keys
    for key, values in requirement_keys.items():
        requirement_keys[key] = list(dict.fromkeys(values))
    preferred_provisional -= required_provisional
    return (
        required_keys,
        preferred_keys,
        required_provisional,
        preferred_provisional,
        provisional_items,
        requirement_keys,
        excluded,
    )


def _build_prompt(
    request,
    required_keys,
    preferred_keys,
    required_provisional,
    preferred_provisional,
    provisional_items,
    requirement_by_id,
) -> str:
    nodes = {item.canonical_key: item for item in request.capability_graph.nodes}
    position = next(
        item for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    payload = {
        "company": request.opportunity.company_name,
        "position": request.opportunity.position_title,
        "requiredCapabilities": [
            {
                "canonicalKey": key,
                "displayName": nodes[key].display_name,
                "scopeDefinition": nodes[key].scope_definition,
            }
            for key in sorted(required_keys)
        ],
        "preferredCapabilities": [
            {
                "canonicalKey": key,
                "displayName": nodes[key].display_name,
                "scopeDefinition": nodes[key].scope_definition,
            }
            for key in sorted(preferred_keys)
        ],
        "requiredProvisionalCapabilities": [
            {
                "candidateId": candidate_id,
                "displayName": provisional_items[candidate_id].new_candidate.display_name,
                "scopeDefinition": provisional_items[candidate_id].new_candidate.scope_definition,
            }
            for candidate_id in sorted(required_provisional)
        ],
        "preferredProvisionalCapabilities": [
            {
                "candidateId": candidate_id,
                "displayName": provisional_items[candidate_id].new_candidate.display_name,
                "scopeDefinition": provisional_items[candidate_id].new_candidate.scope_definition,
            }
            for candidate_id in sorted(preferred_provisional)
        ],
        "responsibilities": _unique_texts(
            [item.atomic_text for item in position.responsibilities]
            + [
                item.atomic_text
                for item in position.requirements
                if item.category is RequirementCategory.RESPONSIBILITY
            ]
        ),
        "projectContext": [
            item.atomic_text
            for item in requirement_by_id.values()
            if item.category in {
                RequirementCategory.RESPONSIBILITY,
                RequirementCategory.PORTFOLIO,
                RequirementCategory.DOMAIN_KNOWLEDGE,
            }
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_PROMPT_CHARS:
        raise RoadmapDraftFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message="roadmap content prompt exceeds the configured limit",
            retryable=False,
        )
    return encoded


def _unique_texts(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))


def _validate_blueprint_references(draft, required_keys, preferred_keys) -> None:
    actual_required = {
        key
        for task in draft.tasks
        if task.necessity is ProjectNecessity.REQUIRED
        for key in task.capability_keys
    }
    actual_preferred = {
        key
        for task in draft.tasks
        if task.necessity is not ProjectNecessity.REQUIRED
        for key in task.capability_keys
    } - actual_required
    if actual_required != required_keys or actual_preferred != preferred_keys:
        raise RoadmapDraftFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message="project blueprint capability groups changed before roadmap compilation",
            retryable=False,
        )


def _role_section(request: RoadmapDraftRequest) -> str:
    position = next(
        item for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    value = position.role.specialization.casefold().replace(" ", "_").replace("-", "_")
    if not value.isascii() or not all(character.isalnum() or character == "_" for character in value):
        value = f"role_{hashlib.sha256(position.role.specialization.encode()).hexdigest()[:12]}"
    return f"section.{value}"


def _minimum_experience_months(experience, selected_track) -> int | None:
    if experience.kind in {ExperienceKind.NEW_GRADUATE, ExperienceKind.NO_RESTRICTION}:
        return 0
    if experience.kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
        return experience.min_months
    if experience.kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED:
        if selected_track is not None and selected_track.value == "EXPERIENCED":
            return experience.experienced_min_months
        return 0
    return None


def _section_memberships(
    blueprint,
    section_key: str,
    opportunity_id: str,
    *,
    capability_key: str | None,
    requirement_ids: list[str],
) -> list[SectionMembership]:
    requirement_set = set(requirement_ids)
    matched = [
        task
        for task in blueprint.tasks
        if (
            capability_key is not None and capability_key in task.capability_keys
        ) or requirement_set.intersection(task.requirement_ids)
    ]
    if not matched:
        return [SectionMembership(
            section_key=section_key,
            chapter_key=f"chapter.foundation:{opportunity_id}",
            chapter_title="직무 기반 역량",
            target_ref=opportunity_id,
            reason="회사 맞춤 프로젝트에 필요한 선수 또는 미분류 원자 역량입니다.",
        )]
    return [
        SectionMembership(
            section_key=section_key,
            chapter_key=f"chapter.task:{task.task_key}",
            chapter_title=task.title,
            target_ref=opportunity_id,
            reason=f"{task.title} 과제를 수행하는 데 필요한 원자 역량입니다.",
        )
        for task in matched
    ]


def _maximum_experience_months(experience, selected_track) -> int | None:
    if experience.kind is ExperienceKind.RANGE:
        return experience.max_months
    # A mixed new-graduate/experienced posting usually specifies only the
    # experienced-track floor. Do not invent a ceiling that the source did not state.
    return None


def _graph_relations(request, operation_by_capability):
    mapping = {
        CapabilityRelationType.HARD_PREREQUISITE: RoadmapRelationType.HARD_PREREQUISITE,
        CapabilityRelationType.RECOMMENDED_FOUNDATION: RoadmapRelationType.RECOMMENDED_FOUNDATION,
        CapabilityRelationType.CONDITIONAL_PREREQUISITE: (
            RoadmapRelationType.CONDITIONAL_PREREQUISITE
        ),
        CapabilityRelationType.ALTERNATIVE_TO: RoadmapRelationType.ALTERNATIVE_TO,
    }
    relations: list[RoadmapRelation] = []
    for edge in request.capability_graph.edges:
        relation_type = mapping.get(edge.relation_type)
        if relation_type is None:
            continue
        relations.append(RoadmapRelation(
            relation_id=_stable_id("relation-graph", edge.relation_id),
            from_operation_id=operation_by_capability[edge.from_capability_key],
            to_operation_id=operation_by_capability[edge.to_capability_key],
            relation_type=relation_type,
            conditions=edge.conditions,
            reason=edge.reason,
        ))
    return relations


def _add_gates(
    request,
    operations,
    existing_by_target,
    section_key,
    preserved_ids,
    requirement_by_id,
):
    position = next(
        item for item in request.structured_posting.positions
        if item.position_id == request.selected_position_id
    )
    assessment_by_id = {
        item.requirement_id: item for item in request.fit_assessment.requirement_assessments
    }
    gate_ids: list[str] = []
    months = None
    experience = position.experience
    if experience.kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
        months = experience.min_months
    elif (
        experience.kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED
        and request.fit_assessment.selected_experience_track is not None
        and request.fit_assessment.selected_experience_track.value == "EXPERIENCED"
    ):
        months = experience.experienced_min_months
    if months:
        requirement_id = f"req-experience-{position.position_id}"
        status = assessment_by_id.get(requirement_id)
        target_ref = f"gate:{request.opportunity.opportunity_id}:{requirement_id}"
        gate_ids.append(_append_gate(
            operations,
            existing_by_target,
            preserved_ids,
            target_ref=target_ref,
            title=f"관련 직무 경력 {months // 12}년" if months % 12 == 0 else f"관련 직무 경력 {months}개월",
            section_key=section_key,
            gate_spec=GateSpec(
                gate_type=CareerGateType.EXPERIENCE,
                required_months=months,
                maximum_months=(
                    experience.max_months
                    if experience.kind is ExperienceKind.RANGE
                    else None
                ),
                requirement_id=requirement_id,
                evidence_ids=experience.evidence_ids,
                assessment_status=(
                    status.status.value if status else RequirementStatus.UNKNOWN.value
                ),
            ),
            progress=_progress_from_status(status.status if status else RequirementStatus.UNKNOWN),
        ))
    for item in request.normalization.items:
        requirement = requirement_by_id.get(item.requirement_id)
        if (
            item.disposition is RoadmapDisposition.CAREER_GATE
            and requirement is not None
            and requirement.category is RequirementCategory.CREDENTIAL
            and requirement.obligation is RequirementObligation.REQUIRED
        ):
            status = assessment_by_id.get(item.requirement_id)
            target_ref = f"gate:{request.opportunity.opportunity_id}:{item.requirement_id}"
            gate_ids.append(_append_gate(
                operations,
                existing_by_target,
                preserved_ids,
                target_ref=target_ref,
                title=requirement.atomic_text,
                section_key=section_key,
                gate_spec=GateSpec(
                    gate_type=CareerGateType.CREDENTIAL,
                    requirement_id=item.requirement_id,
                    evidence_ids=requirement.evidence_ids,
                    assessment_status=(
                        status.status.value if status else RequirementStatus.UNKNOWN.value
                    ),
                ),
                progress=_progress_from_status(
                    status.status if status else RequirementStatus.UNKNOWN
                ),
            ))
    return gate_ids


def _append_gate(
    operations,
    existing_by_target,
    preserved_ids,
    *,
    target_ref,
    title,
    section_key,
    gate_spec,
    progress,
):
    operation_id = _stable_id("op-gate", target_ref)
    existing = existing_by_target.get((RoadmapNodeKind.CAREER_GATE, target_ref))
    if existing:
        preserved_ids.append(existing.node_id)
        operations.append(_reuse_non_capability(
            operation_id,
            existing,
            target_ref=target_ref,
            reason="Existing formal career gate is reused.",
        ))
    else:
        operations.append(RoadmapOperation(
            operation_id=operation_id,
            action=RoadmapAction.CREATE_GATE,
            node_kind=RoadmapNodeKind.CAREER_GATE,
            target_ref=target_ref,
            title=title,
            section_key=section_key,
            initial_progress_state=progress,
            gate_spec=gate_spec,
            reason="A formal requirement is represented as a gate, not a learning skill.",
        ))
    return operation_id


def _progress_from_status(status: RequirementStatus) -> RoadmapProgressState:
    if status is RequirementStatus.VERIFIED_MET:
        return RoadmapProgressState.VERIFIED
    if status is RequirementStatus.EVIDENCED:
        return RoadmapProgressState.EVIDENCED
    if status is RequirementStatus.CLAIMED_ONLY:
        return RoadmapProgressState.CLAIMED
    return RoadmapProgressState.NOT_STARTED


def _progress_from_competency(competency) -> RoadmapProgressState:
    if competency is None:
        return RoadmapProgressState.NOT_STARTED
    if competency.verification_state is VerificationState.VERIFIED:
        return RoadmapProgressState.VERIFIED
    if (
        competency.verification_state is VerificationState.PARTIALLY_VERIFIED
        or competency.evidence_state is EvidenceState.EVIDENCED
    ):
        return RoadmapProgressState.EVIDENCED
    if competency.claim_state is ClaimState.CLAIMED:
        return RoadmapProgressState.CLAIMED
    return RoadmapProgressState.NOT_STARTED


def _reuse_non_capability(operation_id, existing, *, target_ref, reason):
    return RoadmapOperation(
        operation_id=operation_id,
        action=RoadmapAction.REUSE_NODE,
        node_kind=existing.node_kind,
        existing_node_id=existing.node_id,
        target_ref=target_ref,
        title=existing.title,
        scope_definition=existing.scope_definition,
        section_key=existing.section_key,
        initial_progress_state=existing.progress_state,
        preserve_existing_progress=True,
        reason=reason,
    )


def _relation(from_id, to_id, relation_type, reason):
    return RoadmapRelation(
        relation_id=_stable_id("relation", from_id, to_id, relation_type.value),
        from_operation_id=from_id,
        to_operation_id=to_id,
        relation_type=relation_type,
        reason=reason,
    )


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"
