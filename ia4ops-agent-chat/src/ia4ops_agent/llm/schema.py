"""Helpers for JSON schemas accepted by Vertex AI structured output."""

from typing import Any

_UNSUPPORTED_SCHEMA_FIELDS = frozenset({
    "maxLength", "minLength",
    "minItems", "maxItems",
    "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf",
    "pattern",
})


def clean_schema_for_vertex(schema: Any) -> Any:
    """Remove unsupported constraints; callers must still validate with Pydantic."""
    if isinstance(schema, dict):
        return {
            key: clean_schema_for_vertex(value)
            for key, value in schema.items()
            if key not in _UNSUPPORTED_SCHEMA_FIELDS
        }
    if isinstance(schema, list):
        return [clean_schema_for_vertex(item) for item in schema]
    return schema
