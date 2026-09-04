#将MCP JSON Schema适配为当前Pico的Tool Spec
from __future__ import annotations

from typing import Any


TYPE_NAMES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def prompt_schema(input_schema: dict[str, Any]) -> dict[str, str]:
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    rendered: dict[str, str] = {}

    if not isinstance(properties, dict):
        return rendered

    for name, spec in properties.items():
        if not isinstance(spec, dict):
            rendered[str(name)] = "any"
            continue

        value = TYPE_NAMES.get(str(spec.get("type", "any")), "any")
        if isinstance(spec.get("enum"), list) and spec["enum"]:
            value += " enum=" + repr(spec["enum"])
        if name not in required:
            value += f"={spec['default']!r}" if "default" in spec else "?"
        rendered[str(name)] = value

    return rendered


def validate_arguments(input_schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")

    required = input_schema.get("required", [])
    properties = input_schema.get("properties", {})
    if not isinstance(required, list):
        required = []
    if not isinstance(properties, dict):
        properties = {}

    for name in required:
        if name not in arguments:
            raise ValueError(f"missing required argument: {name}")

    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            raise ValueError(f"unknown argument: {name}")
        if not isinstance(spec, dict):
            continue
        _validate_value(str(name), value, spec)


def _validate_value(name: str, value: Any, spec: dict[str, Any]) -> None:
    expected = spec.get("type")
    checks = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }
    if expected in checks and not checks[expected](value):
        raise ValueError(f"argument '{name}' must be {expected}")
    enum = spec.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise ValueError(f"argument '{name}' must be one of {enum!r}")