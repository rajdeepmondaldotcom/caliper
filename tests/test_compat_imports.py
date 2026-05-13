from __future__ import annotations

import importlib

import caliper
import caliper.cli
import caliper.parser
from caliper.parse_cache import _decode_payload as caliper_decode_payload


def test_codex_meter_package_exposes_version() -> None:
    import codex_meter

    assert codex_meter.__version__ == caliper.__version__


def test_codex_meter_submodule_imports_alias_caliper_modules() -> None:
    legacy_parser = importlib.import_module("codex_meter.parser")

    assert legacy_parser is caliper.parser


def test_codex_meter_from_import_supports_private_compatibility() -> None:
    from codex_meter.parse_cache import _decode_payload

    assert _decode_payload is caliper_decode_payload


def test_codex_meter_cli_aliases_caliper_cli() -> None:
    legacy_cli = importlib.import_module("codex_meter.cli")

    assert legacy_cli is caliper.cli
    assert legacy_cli.app is caliper.cli.app
