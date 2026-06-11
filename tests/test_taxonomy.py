from __future__ import annotations

from typer.testing import CliRunner

from caliper.cli import app
from caliper.normalize import normalize_model
from caliper.taxonomy import taxonomy_records

runner = CliRunner()


def test_taxonomy_records_include_claude_and_codex() -> None:
    vendors = {record["vendor"] for record in taxonomy_records()}

    assert {"openai-codex", "claude-code"} <= vendors


def test_normalize_model_uses_vendor_taxonomy() -> None:
    assert normalize_model("claude-code", "claude-sonnet-4-6-20260501") == "claude-sonnet-4.6"
    assert normalize_model("claude-code", "claude-sonnet-4-5-20250929") == "claude-sonnet-4.5"
    assert normalize_model("claude-code", "claude-opus-4-5-20251101") == "claude-opus-4.5"
    assert normalize_model("claude-code", "claude-fable-5") == "claude-fable-5"
    assert normalize_model("claude-code", "claude-haiku-4-5-20251001") == "claude-haiku-4.5"


def test_taxonomy_show_json() -> None:
    result = runner.invoke(app, ["taxonomy", "show", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert "claude-sonnet-4.6" in result.output
