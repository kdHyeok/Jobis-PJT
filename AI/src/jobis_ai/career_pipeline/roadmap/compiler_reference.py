from __future__ import annotations

import hashlib

from jobis_ai.career_pipeline.contracts.roadmap import (
    CurrentRoadmapSnapshot,
    ExistingRoadmapNode,
    ExistingRoadmapRelation,
    RoadmapAction,
    RoadmapCompilationPreview,
    RoadmapNodeKind,
    RoadmapProgressState,
    RoadmapProposal,
    RoadmapRelationType,
)


class RoadmapCompilationFailure(RuntimeError):
    pass


def compile_preview(
    current: CurrentRoadmapSnapshot,
    proposal: RoadmapProposal,
) -> RoadmapCompilationPreview:
    """Reference behavior for the Spring-owned deterministic graph compiler.

    This function never persists or publishes a roadmap. Phase 8 Spring integration
    must produce the same semantic snapshot under an optimistic version lock.
    """
    if proposal.status.value != "DRAFT":
        raise RoadmapCompilationFailure("only DRAFT proposals can be compiled")
    if proposal.based_on_roadmap_version != current.roadmap_version:
        raise RoadmapCompilationFailure(
            f"stale proposal: expected roadmap version {current.roadmap_version}, "
            f"received {proposal.based_on_roadmap_version}"
        )

    remove_target_refs = set(proposal.remove_target_refs)
    removed_node_ids: list[str] = []
    removed_relation_ids: list[str] = []
    nodes = {}
    for node in current.nodes:
        if (
            remove_target_refs
            and node.node_kind in {
                RoadmapNodeKind.EMPLOYMENT_EVENT,
                RoadmapNodeKind.EXPERIENCE_INTERVAL,
            }
        ) or _should_remove_target_node(node, remove_target_refs):
            removed_node_ids.append(node.node_id)
            continue
        nodes[node.node_id] = node
    operation_nodes: dict[str, str] = {}
    created_node_ids: list[str] = []
    reused_node_ids: list[str] = []

    for operation in proposal.operations:
        if operation.action is RoadmapAction.REUSE_NODE:
            existing = nodes.get(operation.existing_node_id)
            if existing is None:
                raise RoadmapCompilationFailure(
                    f"reused node does not exist: {operation.existing_node_id}"
                )
            _validate_reuse_identity(existing, operation)
            nodes[existing.node_id] = _updated_existing(existing, operation)
            operation_nodes[operation.operation_id] = existing.node_id
            reused_node_ids.append(existing.node_id)
            continue

        node_id = _stable_id("node", operation.operation_id)
        if node_id in nodes:
            raise RoadmapCompilationFailure(f"created node ID already exists: {node_id}")
        nodes[node_id] = ExistingRoadmapNode(
            node_id=node_id,
            node_kind=operation.node_kind,
            title=operation.title,
            canonical_key=operation.canonical_key,
            technology_key=operation.technology_key,
            graph_node_version=operation.graph_node_version,
            verification_methods=operation.verification_methods,
            objective=operation.objective,
            excluded_scope=operation.excluded_scope,
            completion_policy=operation.completion_policy,
            provisional_candidate_id=operation.provisional_candidate_id,
            target_ref=operation.target_ref,
            section_key=operation.section_key,
            section_memberships=operation.section_memberships,
            progress_state=operation.initial_progress_state,
            scope_definition=operation.scope_definition,
            project_spec=operation.project_spec,
            gate_spec=operation.gate_spec,
            opportunity_spec=operation.opportunity_spec,
        )
        operation_nodes[operation.operation_id] = node_id
        created_node_ids.append(node_id)

    # CAREER_STAGE_ORDER used to connect an application opportunity directly to
    # an experience gate. That implied that supporting or completing a company
    # project started employment. Rebuild those legacy display-only edges as
    # explicit employment and experience nodes instead.
    relations = {
        relation.relation_id: relation
        for relation in current.relations
        if relation.relation_type is not RoadmapRelationType.CAREER_STAGE_ORDER
        and relation.from_node_id in nodes
        and relation.to_node_id in nodes
    }
    removed_relation_ids.extend(
        relation.relation_id
        for relation in current.relations
        if relation.relation_id not in relations
    )
    created_relation_ids: list[str] = []
    semantic_relations = {
        (item.from_node_id, item.to_node_id, item.relation_type)
        for item in relations.values()
    }
    for relation in proposal.relations:
        from_node = operation_nodes[relation.from_operation_id]
        to_node = operation_nodes[relation.to_operation_id]
        semantic_key = (from_node, to_node, relation.relation_type)
        if semantic_key in semantic_relations:
            continue
        relation_id = _stable_id(
            "edge",
            from_node,
            to_node,
            relation.relation_type.value,
        )
        relations[relation_id] = ExistingRoadmapRelation(
            relation_id=relation_id,
            from_node_id=from_node,
            to_node_id=to_node,
            relation_type=relation.relation_type,
            conditions=relation.conditions,
            reason=relation.reason,
        )
        semantic_relations.add(semantic_key)
        created_relation_ids.append(relation_id)

    if remove_target_refs:
        orphan_nodes, orphan_relations = _prune_orphan_capabilities(nodes, relations)
        removed_node_ids.extend(orphan_nodes)
        removed_relation_ids.extend(orphan_relations)

    career_nodes, career_relations = _career_graph_members(nodes, relations)
    for node in career_nodes:
        if node.node_id in nodes:
            nodes[node.node_id] = node
            continue
        nodes[node.node_id] = node
        created_node_ids.append(node.node_id)
    for relation in career_relations:
        semantic_key = (
            relation.from_node_id,
            relation.to_node_id,
            relation.relation_type,
        )
        if semantic_key in semantic_relations:
            continue
        relations[relation.relation_id] = relation
        semantic_relations.add(semantic_key)
        created_relation_ids.append(relation.relation_id)

    ranked = _with_display_ranks(nodes, relations)
    next_version = current.roadmap_version + 1
    snapshot = CurrentRoadmapSnapshot(
        roadmap_version=next_version,
        nodes=sorted(
            ranked.values(),
            key=lambda item: (
                item.display_rank,
                item.section_key,
                item.node_kind.value,
                item.title,
                item.node_id,
            ),
        ),
        relations=sorted(relations.values(), key=lambda item: item.relation_id),
    )
    return RoadmapCompilationPreview(
        proposal_id=proposal.proposal_id,
        based_on_roadmap_version=current.roadmap_version,
        proposed_roadmap_version=next_version,
        snapshot=snapshot,
        created_node_ids=sorted(created_node_ids),
        reused_node_ids=sorted(set(reused_node_ids)),
        created_relation_ids=sorted(created_relation_ids),
        removed_node_ids=sorted(set(removed_node_ids)),
        removed_relation_ids=sorted(set(removed_relation_ids)),
    )


def _should_remove_target_node(node, targets: set[str]) -> bool:
    if not targets or node.target_ref is None:
        return False
    return any(
        node.target_ref == target
        or node.target_ref == f"project:{target}"
        or node.target_ref.startswith(f"gate:{target}:")
        for target in targets
    )


def _prune_orphan_capabilities(nodes, relations):
    incoming: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for relation in relations.values():
        incoming[relation.to_node_id].add(relation.from_node_id)
    keep: set[str] = set()
    pending = [
        node.node_id
        for node in nodes.values()
        if node.node_kind is not RoadmapNodeKind.CAPABILITY
    ]
    while pending:
        node_id = pending.pop()
        if node_id in keep:
            continue
        keep.add(node_id)
        pending.extend(incoming.get(node_id, ()))
    removed_nodes = []
    for node in list(nodes.values()):
        if node.node_kind is not RoadmapNodeKind.CAPABILITY:
            continue
        if (
            node.node_id in keep
            or node.progress_state is not RoadmapProgressState.NOT_STARTED
            or node.section_key == "section.common"
        ):
            continue
        removed_nodes.append(node.node_id)
        nodes.pop(node.node_id)
    removed_relations = []
    for relation in list(relations.values()):
        if relation.from_node_id in nodes and relation.to_node_id in nodes:
            continue
        removed_relations.append(relation.relation_id)
        relations.pop(relation.relation_id)
    return removed_nodes, removed_relations


def _validate_reuse_identity(existing, operation) -> None:
    if existing.node_kind is not operation.node_kind:
        raise RoadmapCompilationFailure("reused node kind does not match")
    if existing.node_kind is RoadmapNodeKind.CAPABILITY:
        if (
            existing.canonical_key != operation.canonical_key
            or existing.provisional_candidate_id != operation.provisional_candidate_id
        ):
            raise RoadmapCompilationFailure("reused capability identity does not match")
    elif existing.target_ref != operation.target_ref:
        raise RoadmapCompilationFailure("reused targetRef does not match")


def _updated_existing(existing, operation) -> ExistingRoadmapNode:
    memberships = {
        (item.section_key, item.chapter_key, item.target_ref): item
        for item in existing.section_memberships
    }
    memberships.update({
        (item.section_key, item.chapter_key, item.target_ref): item
        for item in operation.section_memberships
    })
    return existing.model_copy(update={
        "title": operation.title or existing.title,
        "technology_key": operation.technology_key or existing.technology_key,
        "graph_node_version": operation.graph_node_version or existing.graph_node_version,
        "verification_methods": operation.verification_methods or existing.verification_methods,
        "objective": operation.objective or existing.objective,
        "excluded_scope": operation.excluded_scope or existing.excluded_scope,
        "completion_policy": operation.completion_policy or existing.completion_policy,
        "section_key": operation.section_key,
        "section_memberships": list(memberships.values()),
        "scope_definition": operation.scope_definition or existing.scope_definition,
        "progress_state": existing.progress_state,
    })


def _career_graph_members(nodes, relations):
    opportunities = [
        node for node in nodes.values()
        if node.node_kind is RoadmapNodeKind.OPPORTUNITY
        and node.opportunity_spec is not None
        and node.opportunity_spec.minimum_experience_months is not None
    ]
    result_nodes: dict[str, ExistingRoadmapNode] = {}
    result_relations: list[ExistingRoadmapRelation] = []
    for relation in relations.values():
        if relation.relation_type is not RoadmapRelationType.REQUIRES_GATE:
            continue
        gate = nodes[relation.from_node_id]
        target = nodes[relation.to_node_id]
        if (
            gate.gate_spec is None
            or gate.gate_spec.gate_type.value != "EXPERIENCE"
            or target.opportunity_spec is None
        ):
            continue
        target_spec = target.opportunity_spec
        target_months = target_spec.minimum_experience_months
        if target_months is None or target_months <= 0:
            continue
        entry_options = [
            item for item in opportunities
            if item.node_id != target.node_id
            and item.opportunity_spec.role_family == target_spec.role_family
            and item.opportunity_spec.role_specialization == target_spec.role_specialization
            and item.opportunity_spec.minimum_experience_months == 0
        ]
        role_identity = (
            target_spec.canonical_role_id
            or f"{target_spec.role_family}:{target_spec.role_specialization}"
        )
        employment_target = f"employment:{role_identity}"
        employment_id = _stable_id("employment", employment_target)
        entry_ids = sorted(item.node_id for item in entry_options)
        employment = ExistingRoadmapNode(
            node_id=employment_id,
            node_kind=RoadmapNodeKind.EMPLOYMENT_EVENT,
            title=f"관련 {target_spec.role_specialization} 직무 취업",
            target_ref=employment_target,
            section_key=target.section_key,
            progress_state=RoadmapProgressState.NOT_STARTED,
            scope_definition=(
                "지원이나 프로젝트 완료와 구분되는 실제 관련 직무 취업 사건입니다. "
                "근무 증거가 확인되기 전에는 경력이 시작되지 않습니다."
            ),
            employment_spec={
                "roleFamily": target_spec.role_family,
                "roleSpecialization": target_spec.role_specialization,
                "canonicalRoleId": target_spec.canonical_role_id,
                "evidenceState": "UNKNOWN",
                "sourceOpportunityNodeIds": entry_ids,
            },
        )
        existing_employment = nodes.get(employment_id)
        if existing_employment is not None:
            prior_ids = (
                existing_employment.employment_spec or {}
            ).get("sourceOpportunityNodeIds", [])
            employment = employment.model_copy(update={
                "progress_state": existing_employment.progress_state,
                "employment_spec": {
                    **(existing_employment.employment_spec or {}),
                    **employment.employment_spec,
                    "sourceOpportunityNodeIds": sorted(set(prior_ids) | set(entry_ids)),
                },
            })
        result_nodes[employment_id] = employment

        maximum_months = target_spec.maximum_experience_months
        interval_target = (
            f"experience:{role_identity}:{target_months}:"
            f"{maximum_months if maximum_months is not None else 'open'}"
        )
        interval_id = _stable_id("experience", interval_target)
        interval_title = (
            f"관련 실무 경력 {target_months // 12}~{maximum_months // 12}년"
            if maximum_months is not None
            and target_months % 12 == 0
            and maximum_months % 12 == 0
            else (
                f"관련 실무 경력 {target_months // 12}년"
                if target_months % 12 == 0
                else f"관련 실무 경력 {target_months}개월"
            )
        )
        interval = ExistingRoadmapNode(
            node_id=interval_id,
            node_kind=RoadmapNodeKind.EXPERIENCE_INTERVAL,
            title=interval_title,
            target_ref=interval_target,
            section_key=target.section_key,
            progress_state=RoadmapProgressState.NOT_STARTED,
            scope_definition=(
                "실제 관련 직무 취업 뒤 근무 증거로 누적하는 경력 구간입니다. "
                "프로젝트 완료나 지원만으로는 누적되지 않습니다."
            ),
            experience_interval_spec={
                "roleFamily": target_spec.role_family,
                "roleSpecialization": target_spec.role_specialization,
                "canonicalRoleId": target_spec.canonical_role_id,
                "minimumMonths": target_months,
                "maximumMonths": maximum_months,
                "evidenceState": "UNKNOWN",
                "accruedMonths": None,
            },
        )
        existing_interval = nodes.get(interval_id)
        if existing_interval is not None:
            interval = interval.model_copy(update={
                "progress_state": existing_interval.progress_state,
                "experience_interval_spec": {
                    **(existing_interval.experience_interval_spec or {}),
                    **interval.experience_interval_spec,
                    "evidenceState": (
                        existing_interval.experience_interval_spec or {}
                    ).get("evidenceState", "UNKNOWN"),
                    "accruedMonths": (
                        existing_interval.experience_interval_spec or {}
                    ).get("accruedMonths"),
                },
            })
        result_nodes[interval_id] = interval

        for previous in entry_options:
            result_relations.append(ExistingRoadmapRelation(
                relation_id=_stable_id("career-entry", previous.node_id, employment_id),
                from_node_id=previous.node_id,
                to_node_id=employment_id,
                relation_type=RoadmapRelationType.POTENTIAL_CAREER_ENTRY,
                reason=(
                    "This is one possible entry opportunity for related employment; "
                    "the opportunity itself does not prove employment."
                ),
            ))
        result_relations.append(ExistingRoadmapRelation(
            relation_id=_stable_id("experience-start", employment_id, interval_id),
            from_node_id=employment_id,
            to_node_id=interval_id,
            relation_type=RoadmapRelationType.STARTS_EXPERIENCE,
            reason="Verified related employment starts this experience interval.",
        ))
        result_relations.append(ExistingRoadmapRelation(
            relation_id=_stable_id("experience-gate", interval_id, gate.node_id),
            from_node_id=interval_id,
            to_node_id=gate.node_id,
            relation_type=RoadmapRelationType.SATISFIES_EXPERIENCE_GATE,
            reason=(
                "Only verified related work experience can satisfy the formal experience gate."
            ),
        ))
    return list(result_nodes.values()), result_relations


def _with_display_ranks(nodes, relations):
    blocking = {
        RoadmapRelationType.HARD_PREREQUISITE,
        RoadmapRelationType.CONDITIONAL_PREREQUISITE,
        RoadmapRelationType.UNLOCKS_PROJECT,
        RoadmapRelationType.REQUIRES_GATE,
        RoadmapRelationType.UNLOCKS_OPPORTUNITY,
        RoadmapRelationType.CAREER_STAGE_ORDER,
        RoadmapRelationType.POTENTIAL_CAREER_ENTRY,
        RoadmapRelationType.STARTS_EXPERIENCE,
        RoadmapRelationType.SATISFIES_EXPERIENCE_GATE,
    }
    incoming: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for relation in relations.values():
        if relation.relation_type not in blocking:
            continue
        incoming[relation.to_node_id].add(relation.from_node_id)
        outgoing[relation.from_node_id].add(relation.to_node_id)
    ready = sorted(node_id for node_id, values in incoming.items() if not values)
    ranks = {node_id: 0 for node_id in ready}
    visited = 0
    while ready:
        node_id = ready.pop(0)
        visited += 1
        for target in sorted(outgoing[node_id]):
            ranks[target] = max(ranks.get(target, 0), ranks[node_id] + 1)
            incoming[target].discard(node_id)
            if not incoming[target]:
                ready.append(target)
                ready.sort()
    if visited != len(nodes):
        raise RoadmapCompilationFailure("compiled blocking roadmap relations contain a cycle")
    return {
        node_id: node.model_copy(update={"display_rank": ranks.get(node_id, 0)})
        for node_id, node in nodes.items()
    }


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"
