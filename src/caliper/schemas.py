from __future__ import annotations

import dataclasses
import json
import types
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from caliper import SCHEMA_VERSION, __version__
from caliper.models import RateLimitSample, ThreadMeta, Usage, UsageEvent

SCHEMA_TYPES = {
    "usage": Usage,
    "thread_meta": ThreadMeta,
    "usage_event": UsageEvent,
    "rate_limit_sample": RateLimitSample,
}


def export_schema(name: str = "usage_event") -> dict[str, Any]:
    if name not in SCHEMA_TYPES:
        raise ValueError(f"schema must be one of: {', '.join(sorted(SCHEMA_TYPES))}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/rajdeepmondaldotcom/caliper/schemas/{name}.schema.json",
        "title": f"Caliper {name}",
        "caliper": {"version": __version__, "schema_version": SCHEMA_VERSION},
        **_schema_for_type(SCHEMA_TYPES[name]),
    }


def validate_json(path: Path, schema_name: str = "usage_event") -> list[str]:
    schema = export_schema(schema_name)
    try:
        payload = json.loads(path.expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [str(exc)]
    return _validate(payload, schema, "$")


def _schema_for_type(value: Any) -> dict[str, Any]:
    if isinstance(value, type) and dataclasses.is_dataclass(value):
        # `from __future__ import annotations` turns dataclass field.type into a
        # string. Resolve it through get_type_hints so nested dataclasses such as
        # UsageEvent.usage: Usage produce nested object schemas, not "string".
        try:
            resolved_hints = get_type_hints(value)
        except Exception:  # pragma: no cover - defensive, e.g. partial typing
            resolved_hints = {}
        properties = {}
        required = []
        dataclass_params = getattr(value, "__dataclass_params__", None)
        custom_init = (
            "__init__" in vars(value) and dataclass_params is not None and not dataclass_params.init
        )
        for field in dataclasses.fields(value):
            field_type = resolved_hints.get(field.name, field.type)
            properties[field.name] = _schema_for_type(field_type)
            # Dataclasses with init=False supply defaults inside a custom __init__,
            # so field-level MISSING is not a signal that the key must be present.
            # In permissive mode, mark required only when the field has no default
            # AND the dataclass uses the default __init__.
            if (
                not custom_init
                and field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                required.append(field.name)
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": True,
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema
    origin = get_origin(value)
    args = get_args(value)
    if origin in {list, set, tuple}:
        return {"type": "array", "items": _schema_for_type(args[0]) if args else {}}
    if origin in {dict}:
        return {"type": "object"}
    if origin in {types.UnionType, getattr(types, "UnionType", None)} or origin is Any:
        return _union_schema(args)
    if value in {str, Path}:
        return {"type": "string"}
    if value is int:
        return {"type": "integer"}
    if value is float:
        return {"type": "number"}
    if value is bool:
        return {"type": "boolean"}
    if value is Any or value is object:
        return {}
    return {"type": "string"}


def _union_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    if not args:
        return {}
    schemas = [_schema_for_type(arg) for arg in args if arg is not type(None)]
    if len(schemas) == 1:
        return {"anyOf": [schemas[0], {"type": "null"}]} if type(None) in args else schemas[0]
    if type(None) in args:
        schemas.append({"type": "null"})
    return {"anyOf": schemas}


def _validate(payload: Any, schema: dict[str, Any], path: str) -> list[str]:
    if "anyOf" in schema:
        branch_errors = [_validate(payload, branch, path) for branch in schema.get("anyOf", [])]
        if any(not errors for errors in branch_errors):
            return []
        return [f"{path}: did not match any allowed schema"]

    errors: list[str] = []
    expected = schema.get("type")
    if expected and not _matches_type(payload, expected):
        return [f"{path}: expected {expected}"]
    if isinstance(payload, list) and "items" in schema:
        for index, item in enumerate(payload):
            errors.extend(_validate(item, schema["items"], f"{path}[{index}]"))
    for key in schema.get("required", []):
        if not isinstance(payload, dict) or key not in payload:
            errors.append(f"{path}: missing required key {key}")
    if isinstance(payload, dict):
        for key, child_schema in schema.get("properties", {}).items():
            if key in payload:
                errors.extend(_validate(payload[key], child_schema, f"{path}.{key}"))
    return errors


def _matches_type(payload: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(payload, dict)
    if expected == "array":
        return isinstance(payload, list)
    if expected == "string":
        return isinstance(payload, str)
    if expected == "integer":
        return isinstance(payload, int) and not isinstance(payload, bool)
    if expected == "number":
        return isinstance(payload, (int, float)) and not isinstance(payload, bool)
    if expected == "boolean":
        return isinstance(payload, bool)
    if expected == "null":
        return payload is None
    return True
