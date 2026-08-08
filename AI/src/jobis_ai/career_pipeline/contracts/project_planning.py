from __future__ import annotations

from pydantic import Field, model_validator

from .capability_graph import CapabilityGraphCatalog, ProjectNecessity
from .common import CanonicalKey, ContractModel, EntityId, NonBlank, WarningItem, ensure_unique
from .posting import StructuredPosting


class PlannedProjectTask(ContractModel):
    task_key: CanonicalKey
    necessity: ProjectNecessity
    title: NonBlank
    objective: NonBlank
    acceptance_criteria: list[NonBlank] = Field(min_length=2, max_length=6)
    capability_keys: list[CanonicalKey] = Field(default_factory=list)
    requirement_ids: list[EntityId] = Field(min_length=1)
    depends_on_task_keys: list[CanonicalKey] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "PlannedProjectTask":
        ensure_unique(self.capability_keys, "planned task capability")
        ensure_unique(self.requirement_ids, "planned task requirement")
        ensure_unique(self.depends_on_task_keys, "planned task dependency")
        if self.task_key in self.depends_on_task_keys:
            raise ValueError("planned project task cannot depend on itself")
        return self


class ProjectPlanningAudit(ContractModel):
    planner_version: NonBlank
    graph_version: NonBlank
    graph_content_hash: NonBlank
    provider: NonBlank
    model: NonBlank
    generation_attempts: int = Field(ge=1)
    generation_duration_ms: int = Field(ge=0)
    generation_effort: NonBlank = "medium"
    generation_effort_history: list[NonBlank] = Field(default_factory=list)
    provider_duration_ms: int | None = Field(default=None, ge=0)
    provider_api_duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)
    provider_session_ids: list[NonBlank] = Field(default_factory=list)


class CompanyProjectBlueprint(ContractModel):
    blueprint_id: EntityId
    common_analysis_id: EntityId
    selected_position_id: EntityId
    title: NonBlank
    objective: NonBlank
    domain_context: NonBlank
    tasks: list[PlannedProjectTask] = Field(default_factory=list, max_length=12)
    unresolved_requirement_ids: list[EntityId] = Field(default_factory=list)
    audit: ProjectPlanningAudit
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_blueprint(self) -> "CompanyProjectBlueprint":
        task_keys = [item.task_key for item in self.tasks]
        ensure_unique(task_keys, "planned project task")
        ensure_unique(self.unresolved_requirement_ids, "unresolved project requirement")
        if not self.tasks and not self.unresolved_requirement_ids:
            raise ValueError("project blueprint requires tasks or unresolved requirements")
        known = set(task_keys)
        necessity_by_key = {item.task_key: item.necessity for item in self.tasks}
        for task in self.tasks:
            unknown = set(task.depends_on_task_keys) - known
            if unknown:
                raise ValueError(
                    f"planned project task depends on unknown tasks: {sorted(unknown)}"
                )
            if task.necessity is ProjectNecessity.REQUIRED:
                extensions = [
                    key for key in task.depends_on_task_keys
                    if necessity_by_key[key] is ProjectNecessity.EXTENSION
                ]
                if extensions:
                    raise ValueError(
                        "required project task cannot depend on extension tasks: "
                        f"{sorted(extensions)}"
                    )
        _ensure_acyclic(self.tasks)
        return self


def _ensure_acyclic(tasks: list[PlannedProjectTask]) -> None:
    dependencies = {task.task_key: set(task.depends_on_task_keys) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_key: str) -> None:
        if task_key in visited:
            return
        if task_key in visiting:
            raise ValueError("planned project task dependencies must form an acyclic graph")
        visiting.add(task_key)
        for dependency in dependencies[task_key]:
            visit(dependency)
        visiting.remove(task_key)
        visited.add(task_key)

    for key in dependencies:
        visit(key)


class ProjectPlanningRequest(ContractModel):
    common_analysis_id: EntityId
    structured_posting: StructuredPosting
    selected_position_id: EntityId
    graph_catalog: CapabilityGraphCatalog

    @model_validator(mode="after")
    def validate_revisions(self) -> "ProjectPlanningRequest":
        if self.selected_position_id not in {
            item.position_id for item in self.structured_posting.positions
        }:
            raise ValueError("selectedPositionId does not exist in structuredPosting")
        return self
