"""Optional HTTP facade over the same approved graph release used in-process.

Run with::

    python -m uvicorn jobis_ai.capability_graph_server.app:app --port 8600

The single JOBIS AI runtime does not require this process.  It remains as a
read-only compatibility facade for callers that explicitly configure the HTTP
graph adapter.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jobis_ai.career_pipeline.capability_graph import (
    DEFAULT_ACTIVE_RELEASE_PATH,
    CapabilityGraphContractError,
    GraphReleaseCapabilityGraphPort,
    LoadedGraphRelease,
    load_graph_release,
)
from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphClosure,
    CapabilityGraphQueryRequest,
)


CONTRACT_VERSION = "jobis.capability-graph.v1alpha1"
DEFAULT_DATASET = DEFAULT_ACTIVE_RELEASE_PATH


class GraphDataset:
    def __init__(self, path: Path) -> None:
        release = load_graph_release(path)
        self.path = path
        self.release = release
        self.graph_version = release.graph_version
        self.nodes = release.capabilities
        self.project_tasks = release.project_tasks
        self.task_requirements = release.task_requirements
        self._port = GraphReleaseCapabilityGraphPort(
            LoadedGraphRelease(release=release, path=path)
        )
        self.catalog = self._port.get_catalog()

    def prerequisites(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure:
        return self._port.get_learning_closure(request)


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
        "projectTaskCount": len(_dataset.project_tasks),
        "taskRequirementCount": len(_dataset.task_requirements),
    }


@app.get("/v1/capabilities")
def catalog() -> JSONResponse:
    return JSONResponse(_dataset.catalog.model_dump(mode="json", by_alias=True))


@app.post("/v1/graph/prerequisites")
async def prerequisites(request: Request) -> JSONResponse:
    try:
        query = CapabilityGraphQueryRequest.model_validate(await request.json())
        closure = _dataset.prerequisites(query)
    except ValueError as exc:
        return _error(400, f"invalid prerequisite query: {exc}")
    except CapabilityGraphContractError as exc:
        return _error(400, str(exc))
    return JSONResponse(closure.model_dump(mode="json", by_alias=True))
