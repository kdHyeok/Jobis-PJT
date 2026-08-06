from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from jobis_ai_v3.contracts.errors import ErrorCode
from jobis_ai_v3.contracts.normalization import (
    CapabilityCatalogSnapshot,
    CapabilityCandidate,
    CapabilityKind,
    CapabilityNormalizationRequest,
    CapabilityNormalizationResult,
    MatchType,
    NewCapabilityCandidate,
    NormalizationAudit,
    NormalizationDecision,
    RequirementNormalization,
    ReviewStatus,
    RoadmapDisposition,
)
from jobis_ai_v3.contracts.posting import (
    AtomicRequirement,
    RequirementCategory,
    StructuredPosting,
)
from jobis_ai_v3.contracts.project_planning import CompanyProjectBlueprint
from jobis_ai_v3.llm import JsonProviderError, JsonProviderNotConfigured, StructuredGenerator

from .draft import CapabilityNormalizationDraft, RequirementNormalizationDraft


NORMALIZER_VERSION = "capability-normalizer-3.0.0"
PROJECT_NORMALIZER_VERSION = "project-blueprint-normalizer-3.3.0"
MAX_PROMPT_CHARS = 64_000


SYSTEM_PROMPT = """You propose normalization links from atomic job requirements to an open capability catalog.

Rules:
1. Return exactly one item for every supplied requirementId.
2. Use only canonicalKey values present in catalogEntries. Never invent a catalog key.
3. A catalog candidate must cover the requirement's learning scope, not merely share a word.
4. Set partialScope=true when the catalog capability covers only part of the requirement.
5. If the requirement contains two or more independently learnable capabilities, return splitRequired=true.
6. If no catalog entry represents the capability, propose one newCandidate. New technologies must not be dropped or coerced to the nearest known technology.
7. A subtopic such as SQL JOIN should map to an existing parent only when the parent's scopeDefinition explicitly includes it.
8. Never turn attitudes, responsibilities, employment conditions, years of experience, certificates, or a whole project into a technical capability.
9. New-candidate scopeDefinition must say what can be learned or demonstrated and must not copy a whole job-posting sentence.
10. Output only semantic proposals. The service decides review status and never auto-approves your proposal.
"""


class CapabilityNormalizationFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _ExactMatch:
    canonical_key: str
    surface: str
    start: int
    end: int
    canonical_key_exact: bool


class CapabilityNormalizationService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def normalize(self, request: CapabilityNormalizationRequest) -> CapabilityNormalizationResult:
        requirements = _selected_requirements(request)
        catalog = {
            entry.canonical_key: entry
            for entry in request.catalog.entries
            if entry.status.value == "APPROVED"
        }
        compiled: dict[str, RequirementNormalization] = {}
        unresolved: list[AtomicRequirement] = []
        exact_ids: list[str] = []

        for requirement in requirements:
            disposition = _disposition(requirement.category)
            if disposition is not RoadmapDisposition.LEARNING_CAPABILITY:
                compiled[requirement.requirement_id] = _not_applicable(requirement, disposition)
                continue
            matches = _exact_matches(requirement.atomic_text, list(catalog.values()))
            matched_keys = list(dict.fromkeys(item.canonical_key for item in matches))
            if len(matched_keys) == 1 and _is_standalone_exact(requirement.atomic_text, matches):
                item = matches[0]
                selected = matched_keys[0]
                match_type = (
                    MatchType.EXACT_CANONICAL_KEY
                    if any(match.canonical_key_exact for match in matches)
                    else MatchType.EXACT_ALIAS
                )
                compiled[requirement.requirement_id] = RequirementNormalization(
                    requirement_id=requirement.requirement_id,
                    source_category=requirement.category,
                    disposition=disposition,
                    decision=NormalizationDecision.AUTO_SELECTED,
                    selected_canonical_key=selected,
                    candidates=[CapabilityCandidate(
                        canonical_key=selected,
                        match_type=match_type,
                        confidence=1.0,
                        reason=f"Approved catalog surface '{item.surface}' appears as an exact bounded term.",
                    )],
                    review_status=ReviewStatus.NOT_REQUIRED,
                    evidence_ids=requirement.evidence_ids,
                    reason="A unique approved catalog alias matched deterministically.",
                )
                exact_ids.append(requirement.requirement_id)
            elif len(matched_keys) > 1 and _has_independent_matches(matches):
                compiled[requirement.requirement_id] = RequirementNormalization(
                    requirement_id=requirement.requirement_id,
                    source_category=requirement.category,
                    disposition=disposition,
                    decision=NormalizationDecision.SPLIT_REQUIRED,
                    candidates=[
                        CapabilityCandidate(
                            canonical_key=key,
                            match_type=MatchType.EXACT_ALIAS,
                            confidence=1.0,
                            reason="A distinct approved alias appears in the same atomic requirement.",
                        )
                        for key in matched_keys
                    ],
                    review_status=ReviewStatus.SOURCE_RESTRUCTURE_REQUIRED,
                    evidence_ids=requirement.evidence_ids,
                    reason="The atomic requirement still contains multiple independent capabilities.",
                )
                exact_ids.append(requirement.requirement_id)
            elif len(matched_keys) > 1:
                compiled[requirement.requirement_id] = RequirementNormalization(
                    requirement_id=requirement.requirement_id,
                    source_category=requirement.category,
                    disposition=disposition,
                    decision=NormalizationDecision.CANDIDATES_PROPOSED,
                    candidates=[
                        CapabilityCandidate(
                            canonical_key=key,
                            match_type=MatchType.EXACT_ALIAS,
                            confidence=1.0,
                            reason="The same exact alias is shared by multiple catalog entries.",
                        )
                        for key in matched_keys
                    ],
                    review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
                    evidence_ids=requirement.evidence_ids,
                    reason="The exact alias is ambiguous across approved catalog entries.",
                )
                exact_ids.append(requirement.requirement_id)
            else:
                unresolved.append(requirement)

        metadata = None
        if unresolved:
            prompt = _build_prompt(unresolved, list(catalog.values()))
            try:
                draft, metadata = self._generator.generate(
                    CapabilityNormalizationDraft,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                )
            except JsonProviderNotConfigured as exc:
                raise CapabilityNormalizationFailure(
                    code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                    message=str(exc),
                    retryable=False,
                ) from exc
            except JsonProviderError as exc:
                timed_out = "timed out" in str(exc).casefold() or "timeout" in str(exc).casefold()
                raise CapabilityNormalizationFailure(
                    code=ErrorCode.AI_TIMEOUT if timed_out else ErrorCode.AI_PROVIDER_UNAVAILABLE,
                    message=str(exc),
                    retryable=True,
                ) from exc
            try:
                proposals = _validated_draft(draft, unresolved, set(catalog))
                for requirement in unresolved:
                    compiled[requirement.requirement_id] = _compile_proposal(
                        requirement,
                        proposals[requirement.requirement_id],
                    )
            except ValueError as exc:
                raise CapabilityNormalizationFailure(
                    code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                    message=str(exc),
                    retryable=False,
                ) from exc

        ordered = [compiled[requirement.requirement_id] for requirement in requirements]
        normalization_id = _stable_id(
            "normalization",
            request.common_analysis_id,
            request.selected_position_id,
            request.catalog.catalog_version,
            *[
                f"{item.requirement_id}:{item.decision.value}:"
                f"{item.selected_canonical_key or '-'}"
                for item in ordered
            ],
        )
        return CapabilityNormalizationResult(
            normalization_id=normalization_id,
            common_analysis_id=request.common_analysis_id,
            selected_position_id=request.selected_position_id,
            catalog_version=request.catalog.catalog_version,
            items=ordered,
            audit=NormalizationAudit(
                normalizer_version=NORMALIZER_VERSION,
                catalog_version=request.catalog.catalog_version,
                provider=metadata.provider if metadata else None,
                model=metadata.model if metadata else None,
                generation_attempts=metadata.attempts if metadata else None,
                generation_duration_ms=metadata.duration_ms if metadata else None,
                exact_match_requirement_ids=exact_ids,
                ai_match_requirement_ids=[item.requirement_id for item in unresolved],
            ),
        )


def compile_project_normalization(
    *,
    common_analysis_id: str,
    structured_posting: StructuredPosting,
    selected_position_id: str,
    catalog: CapabilityCatalogSnapshot,
    blueprint: CompanyProjectBlueprint,
) -> CapabilityNormalizationResult:
    """Compile requirement traceability from an already validated project blueprint.

    The project planner has already selected approved atomic capability keys for
    concrete tasks. Re-running a second semantic matcher over the entire posting
    and catalog is both redundant and capable of contradicting the project. This
    compiler therefore records those task links deterministically while keeping
    career gates and non-learning requirements outside the skill graph.
    """
    if blueprint.common_analysis_id != common_analysis_id:
        raise ValueError("project blueprint belongs to a different commonAnalysisId")
    if blueprint.selected_position_id != selected_position_id:
        raise ValueError("project blueprint belongs to a different selectedPositionId")

    approved_keys = {
        item.canonical_key
        for item in catalog.entries
        if item.status.value == "APPROVED"
    }
    keys_by_requirement: dict[str, set[str]] = {}
    for task in blueprint.tasks:
        unknown = set(task.capability_keys) - approved_keys
        if unknown:
            raise ValueError(
                f"project blueprint refers to unknown approved capabilities: {sorted(unknown)}"
            )
        for requirement_id in task.requirement_ids:
            keys_by_requirement.setdefault(requirement_id, set()).update(task.capability_keys)

    requirements = _requirements_for_position(structured_posting, selected_position_id)
    items: list[RequirementNormalization] = []
    project_linked_ids: list[str] = []
    for requirement in requirements:
        disposition = _disposition(requirement.category)
        if disposition is not RoadmapDisposition.LEARNING_CAPABILITY:
            items.append(_not_applicable(requirement, disposition))
            continue

        keys = sorted(keys_by_requirement.get(requirement.requirement_id, set()))
        if len(keys) == 1:
            key = keys[0]
            items.append(RequirementNormalization(
                requirement_id=requirement.requirement_id,
                source_category=requirement.category,
                disposition=disposition,
                decision=NormalizationDecision.AUTO_SELECTED,
                selected_canonical_key=key,
                candidates=[CapabilityCandidate(
                    canonical_key=key,
                    match_type=MatchType.AI_DIRECT_SCOPE,
                    confidence=1.0,
                    reason="The approved capability is demonstrated by a validated project task.",
                )],
                review_status=ReviewStatus.NOT_REQUIRED,
                evidence_ids=requirement.evidence_ids,
                reason="The company-target project supplies the concrete learning context.",
            ))
            project_linked_ids.append(requirement.requirement_id)
        elif len(keys) > 1:
            items.append(RequirementNormalization(
                requirement_id=requirement.requirement_id,
                source_category=requirement.category,
                disposition=disposition,
                decision=NormalizationDecision.SPLIT_REQUIRED,
                candidates=[
                    CapabilityCandidate(
                        canonical_key=key,
                        match_type=MatchType.AI_DIRECT_SCOPE,
                        confidence=1.0,
                        reason="The validated project task demonstrates this atomic capability.",
                    )
                    for key in keys
                ],
                review_status=ReviewStatus.SOURCE_RESTRUCTURE_REQUIRED,
                evidence_ids=requirement.evidence_ids,
                reason=(
                    "The broad posting requirement is represented by multiple atomic "
                    "capabilities in the company-target project."
                ),
            ))
            project_linked_ids.append(requirement.requirement_id)
        else:
            items.append(RequirementNormalization(
                requirement_id=requirement.requirement_id,
                source_category=requirement.category,
                disposition=disposition,
                decision=NormalizationDecision.NEW_CANDIDATE_PROPOSED,
                new_candidate=_project_provisional_candidate(requirement),
                review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
                evidence_ids=requirement.evidence_ids,
                reason=(
                    "No approved atomic capability safely covers this verified learning "
                    "requirement. It is preserved as a user-scoped candidate until catalog "
                    "review instead of being removed from the roadmap."
                ),
            ))
            project_linked_ids.append(requirement.requirement_id)

    normalization_id = _stable_id(
        "normalization",
        common_analysis_id,
        selected_position_id,
        catalog.catalog_version,
        blueprint.blueprint_id,
        *[
            f"{item.requirement_id}:{item.decision.value}:"
            f"{item.selected_canonical_key or '-'}"
            for item in items
        ],
    )
    return CapabilityNormalizationResult(
        normalization_id=normalization_id,
        common_analysis_id=common_analysis_id,
        selected_position_id=selected_position_id,
        catalog_version=catalog.catalog_version,
        items=items,
        audit=NormalizationAudit(
            normalizer_version=PROJECT_NORMALIZER_VERSION,
            catalog_version=catalog.catalog_version,
            exact_match_requirement_ids=[],
            ai_match_requirement_ids=project_linked_ids,
        ),
    )


def _project_provisional_candidate(
    requirement: AtomicRequirement,
) -> NewCapabilityCandidate:
    """Preserve a verified learning scope without pretending it is public taxonomy.

    The project planner is allowed to report that the approved graph has no safe
    match. That absence must not erase the requirement. The atomic requirement is
    already backed by verified source evidence, so it is safe to retain its exact
    scope as a user-local review candidate. Kind refinement and aliases remain an
    operator decision.
    """
    proposed_kind = {
        RequirementCategory.TECHNICAL_CAPABILITY: CapabilityKind.TECHNICAL_CAPABILITY,
        RequirementCategory.DOMAIN_KNOWLEDGE: CapabilityKind.DOMAIN_KNOWLEDGE,
        RequirementCategory.TECHNOLOGY: CapabilityKind.OTHER,
    }.get(requirement.category, CapabilityKind.OTHER)
    display_name = re.sub(r"\s+", " ", requirement.atomic_text).strip()
    return NewCapabilityCandidate(
        candidate_id=_stable_id(
            "capability-candidate",
            requirement.requirement_id,
            display_name,
            requirement.category.value,
        ),
        display_name=display_name,
        proposed_kind=proposed_kind,
        scope_definition=(
            "공고에서 확인된 다음 수행 범위를 학습하고 결과물로 입증한다: "
            f"{display_name}"
        ),
        aliases=[],
        evidence_ids=requirement.evidence_ids,
        confidence=0.65,
    )


def _selected_requirements(request: CapabilityNormalizationRequest) -> list[AtomicRequirement]:
    return _requirements_for_position(
        request.structured_posting,
        request.selected_position_id,
    )


def _requirements_for_position(
    structured_posting: StructuredPosting,
    selected_position_id: str,
) -> list[AtomicRequirement]:
    position = next(
        item
        for item in structured_posting.positions
        if item.position_id == selected_position_id
    )
    return [
        *position.requirements,
        *[
            item
            for item in structured_posting.shared_conditions
            if selected_position_id in item.applies_to_position_ids
        ],
    ]


def _disposition(category: RequirementCategory) -> RoadmapDisposition:
    return {
        RequirementCategory.TECHNOLOGY: RoadmapDisposition.LEARNING_CAPABILITY,
        RequirementCategory.TECHNICAL_CAPABILITY: RoadmapDisposition.LEARNING_CAPABILITY,
        RequirementCategory.DOMAIN_KNOWLEDGE: RoadmapDisposition.LEARNING_CAPABILITY,
        RequirementCategory.RESPONSIBILITY: RoadmapDisposition.PROJECT_CONTEXT,
        RequirementCategory.PORTFOLIO: RoadmapDisposition.PROJECT_CONTEXT,
        RequirementCategory.CREDENTIAL: RoadmapDisposition.CAREER_GATE,
        RequirementCategory.EXPERIENCE: RoadmapDisposition.CAREER_GATE,
        RequirementCategory.BEHAVIORAL: RoadmapDisposition.FIT_ONLY,
        RequirementCategory.EMPLOYMENT_CONDITION: RoadmapDisposition.EMPLOYMENT_INFORMATION,
        RequirementCategory.OTHER: RoadmapDisposition.REVIEW_REQUIRED,
    }[category]


def _not_applicable(
    requirement: AtomicRequirement,
    disposition: RoadmapDisposition,
) -> RequirementNormalization:
    explanations = {
        RoadmapDisposition.PROJECT_CONTEXT: "This item belongs to the later company-target project brief.",
        RoadmapDisposition.CAREER_GATE: "This item is a formal career gate, not a learnable capability node.",
        RoadmapDisposition.FIT_ONLY: "This behavioral item is evaluated in fit analysis, not added as a skill node.",
        RoadmapDisposition.EMPLOYMENT_INFORMATION: "This employment condition is display information, not a skill.",
        RoadmapDisposition.REVIEW_REQUIRED: "The source category is not safe to normalize without operator review.",
    }
    if disposition is RoadmapDisposition.REVIEW_REQUIRED:
        return RequirementNormalization(
            requirement_id=requirement.requirement_id,
            source_category=requirement.category,
            disposition=disposition,
            decision=NormalizationDecision.UNRESOLVED,
            review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
            evidence_ids=requirement.evidence_ids,
            reason=explanations[disposition],
        )
    return RequirementNormalization(
        requirement_id=requirement.requirement_id,
        source_category=requirement.category,
        disposition=disposition,
        decision=NormalizationDecision.NOT_APPLICABLE,
        review_status=ReviewStatus.NOT_REQUIRED,
        evidence_ids=requirement.evidence_ids,
        reason=explanations[disposition],
    )


def _exact_matches(text: str, entries: list) -> list[_ExactMatch]:
    matches: list[_ExactMatch] = []
    folded = text.casefold()
    for entry in entries:
        surfaces = [entry.canonical_key, entry.display_name, *entry.aliases]
        seen_surfaces: set[str] = set()
        for surface in surfaces:
            normalized = re.sub(r"\s+", " ", surface.strip()).casefold()
            if not normalized or normalized in seen_surfaces:
                continue
            seen_surfaces.add(normalized)
            pattern = _bounded_pattern(normalized)
            for found in re.finditer(pattern, folded, flags=re.IGNORECASE):
                matches.append(_ExactMatch(
                    canonical_key=entry.canonical_key,
                    surface=surface,
                    start=found.start(),
                    end=found.end(),
                    canonical_key_exact=(normalized == entry.canonical_key.casefold()),
                ))

    retained = [
        match
        for match in matches
        if not any(
            other.canonical_key != match.canonical_key
            and other.start <= match.start
            and other.end >= match.end
            and (other.end - other.start) > (match.end - match.start)
            for other in matches
        )
    ]
    return sorted(retained, key=lambda item: (item.start, -(item.end - item.start), item.canonical_key))


def _bounded_pattern(surface: str) -> str:
    escaped = re.escape(surface).replace(r"\ ", r"\s+")
    identifier = r"A-Za-z0-9_+#.\-"
    return rf"(?<![{identifier}]){escaped}(?![{identifier}])"


def _has_independent_matches(matches: list[_ExactMatch]) -> bool:
    keys = {item.canonical_key for item in matches}
    if len(keys) < 2:
        return False
    return any(
        first.canonical_key != second.canonical_key
        and (first.end <= second.start or second.end <= first.start)
        for first in matches
        for second in matches
    )


def _is_standalone_exact(text: str, matches: list[_ExactMatch]) -> bool:
    normalized_text = re.sub(r"\s+", " ", text.strip()).casefold()
    return any(
        normalized_text == re.sub(r"\s+", " ", item.surface.strip()).casefold()
        for item in matches
    )


def _build_prompt(requirements: list[AtomicRequirement], entries: list) -> str:
    payload = {
        "requirements": [
            {
                "requirementId": item.requirement_id,
                "text": item.atomic_text,
                "category": item.category.value,
                "evidenceIds": item.evidence_ids,
            }
            for item in requirements
        ],
        "catalogEntries": [
            {
                "canonicalKey": item.canonical_key,
                "displayName": item.display_name,
                "kind": item.kind.value,
                "scopeDefinition": item.scope_definition,
                "aliases": item.aliases,
            }
            for item in entries
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_PROMPT_CHARS:
        raise CapabilityNormalizationFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message=(
                f"normalization input is {len(encoded)} characters; "
                "the catalog search adapter must provide a smaller candidate slice"
            ),
            retryable=False,
        )
    return encoded


def _validated_draft(
    draft: CapabilityNormalizationDraft,
    requirements: list[AtomicRequirement],
    catalog_keys: set[str],
) -> dict[str, RequirementNormalizationDraft]:
    expected = {item.requirement_id for item in requirements}
    actual = {item.requirement_id for item in draft.items}
    if actual != expected:
        raise ValueError(
            "normalizer must return exactly the requested requirements; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    unknown = {
        candidate.canonical_key
        for item in draft.items
        for candidate in item.candidates
        if candidate.canonical_key not in catalog_keys
    }
    if unknown:
        raise ValueError(f"normalizer proposed unknown catalog keys: {sorted(unknown)}")
    return {item.requirement_id: item for item in draft.items}


def _compile_proposal(
    requirement: AtomicRequirement,
    draft: RequirementNormalizationDraft,
) -> RequirementNormalization:
    disposition = _disposition(requirement.category)
    if draft.split_required:
        return RequirementNormalization(
            requirement_id=requirement.requirement_id,
            source_category=requirement.category,
            disposition=disposition,
            decision=NormalizationDecision.SPLIT_REQUIRED,
            review_status=ReviewStatus.SOURCE_RESTRUCTURE_REQUIRED,
            evidence_ids=requirement.evidence_ids,
            reason=draft.reason,
        )
    if draft.candidates:
        return RequirementNormalization(
            requirement_id=requirement.requirement_id,
            source_category=requirement.category,
            disposition=disposition,
            decision=NormalizationDecision.CANDIDATES_PROPOSED,
            candidates=[
                CapabilityCandidate(
                    canonical_key=item.canonical_key,
                    match_type=(
                        MatchType.AI_PARTIAL_SCOPE
                        if item.partial_scope
                        else MatchType.AI_DIRECT_SCOPE
                    ),
                    confidence=item.confidence,
                    reason=item.reason,
                )
                for item in draft.candidates
            ],
            review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
            evidence_ids=requirement.evidence_ids,
            reason=draft.reason,
        )
    if draft.new_candidate is not None:
        item = draft.new_candidate
        return RequirementNormalization(
            requirement_id=requirement.requirement_id,
            source_category=requirement.category,
            disposition=disposition,
            decision=NormalizationDecision.NEW_CANDIDATE_PROPOSED,
            new_candidate=NewCapabilityCandidate(
                candidate_id=_stable_id(
                    "capability-candidate",
                    requirement.requirement_id,
                    item.display_name,
                    item.scope_definition,
                ),
                display_name=item.display_name,
                proposed_kind=item.proposed_kind,
                scope_definition=item.scope_definition,
                aliases=item.aliases,
                evidence_ids=requirement.evidence_ids,
                confidence=item.confidence,
            ),
            review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
            evidence_ids=requirement.evidence_ids,
            reason=draft.reason,
        )
    return RequirementNormalization(
        requirement_id=requirement.requirement_id,
        source_category=requirement.category,
        disposition=disposition,
        decision=NormalizationDecision.UNRESOLVED,
        review_status=ReviewStatus.OPERATOR_REVIEW_REQUIRED,
        evidence_ids=requirement.evidence_ids,
        reason=draft.reason,
    )


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"
