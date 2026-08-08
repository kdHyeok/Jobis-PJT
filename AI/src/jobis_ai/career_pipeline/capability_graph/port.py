from __future__ import annotations

import hashlib
import json
from typing import Protocol

import httpx

from jobis_ai.career_pipeline.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
    CapabilityGraphQueryRequest,
)


class CapabilityGraphUnavailable(RuntimeError):
    pass


class CapabilityGraphContractError(RuntimeError):
    pass


class CapabilityGraphPort(Protocol):
    def get_catalog(self) -> CapabilityGraphCatalog: ...

    def get_learning_closure(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure: ...


class UnavailableCapabilityGraphPort:
    def get_catalog(self) -> CapabilityGraphCatalog:
        raise CapabilityGraphUnavailable("CAPABILITY_GRAPH_URL is not configured")

    def get_learning_closure(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure:
        raise CapabilityGraphUnavailable("CAPABILITY_GRAPH_URL is not configured")


class HttpCapabilityGraphPort:
    """Read-only adapter for the separately owned capability graph service."""

    def __init__(
        self,
        *,
        base_url: str,
        shared_secret: str,
        timeout_seconds: float,
    ) -> None:
        if not base_url.strip():
            raise CapabilityGraphUnavailable("CAPABILITY_GRAPH_URL is not configured")
        self._base_url = base_url.rstrip("/")
        self._secret = shared_secret
        self._timeout = timeout_seconds

    def get_learning_closure(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure:
        try:
            response = httpx.post(
                f"{self._base_url}/v1/graph/prerequisites",
                headers={
                    "X-JOBIS-GRAPH-SECRET": self._secret,
                    "X-JOBIS-CAPABILITY-GRAPH-CONTRACT": (
                        "jobis.capability-graph.v1alpha1"
                    ),
                },
                json=request.model_dump(mode="json", by_alias=True),
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise CapabilityGraphUnavailable(f"capability graph request failed: {exc}") from exc

        if response.status_code >= 500:
            raise CapabilityGraphUnavailable(
                f"capability graph request failed with status {response.status_code}"
            )
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
                detail = error.get("message") or response.text
            except (TypeError, ValueError):
                detail = response.text
            raise CapabilityGraphContractError(
                f"capability graph rejected the request ({response.status_code}): {detail}"
            )

        try:
            closure = CapabilityGraphClosure.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise CapabilityGraphContractError(f"invalid capability graph response: {exc}") from exc

        if (
            request.requested_graph_version is not None
            and closure.graph_version != request.requested_graph_version
        ):
            raise CapabilityGraphContractError(
                f"requested graph version {request.requested_graph_version}, "
                f"received {closure.graph_version}"
            )
        if set(request.target_capability_keys) - set(closure.target_capability_keys):
            raise CapabilityGraphContractError("graph response omitted requested target capabilities")
        validate_closure_hash(closure)
        return closure

    def get_catalog(self) -> CapabilityGraphCatalog:
        response = self._request("GET", "/v1/capabilities")
        try:
            return CapabilityGraphCatalog.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise CapabilityGraphContractError(
                f"invalid capability graph catalog response: {exc}"
            ) from exc

    def _request(self, method: str, path: str, *, json_payload: dict | None = None):
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "X-JOBIS-GRAPH-SECRET": self._secret,
                    "X-JOBIS-CAPABILITY-GRAPH-CONTRACT": (
                        "jobis.capability-graph.v1alpha1"
                    ),
                },
                json=json_payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise CapabilityGraphUnavailable(f"capability graph request failed: {exc}") from exc
        if response.status_code >= 500:
            raise CapabilityGraphUnavailable(
                f"capability graph request failed with status {response.status_code}"
            )
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
                detail = error.get("message") or response.text
            except (TypeError, ValueError):
                detail = response.text
            raise CapabilityGraphContractError(
                f"capability graph rejected the request ({response.status_code}): {detail}"
            )
        return response


class InMemoryCapabilityGraphPort:
    def __init__(
        self,
        closure: CapabilityGraphClosure,
        catalog: CapabilityGraphCatalog | None = None,
    ) -> None:
        self._closure = closure
        self._catalog = catalog or CapabilityGraphCatalog(
            graph_version=closure.graph_version,
            content_hash=closure.content_hash,
            capabilities=closure.nodes,
        )

    def get_catalog(self) -> CapabilityGraphCatalog:
        return self._catalog

    def get_learning_closure(
        self,
        request: CapabilityGraphQueryRequest,
    ) -> CapabilityGraphClosure:
        if set(request.target_capability_keys) - set(self._closure.target_capability_keys):
            raise CapabilityGraphContractError("fixture closure does not contain all requested targets")
        if (
            request.requested_graph_version is not None
            and request.requested_graph_version != self._closure.graph_version
        ):
            raise CapabilityGraphContractError("fixture graph version does not match the request")
        validate_closure_hash(self._closure)
        return self._closure


def closure_content_hash(closure: CapabilityGraphClosure) -> str:
    payload = closure.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_closure_hash(closure: CapabilityGraphClosure) -> None:
    expected = closure_content_hash(closure)
    if closure.content_hash != expected:
        raise CapabilityGraphContractError(
            f"capability graph content hash mismatch: expected {expected}"
        )
