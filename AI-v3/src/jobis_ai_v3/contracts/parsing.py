from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


ModelT = TypeVar("ModelT", bound=BaseModel)
FENCED_JSON = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class StructuredContractError(ValueError):
    pass


def parse_structured_payload(raw: str | dict[str, Any], model: type[ModelT]) -> ModelT:
    """Parse JSON without inventing, deleting, or defaulting semantic fields.

    The only tolerated transport repair is removing one outer Markdown JSON fence.
    Pydantic remains responsible for field, enum, and reference-adjacent validation.
    """

    payload: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        match = FENCED_JSON.fullmatch(text)
        if match:
            text = match.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StructuredContractError(f"response is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise StructuredContractError("structured response must be a JSON object")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise StructuredContractError(f"structured response violates the contract: {exc}") from exc

