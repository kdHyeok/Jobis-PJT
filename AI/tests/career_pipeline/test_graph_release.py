from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobis_ai.career_pipeline.capability_graph import (
    DEFAULT_ACTIVE_RELEASE_PATH,
    CapabilityGraphContractError,
    GraphReleaseCapabilityGraphPort,
    graph_release_content_hash,
    load_active_graph_release,
    load_graph_release,
)
from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphQueryRequest,
    GraphRelease,
    ProjectNecessity,
)


def release_payload() -> dict:
    release = load_graph_release(DEFAULT_ACTIVE_RELEASE_PATH)
    return release.model_dump(mode="json", by_alias=True)


def test_packaged_v2_release_validates_schema_hash_and_separated_types() -> None:
    release = load_graph_release(DEFAULT_ACTIVE_RELEASE_PATH)

    assert release.schema_version == "jobis.capability-graph.release.v1"
    assert release.graph_version == "0.2.0-alpha.1"
    assert release.content_hash == graph_release_content_hash(release)
    assert len(release.capabilities) == 69
    assert len(release.capability_relations) == 82
    assert len(release.project_tasks) == 12
    assert len(release.task_requirements) == 26
    assert all(not item.canonical_key.startswith("task.") for item in release.capabilities)
    assert all(item.task_key.startswith("task.") for item in release.project_tasks)


def test_approved_release_rejects_unknown_source_and_unapproved_node() -> None:
    unknown_source = release_payload()
    unknown_source["capabilities"][0]["sourceIds"] = ["source-does-not-exist"]
    with pytest.raises(ValidationError, match="unknown source IDs"):
        GraphRelease.model_validate(unknown_source)

    unapproved = release_payload()
    unapproved["capabilities"][0]["reviewStatus"] = "DRAFT"
    with pytest.raises(ValidationError, match="unapproved items"):
        GraphRelease.model_validate(unapproved)


def test_release_rejects_capability_and_project_task_cycles() -> None:
    capability_cycle = release_payload()
    first = capability_cycle["capabilityRelations"][0]
    capability_cycle["capabilityRelations"].append({
        **first,
        "relationId": "rel-test-cycle",
        "fromCapabilityKey": first["toCapabilityKey"],
        "toCapabilityKey": first["fromCapabilityKey"],
    })
    with pytest.raises(ValidationError, match="prerequisite relations contain a cycle"):
        GraphRelease.model_validate(capability_cycle)

    task_cycle = release_payload()
    task_cycle["projectTasks"][0]["dependsOnTaskKeys"] = [
        task_cycle["projectTasks"][1]["taskKey"]
    ]
    with pytest.raises(ValidationError, match="project task dependencies contain a cycle"):
        GraphRelease.model_validate(task_cycle)


def test_release_rejects_conditional_relation_without_condition() -> None:
    payload = release_payload()
    payload["capabilityRelations"][0]["relationType"] = "CONDITIONAL_PREREQUISITE"
    payload["capabilityRelations"][0]["conditions"] = []

    with pytest.raises(ValidationError, match="requires conditions"):
        GraphRelease.model_validate(payload)


def test_release_rejects_unknown_task_requirement_target() -> None:
    payload = release_payload()
    payload["taskRequirements"][0]["capabilityKey"] = "unknown.capability"

    with pytest.raises(ValidationError, match="unknown capability"):
        GraphRelease.model_validate(payload)


def test_in_process_port_rejects_unknown_query_target() -> None:
    port = GraphReleaseCapabilityGraphPort.from_active_release()

    with pytest.raises(CapabilityGraphContractError, match="unknown target"):
        port.get_learning_closure(CapabilityGraphQueryRequest(
            target_capability_keys=["unknown.capability"],
        ))


def test_project_task_query_resolves_dependencies_and_capability_requirements() -> None:
    port = GraphReleaseCapabilityGraphPort.from_active_release()
    closure = port.get_learning_closure(CapabilityGraphQueryRequest(
        project_task_keys=["task.gamepay.delivery-package"],
        project_necessities=[
            ProjectNecessity.REQUIRED,
            ProjectNecessity.RECOMMENDED,
            ProjectNecessity.EXTENSION,
        ],
    ))

    assert closure.resolved_project_task_keys == [
        "task.gamepay.domain-model",
        "task.gamepay.catalog-rest-api",
        "task.gamepay.wallet-topup-ledger",
        "task.gamepay.purchase-atomicity",
        "task.gamepay.duplicate-prevention",
        "task.gamepay.concurrent-purchase",
        "task.gamepay.cancel-refund",
        "task.gamepay.delivery-package",
    ]
    assert "docker.compose-local-stack" in closure.target_capability_keys
    assert "docs.design-verification-evidence" in closure.target_capability_keys
    assert all(not node.canonical_key.startswith("task.") for node in closure.nodes)
    assert any(
        origin.origin_type == "PROJECT_TASK_REQUIREMENT"
        for origin in closure.target_origins
    )


def test_invalid_configured_release_falls_back_to_packaged_last_approved_snapshot(
    tmp_path: Path,
    caplog,
) -> None:
    invalid = tmp_path / "invalid-release.yaml"
    invalid.write_text(yaml.safe_dump({"schema_version": "broken"}), encoding="utf-8")

    loaded = load_active_graph_release(invalid)

    assert loaded.path == DEFAULT_ACTIVE_RELEASE_PATH
    assert loaded.release.graph_version == "0.2.0-alpha.1"
    assert loaded.fallback_reason is not None
    assert "using the packaged last-approved snapshot" in caplog.text
