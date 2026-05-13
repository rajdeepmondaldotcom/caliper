from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from caliper.cli import app
from caliper.schemas import (
    _matches_type,
    _schema_for_type,
    _union_schema,
    _validate,
    export_schema,
    validate_json,
)

runner = CliRunner()


def test_schema_export_contains_caliper_envelope() -> None:
    schema = export_schema("usage_event")

    assert schema["caliper"]["schema_version"] == 1
    assert "timestamp" in schema["properties"]
    assert schema["properties"]["usage"]["properties"]["input_tokens"]["type"] == "integer"


def test_schema_export_covers_all_public_schema_names() -> None:
    assert export_schema("usage")["title"] == "Caliper usage"
    assert export_schema("thread_meta")["title"] == "Caliper thread_meta"
    assert export_schema("rate_limit_sample")["title"] == "Caliper rate_limit_sample"


def test_schema_export_rejects_unknown_name() -> None:
    try:
        export_schema("unknown")
    except ValueError as exc:
        assert "schema must be one of:" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_schema_validate_usage_event_payload(tmp_path) -> None:
    payload = {
        "timestamp": "2026-05-12T00:00:00Z",
        "path": "/tmp/session.jsonl",
        "session_id": "session",
        "usage": {"input_tokens": 1, "total_tokens": 1},
        "model": "gpt-5.5",
        "service_tier": "standard",
        "tier_source": "logged",
        "thread": {},
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))

    assert validate_json(path, "usage_event") == []


def test_schema_validate_reports_required_and_nested_type_errors(tmp_path) -> None:
    payload = {
        "timestamp": "2026-05-12T00:00:00Z",
        "path": "/tmp/session.jsonl",
        "session_id": "session",
        "usage": {"input_tokens": "not-an-int"},
        "model": "gpt-5.5",
        "service_tier": "standard",
        "tier_source": "logged",
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))

    errors = validate_json(path, "usage_event")

    assert "$: missing required key thread" in errors
    assert "$.usage.input_tokens: expected integer" in errors


def test_schema_validate_reports_file_and_json_errors(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    assert validate_json(missing, "usage_event")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{")
    assert validate_json(malformed, "usage_event")


def test_schema_helpers_handle_supported_type_shapes() -> None:
    assert _schema_for_type(list[int]) == {"type": "array", "items": {"type": "integer"}}
    assert _schema_for_type(dict[str, int]) == {"type": "object"}
    assert _schema_for_type(str | None) == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert _schema_for_type(float) == {"type": "number"}
    assert _schema_for_type(bool) == {"type": "boolean"}
    assert _schema_for_type(Any) == {}
    assert _schema_for_type(complex) == {"type": "string"}
    assert _schema_for_type(object()) == {"type": "string"}


def test_schema_validator_handles_anyof_and_arrays() -> None:
    assert _validate([1, 2], {"type": "array", "items": {"type": "integer"}}, "$") == []
    assert _validate([1, "bad"], {"type": "array", "items": {"type": "integer"}}, "$") == [
        "$[1]: expected integer"
    ]

    nullable_string = _union_schema((str, type(None)))
    assert _validate(None, nullable_string, "$.value") == []
    assert _validate("ok", nullable_string, "$.value") == []
    assert _validate(3, nullable_string, "$.value") == ["$.value: did not match any allowed schema"]


def test_schema_type_matching_excludes_bool_from_numeric_types() -> None:
    assert not _matches_type(True, "integer")
    assert not _matches_type(False, "number")
    assert _matches_type(None, "null")
    assert _matches_type({}, "object")
    assert _matches_type([], "array")
    assert _matches_type("x", "unknown-json-schema-type")


def test_schema_cli_export_and_validate(tmp_path) -> None:
    result = runner.invoke(app, ["schema", "export", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "usage_event" in result.output

    payload = {
        "timestamp": "2026-05-12T00:00:00Z",
        "path": "/tmp/session.jsonl",
        "session_id": "session",
        "usage": {"input_tokens": 1, "total_tokens": 1},
        "model": "gpt-5.5",
        "service_tier": "standard",
        "tier_source": "logged",
        "thread": {},
    }
    target = tmp_path / "event.json"
    target.write_text(json.dumps(payload))
    valid = runner.invoke(app, ["schema", "validate", str(target)])
    assert valid.exit_code == 0, valid.output


def test_schema_cli_rejects_bad_format_and_invalid_payload(tmp_path) -> None:
    bad_format = runner.invoke(app, ["schema", "export", "--format", "yaml"])
    assert bad_format.exit_code == 2
    assert "--output-format must be json" in bad_format.output

    target = tmp_path / "event.json"
    target.write_text(json.dumps({"usage": []}))
    invalid = runner.invoke(app, ["schema", "validate", str(target)])
    assert invalid.exit_code == 2
    assert "missing required key timestamp" in invalid.output
