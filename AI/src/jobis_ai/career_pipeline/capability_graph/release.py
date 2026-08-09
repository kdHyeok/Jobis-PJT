from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphQueryRequest,
    CapabilityRelationType,
    GraphRelease,
    GraphReleaseStatus,
    GraphWarning,
    LearningLayer,
    TargetOrigin,
    TaskRequirement,
)

from .port import (
    CapabilityGraphContractError,
    closure_content_hash,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_ACTIVE_RELEASE_PATH = (
    Path(__file__).with_name("releases") / "graph-release.v0.2.0-alpha.1.yaml"
)
ACTIVE_RELEASE_ENV = "JOBIS_GRAPH_RELEASE_PATH"


@dataclass(frozen=True)
class LoadedGraphRelease:
    release: GraphRelease
    path: Path
    fallback_reason: str | None = None


def graph_release_content_hash(release: GraphRelease) -> str:
    payload = release.model_dump(
        mode="json",
        by_alias=True,
        exclude={"content_hash"},
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_graph_release(path: Path) -> GraphRelease:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        release = GraphRelease.model_validate(raw)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise CapabilityGraphContractError(
            f"invalid graph release {path}: {exc}"
        ) from exc
    if release.release_status is not GraphReleaseStatus.APPROVED:
        raise CapabilityGraphContractError(
            f"graph release {path} is not approved: {release.release_status.value}"
        )
    expected = graph_release_content_hash(release)
    if release.content_hash != expected:
        raise CapabilityGraphContractError(
            f"graph release content hash mismatch for {path}: expected {expected}"
        )
    return release


def load_active_graph_release(
    configured_path: str | Path | None = None,
) -> LoadedGraphRelease:
    configured = configured_path or os.getenv(ACTIVE_RELEASE_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        try:
            return LoadedGraphRelease(release=load_graph_release(path), path=path)
        except CapabilityGraphContractError as exc:
            fallback_reason = str(exc)
            LOGGER.warning(
                "Configured capability graph release failed validation; using the "
                "packaged last-approved snapshot. reason=%s",
                fallback_reason,
            )
            return LoadedGraphRelease(
                release=load_graph_release(DEFAULT_ACTIVE_RELEASE_PATH),
                path=DEFAULT_ACTIVE_RELEASE_PATH,
                fallback_reason=fallback_reason,
            )
    return LoadedGraphRelease(
        release=load_graph_release(DEFAULT_ACTIVE_RELEASE_PATH),
        path=DEFAULT_ACTIVE_RELEASE_PATH,
    )


class GraphReleaseCapabilityGraphPort:
    """Deterministic in-process graph adapter backed by an approved release."""

    def __init__(self, loaded: LoadedGraphRelease) -> None:
        self.loaded = loaded
        self.release = loaded.release
        self._capability_by_key = {
            item.canonical_key: item for item in self.release.capabilities
        }
        self._task_by_key = {
            item.task_key: item for item in self.release.project_tasks
        }
        self._catalog = self._build_catalog()

    @classmethod
    def from_active_release(
        cls,
        configured_path: str | Path | None = None,
    ) -> "GraphReleaseCapabilityGraphPort":
        return cls(load_active_graph_release(configured_path))

    @property
    def graph_version(self) -> str:
        return self.release.graph_version

    @property
    def fallback_reason(self) -> str | None:
        return self.loaded.fallback_reason

    def get_catalog(self) -> CapabilityGraphCatalog:
        return self._catalog

    def get_learning_closure(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure:
        if (
            request.requested_graph_version is not None
            and request.requested_graph_version != self.release.graph_version
        ):
            raise CapabilityGraphContractError(
                f"requested graph version {request.requested_graph_version}, "
                f"active version is {self.release.graph_version}"
            )

        unknown_capabilities = sorted(
            set(request.target_capability_keys) - set(self._capability_by_key)
        )
        if unknown_capabilities:
            raise CapabilityGraphContractError(
                f"unknown target capabilities: {unknown_capabilities}"
            )
        unknown_tasks = sorted(set(request.project_task_keys) - set(self._task_by_key))
        if unknown_tasks:
            raise CapabilityGraphContractError(
                f"unknown project tasks: {unknown_tasks}"
            )

        resolved_tasks = self._resolve_project_tasks(request.project_task_keys)
        selected_requirements = [
            item
            for item in self.release.task_requirements
            if item.task_key in resolved_tasks
            and item.necessity in request.project_necessities
        ]
        requirement_targets = [item.capability_key for item in selected_requirements]
        targets = _ordered_unique(
            [*request.target_capability_keys, *requirement_targets]
        )

        warnings: list[GraphWarning] = []
        boundary: list[str] = []
        for key in request.boundary_capability_keys:
            if key in self._capability_by_key:
                boundary.append(key)
            else:
                warnings.append(GraphWarning(
                    code="UNKNOWN_BOUNDARY_CAPABILITY",
                    message=(
                        f"boundary capability {key} is not in graph "
                        f"{self.release.graph_version}"
                    ),
                ))
        boundary_set = set(boundary)

        active = {
            (condition.kind, condition.key): condition.value
            for condition in request.active_conditions
        }
        allowed_types = set(request.include_relation_types)
        allowed_types.add(CapabilityRelationType.CONDITIONAL_PREREQUISITE)

        def edge_applies(edge: CapabilityGraphEdge) -> bool:
            if edge.relation_type not in allowed_types:
                return False
            return all(
                active.get((condition.kind, condition.key))
                in condition.accepted_values
                for condition in edge.conditions
            )

        applicable_edges = [
            edge
            for edge in self.release.capability_relations
            if edge_applies(edge)
        ]
        prerequisites_of: dict[str, list[CapabilityGraphEdge]] = {}
        for edge in applicable_edges:
            prerequisites_of.setdefault(edge.to_capability_key, []).append(edge)

        included: set[str] = set(targets) | boundary_set
        frontier = list(targets)
        depth = 0
        while frontier and depth < request.max_depth:
            next_frontier: list[str] = []
            for key in frontier:
                if key in boundary_set:
                    continue
                for edge in prerequisites_of.get(key, []):
                    prerequisite = edge.from_capability_key
                    if prerequisite not in included:
                        included.add(prerequisite)
                        next_frontier.append(prerequisite)
            frontier = next_frontier
            depth += 1

        nodes = [
            node
            for node in self.release.capabilities
            if node.canonical_key in included
        ]
        edges = [
            edge
            for edge in applicable_edges
            if edge.from_capability_key in included
            and edge.to_capability_key in included
        ]
        source_ids = {source_id for node in nodes for source_id in node.source_ids}
        source_ids |= {source_id for edge in edges for source_id in edge.source_ids}
        source_ids |= {
            source_id
            for task in self.release.project_tasks
            if task.task_key in resolved_tasks
            for source_id in task.source_ids
        }
        source_ids |= {
            source_id
            for requirement in selected_requirements
            for source_id in requirement.source_ids
        }
        sources = [
            source for source in self.release.sources
            if source.source_id in source_ids
        ]

        closure = CapabilityGraphClosure(
            graph_version=self.release.graph_version,
            generated_at=datetime.now(UTC),
            content_hash="sha256:" + "0" * 64,
            target_capability_keys=targets,
            resolved_project_task_keys=resolved_tasks,
            boundary_capability_keys=boundary,
            target_origins=self._target_origins(
                request.target_capability_keys,
                selected_requirements,
            ),
            nodes=nodes,
            edges=edges,
            sources=sources,
            learning_order=self._learning_order(included - boundary_set, edges),
            warnings=warnings,
        )
        return closure.model_copy(update={"content_hash": closure_content_hash(closure)})

    def _build_catalog(self) -> CapabilityGraphCatalog:
        catalog = CapabilityGraphCatalog(
            graph_version=self.release.graph_version,
            content_hash="sha256:" + "0" * 64,
            capabilities=self.release.capabilities,
        )
        payload = catalog.model_dump(
            mode="json",
            by_alias=True,
            exclude={"content_hash"},
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return catalog.model_copy(update={
            "content_hash": "sha256:" + hashlib.sha256(encoded).hexdigest()
        })

    def _resolve_project_tasks(self, requested: list[str]) -> list[str]:
        resolved: set[str] = set()

        def add(task_key: str) -> None:
            if task_key in resolved:
                return
            for dependency in self._task_by_key[task_key].depends_on_task_keys:
                add(dependency)
            resolved.add(task_key)

        for key in requested:
            add(key)
        return [
            task.task_key
            for task in self.release.project_tasks
            if task.task_key in resolved
        ]

    def _target_origins(
        self,
        direct_targets: list[str],
        requirements: list[TaskRequirement],
    ) -> list[TargetOrigin]:
        origins = [
            TargetOrigin(
                capability_key=key,
                origin_type="DIRECT_CAPABILITY",
            )
            for key in direct_targets
        ]
        by_capability: dict[str, list[TaskRequirement]] = {}
        for requirement in requirements:
            by_capability.setdefault(requirement.capability_key, []).append(requirement)
        origins.extend(
            TargetOrigin(
                capability_key=capability_key,
                origin_type="PROJECT_TASK_REQUIREMENT",
                project_task_keys=_ordered_unique([
                    item.task_key for item in items
                ]),
                necessities=_ordered_unique([
                    item.necessity for item in items
                ]),
            )
            for capability_key, items in by_capability.items()
        )
        return origins

    def _learning_order(
        self,
        keys: set[str],
        edges: list[CapabilityGraphEdge],
    ) -> list[LearningLayer]:
        depth_of: dict[str, int] = {}

        def resolve(key: str) -> int:
            if key in depth_of:
                return depth_of[key]
            depths = [
                resolve(edge.from_capability_key) + 1
                for edge in edges
                if edge.to_capability_key == key
                and edge.from_capability_key in keys
            ]
            depth_of[key] = max(depths, default=0)
            return depth_of[key]

        for key in keys:
            resolve(key)
        layers: dict[int, list[str]] = {}
        for key, depth in depth_of.items():
            layers.setdefault(depth, []).append(key)
        return [
            LearningLayer(depth=depth, capability_keys=sorted(layers[depth]))
            for depth in sorted(layers)
        ]


def _ordered_unique(values: list) -> list:
    return list(dict.fromkeys(values))
