"""Compatibility import surface for the internal career pipeline."""

from ..llm_adapter import (
    JsonCompletionProvider,
    JsonProviderError,
    JsonProviderNotConfigured,
    LlmProgressCallback,
    LlmProgressEvent,
    StructuredGeneration,
    StructuredGenerator,
)

__all__ = [
    "JsonCompletionProvider",
    "JsonProviderError",
    "JsonProviderNotConfigured",
    "LlmProgressCallback",
    "LlmProgressEvent",
    "StructuredGeneration",
    "StructuredGenerator",
]
