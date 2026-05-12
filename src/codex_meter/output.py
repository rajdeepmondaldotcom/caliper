from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from codex_meter.models import decimal_string


def json_default(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, default=json_default)


def amount_fields(name: str, value: object) -> dict[str, object]:
    return {name: value, f"{name}_exact": decimal_string(value)}


def records_to_csv(records: list[dict]) -> str:
    if not records:
        return ""
    fields = list(records[0].keys())
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(records)
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
        values = [str(record.get(field, "")).replace("|", "\\|") for field in fields]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"
