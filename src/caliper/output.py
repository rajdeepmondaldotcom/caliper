from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from caliper import SCHEMA_VERSION, __version__
from caliper.models import decimal_string


def json_default(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, default=json_default)


def caliper_envelope() -> dict[str, object]:
    return {"version": __version__, "schema_version": SCHEMA_VERSION}


def with_caliper_envelope(payload: dict[str, object]) -> dict[str, object]:
    return {
        "caliper": caliper_envelope(),
        **{key: value for key, value in payload.items() if key != "caliper"},
    }


def json_dumps_enveloped(payload: dict[str, object]) -> str:
    return json_dumps(with_caliper_envelope(payload))


def amount_fields(name: str, value: object) -> dict[str, object]:
    return {name: value, f"{name}_exact": decimal_string(value)}


def records_to_csv(records: list[dict]) -> str:
    if not records:
        return ""
    fields = list(records[0].keys())
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {field: _stringify_record_value(field, record.get(field, "")) for field in fields}
        for record in records
    )
    return out.getvalue()


def records_to_markdown(records: list[dict]) -> str:
    if not records:
        return "_No data._\n"
    fields = list(records[0].keys())
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for record in records:
        values = [
            _stringify_record_value(field, record.get(field, "")).replace("|", "\\|")
            for field in fields
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def _stringify_record_value(field: str, value: object) -> str:
    """Stringify record values for human-facing tabular formats.

    JSON keeps numeric precision. CSV/Markdown should not expose accidental
    Python float repr for percentage columns.
    """
    if value is None:
        return ""
    lowered = field.lower()
    if isinstance(value, float) and (
        lowered in {"pct", "percent", "used_percent"} or lowered.endswith(("_pct", "_percent"))
    ):
        return f"{value:.2f}"
    return str(value)
