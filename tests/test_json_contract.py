from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from caliper import SCHEMA_VERSION, __version__
from caliper.cli import app
from caliper.output import json_dumps_enveloped, with_caliper_envelope

runner = CliRunner()


def test_envelope_helper_preserves_payload_and_pins_schema() -> None:
    payload = with_caliper_envelope({"records": []})

    assert payload["caliper"] == {"version": __version__, "schema_version": SCHEMA_VERSION}
    assert payload["records"] == []
    assert json.loads(json_dumps_enveloped({"records": []})) == payload


def test_cli_owned_json_uses_envelope_helper() -> None:
    """Direct json_dumps calls in the CLI are reserved for non-report JSON."""
    allowed_fragments = {
        "json_dumps(export_schema(name))",
        "write_text(json_dumps(payload) +",
    }
    offenders = []
    for lineno, line in enumerate(Path("src/caliper/cli.py").read_text().splitlines(), start=1):
        if "json_dumps(" not in line:
            continue
        if any(fragment in line for fragment in allowed_fragments):
            continue
        offenders.append(f"{lineno}: {line.strip()}")

    assert offenders == []


def test_schema_export_uses_caliper_metadata() -> None:
    result = runner.invoke(app, ["schema", "export", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["caliper"]["schema_version"] == SCHEMA_VERSION
