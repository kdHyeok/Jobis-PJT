from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


CONTRACT_VERSION = "jobis.ai.v3alpha1"


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
        validate_assignment=True,
    )


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CanonicalKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$"),
]
EntityId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


class WarningSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class WarningItem(ContractModel):
    code: NonBlank
    message: NonBlank
    severity: WarningSeverity = WarningSeverity.WARNING
    evidence_ids: list[EntityId] = Field(default_factory=list)


class ContractMetadata(ContractModel):
    contract_version: str = Field(default=CONTRACT_VERSION, pattern=r"^jobis\.ai\.v3")
    request_id: EntityId | None = None
    trace_id: EntityId | None = None
    created_at: datetime


def ensure_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label}: {duplicates}")


def ensure_contract_version(value: str) -> str:
    if not re.fullmatch(r"jobis\.ai\.v3(?:alpha|beta|rc)?[0-9]+", value):
        raise ValueError("unsupported JOBIS career-pipeline contract version format")
    return value
