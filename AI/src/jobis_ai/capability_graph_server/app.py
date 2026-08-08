"""읽기 전용 Capability Graph HTTP 서버 — 판단 계층(결정론, LLM 없음).

기동: python -m uvicorn jobis_ai.capability_graph_server.app:app --port 8600

계약(jobis.capability-graph.v1alpha1)은 career_pipeline 의 클라이언트(port.py)가 소비하는
형태 그대로다: GET /health, GET /v1/capabilities, POST /v1/graph/prerequisites.
/v1/* 는 X-JOBIS-GRAPH-SECRET 헤더가 JOBIS_GRAPH_SHARED_SECRET 과 일치해야 한다.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jobis_ai.career_pipeline.capability_graph.port import closure_content_hash
from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphNode,
    CapabilityGraphQueryRequest,
    CapabilityRelationType,
    GraphSource,
    GraphWarning,
    LearningLayer,
)

CONTRACT_VERSION = "jobis.capability-graph.v1alpha1"
DEFAULT_DATASET = Path(__file__).with_name("seed.v1.yaml")

_SEED_CONFIDENCE = {
    "band": "STRONG_INFERENCE",
    "reason": "로컬 시드 그래프 큐레이션 — 연결된 공식 문서의 학습 경로에서 도출했다.",
}
NODE_DEFAULTS = {
    "node_type": "PERFORMANCE",
    "verification_methods": ["IMPLEMENT"],
    "review_status": "APPROVED",
    "version": 1,
    "confidence": _SEED_CONFIDENCE,
}
EDGE_DEFAULTS = {
    "relation_type": "HARD_PREREQUISITE",
    "review_status": "APPROVED",
    "version": 1,
    "confidence": _SEED_CONFIDENCE,
}


class GraphDataset:
    def __init__(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.graph_version: str = raw["graph_version"]
        self.sources = [self._source(item) for item in raw["sources"]]
        source_ids = {item.source_id for item in self.sources}
        self.nodes = [
            CapabilityGraphNode.model_validate({**NODE_DEFAULTS, **item})
            for item in raw["nodes"]
        ]
        self.edges = [
            CapabilityGraphEdge.model_validate({**EDGE_DEFAULTS, **item})
            for item in raw["edges"]
        ]
        self.node_by_key = {node.canonical_key: node for node in self.nodes}
        # 전체 데이터셋 자체도 닫힌 계약이어야 한다 — 기동 시점에 한 번 전부 검증한다.
        CapabilityGraphClosure.model_validate(self._full_closure_payload())
        for node in self.nodes:
            missing = set(node.source_ids) - source_ids
            if missing:
                raise ValueError(f"node {node.canonical_key} has unknown sources {missing}")
        self.catalog = self._build_catalog()

    def _source(self, item: dict) -> GraphSource:
        # LINK_ONLY 스냅샷은 링크 문자열 자체의 해시를 기록한다 — 본문을 저장하지 않았음을
        # 정직하게 드러내는 값이다.
        if "content_hash" not in item:
            digest = hashlib.sha256(item["uri"].encode("utf-8")).hexdigest()
            item = {**item, "content_hash": f"sha256:{digest}", "snapshot_scope": "LINK_ONLY"}
        return GraphSource.model_validate(item)

    def _full_closure_payload(self) -> dict:
        placeholder = CapabilityGraphClosure.model_construct(
            graph_version=self.graph_version,
            generated_at=datetime.now(UTC),
            content_hash="sha256:" + "0" * 64,
            target_capability_keys=[],
            boundary_capability_keys=[],
            nodes=self.nodes,
            edges=self.edges,
            sources=self.sources,
            learning_order=[],
        )
        payload = placeholder.model_dump(mode="json", by_alias=True)
        return payload

    def _build_catalog(self) -> CapabilityGraphCatalog:
        catalog = CapabilityGraphCatalog(
            graph_version=self.graph_version,
            content_hash="sha256:" + "0" * 64,
            capabilities=self.nodes,
        )
        payload = catalog.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return catalog.model_copy(update={"content_hash": f"sha256:{digest}"})

    def prerequisites(self, request: CapabilityGraphQueryRequest) -> CapabilityGraphClosure:
        targets = [*request.target_capability_keys, *request.project_task_keys]
        unknown_targets = [key for key in targets if key not in self.node_by_key]
        if unknown_targets:
            raise UnknownTargetError(unknown_targets)

        warnings: list[GraphWarning] = []
        boundary = []
        for key in request.boundary_capability_keys:
            if key in self.node_by_key:
                boundary.append(key)
            else:
                warnings.append(GraphWarning(
                    code="UNKNOWN_BOUNDARY_CAPABILITY",
                    message=f"boundary capability {key} is not in graph {self.graph_version}",
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
            for condition in edge.conditions:
                value = active.get((condition.kind, condition.key))
                if value is None or value not in condition.accepted_values:
                    return False
            return True

        prerequisites_of: dict[str, list[CapabilityGraphEdge]] = {}
        for edge in self.edges:
            if edge_applies(edge):
                prerequisites_of.setdefault(edge.to_capability_key, []).append(edge)

        included: set[str] = set(targets) | boundary_set
        frontier = list(targets)
        depth = 0
        while frontier and depth < request.max_depth:
            next_frontier: list[str] = []
            for key in frontier:
                if key in boundary_set:
                    continue  # 사용자가 이미 검증한 역량 너머는 펼치지 않는다
                for edge in prerequisites_of.get(key, []):
                    prerequisite = edge.from_capability_key
                    if prerequisite not in included:
                        included.add(prerequisite)
                        next_frontier.append(prerequisite)
            frontier = next_frontier
            depth += 1

        nodes = [node for node in self.nodes if node.canonical_key in included]
        edges = [
            edge for edge in self.edges
            if edge_applies(edge)
            and edge.from_capability_key in included
            and edge.to_capability_key in included
        ]
        source_ids = {sid for node in nodes for sid in node.source_ids}
        source_ids |= {sid for edge in edges for sid in edge.source_ids}
        sources = [source for source in self.sources if source.source_id in source_ids]

        closure = CapabilityGraphClosure(
            graph_version=self.graph_version,
            generated_at=datetime.now(UTC),
            content_hash="sha256:" + "0" * 64,
            target_capability_keys=list(request.target_capability_keys),
            resolved_project_task_keys=list(request.project_task_keys),
            boundary_capability_keys=boundary,
            nodes=nodes,
            edges=edges,
            sources=sources,
            learning_order=self._learning_order(included - boundary_set, edges),
            warnings=warnings,
        )
        return closure.model_copy(update={"content_hash": closure_content_hash(closure)})

    def _learning_order(
        self,
        keys: set[str],
        edges: list[CapabilityGraphEdge],
    ) -> list[LearningLayer]:
        depth_of: dict[str, int] = {}

        def resolve(key: str, trail: tuple[str, ...]) -> int:
            if key in depth_of:
                return depth_of[key]
            if key in trail:  # HARD 사이클은 데이터셋 검증이 이미 막지만, 조건부 포함까지 방어
                return 0
            depths = [
                resolve(edge.from_capability_key, (*trail, key)) + 1
                for edge in edges
                if edge.to_capability_key == key and edge.from_capability_key in keys
            ]
            depth_of[key] = max(depths, default=0)
            return depth_of[key]

        for key in keys:
            resolve(key, ())
        layers: dict[int, list[str]] = {}
        for key, depth in depth_of.items():
            layers.setdefault(depth, []).append(key)
        return [
            LearningLayer(depth=depth, capability_keys=sorted(layers[depth]))
            for depth in sorted(layers)
        ]


class UnknownTargetError(Exception):
    def __init__(self, keys: list[str]) -> None:
        super().__init__(f"unknown target capabilities: {sorted(keys)}")
        self.keys = keys


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message}})


def _shared_secret() -> str:
    return os.getenv("JOBIS_GRAPH_SHARED_SECRET", "local-capability-graph-secret")


def load_dataset() -> GraphDataset:
    path = Path(os.getenv("JOBIS_GRAPH_DATASET_PATH", str(DEFAULT_DATASET)))
    return GraphDataset(path)


app = FastAPI(title="jobis-capability-graph")
_dataset = load_dataset()


@app.middleware("http")
async def require_secret(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        if request.headers.get("X-JOBIS-GRAPH-SECRET") != _shared_secret():
            return _error(401, "invalid or missing X-JOBIS-GRAPH-SECRET header")
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "jobis-capability-graph",
        "contractVersion": CONTRACT_VERSION,
        "graphVersion": _dataset.graph_version,
        "capabilityCount": len(_dataset.nodes),
    }


@app.get("/v1/capabilities")
def catalog() -> JSONResponse:
    return JSONResponse(_dataset.catalog.model_dump(mode="json", by_alias=True))


@app.post("/v1/graph/prerequisites")
async def prerequisites(request: Request) -> JSONResponse:
    try:
        query = CapabilityGraphQueryRequest.model_validate(await request.json())
    except ValueError as exc:
        return _error(400, f"invalid prerequisite query: {exc}")
    if (
        query.requested_graph_version is not None
        and query.requested_graph_version != _dataset.graph_version
    ):
        return _error(
            400,
            f"requested graph version {query.requested_graph_version}, "
            f"active version is {_dataset.graph_version}",
        )
    try:
        closure = _dataset.prerequisites(query)
    except UnknownTargetError as exc:
        return _error(400, str(exc))
    return JSONResponse(closure.model_dump(mode="json", by_alias=True))
