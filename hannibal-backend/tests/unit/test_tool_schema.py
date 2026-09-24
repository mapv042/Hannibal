"""Strict-mode schema rewriting for OpenAI function calling."""

from app.modules.ai.tool_schema import drop_null_arguments, to_strict_schema
from app.modules.ai.tools import TOOL_DEFINITIONS
from app.modules.ai.doctor_tools import DOCTOR_TOOL_DEFINITIONS


def test_optional_becomes_nullable_and_everything_required():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string", "enum": ["x", "y"]},
            "c": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["a"],
    }
    strict = to_strict_schema(schema)
    assert strict["required"] == ["a", "b", "c"]
    assert strict["additionalProperties"] is False
    assert strict["properties"]["a"]["type"] == "string"
    assert strict["properties"]["b"]["type"] == ["string", "null"]
    assert None in strict["properties"]["b"]["enum"]
    assert strict["properties"]["c"]["type"] == ["array", "null"]


def test_original_schema_is_not_mutated():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    to_strict_schema(schema)
    assert "additionalProperties" not in schema


def test_empty_properties():
    assert to_strict_schema({"type": "object", "properties": {}}) == {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False,
    }


def test_every_real_tool_converts():
    for tool in TOOL_DEFINITIONS + DOCTOR_TOOL_DEFINITIONS:
        strict = to_strict_schema(tool["input_schema"])
        assert set(strict["required"]) == set(strict["properties"])


def test_drop_null_arguments():
    assert drop_null_arguments({"a": 1, "b": None, "c": ""}) == {"a": 1, "c": ""}
