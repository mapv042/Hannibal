"""Tool-schema transforms shared by the OpenAI services.

Our tools are written once, in Anthropic's format, with ordinary JSON-schema
optionals (a property simply left out of `required`). OpenAI's strict function
calling guarantees the arguments match the schema — no invented parameter
names, no missing required fields, enums respected — but it only accepts a
narrower dialect: every property listed in `required`, optionals expressed as
nullable, and `additionalProperties: false` on every object.

`to_strict_schema` rewrites one dialect into the other, so tool authors keep
writing the natural form. `drop_null_arguments` undoes the only visible side
effect on the way back: in strict mode an omitted optional arrives as an
explicit null, and handlers written as `args.get("x", "")` must keep seeing a
missing key rather than None.
"""

from __future__ import annotations

import copy
from typing import Any


def _nullable(prop: dict) -> dict:
    """Allow null for a property that was optional in the original schema."""
    prop = dict(prop)
    t = prop.get("type")
    if isinstance(t, str):
        prop["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        prop["type"] = [*t, "null"]
    if "enum" in prop and None not in prop["enum"]:
        prop["enum"] = [*prop["enum"], None]
    return prop


def _strict_object(schema: dict) -> dict:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    new_props: dict[str, Any] = {}
    for name, prop in properties.items():
        prop = _strict_node(prop)
        new_props[name] = prop if name in required else _nullable(prop)
    out = dict(schema)
    out["properties"] = new_props
    out["required"] = list(properties.keys())
    out["additionalProperties"] = False
    return out


def _strict_node(node: dict) -> dict:
    if not isinstance(node, dict):
        return node
    if node.get("type") == "object":
        return _strict_object(node)
    if node.get("type") == "array" and isinstance(node.get("items"), dict):
        out = dict(node)
        out["items"] = _strict_node(node["items"])
        return out
    return node


def to_strict_schema(schema: dict | None) -> dict:
    """Rewrite a tool's input_schema into OpenAI strict-mode form."""
    schema = copy.deepcopy(schema or {"type": "object", "properties": {}})
    if "type" not in schema:
        schema["type"] = "object"
    return _strict_node(schema)


def drop_null_arguments(arguments: dict) -> dict:
    """Remove top-level null arguments (strict mode's form of 'omitted')."""
    if not isinstance(arguments, dict):
        return arguments
    return {k: v for k, v in arguments.items() if v is not None}
