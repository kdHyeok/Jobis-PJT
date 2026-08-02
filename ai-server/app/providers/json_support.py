from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError


class InvalidProviderResponse(RuntimeError):
    pass


def parse_model[T: BaseModel](text: str, model: type[T]) -> T:
    value = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", value, re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        raise InvalidProviderResponse("Claude response did not contain a JSON object")
    try:
        payload = json.loads(value[start : end + 1])
        return model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exception:
        raise InvalidProviderResponse(
            f"Claude returned invalid structured data: {exception}"
        ) from exception
