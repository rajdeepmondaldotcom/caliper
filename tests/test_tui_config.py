"""Validate the [tui] section reader/writer added to caliper.config."""

from __future__ import annotations

import pytest

from caliper.config import (
    TuiConfig,
    load_tui_config,
    serialize_tui_config,
)


def test_load_tui_config_returns_defaults_for_empty_dict():
    cfg = load_tui_config({})
    assert cfg == TuiConfig()
    assert cfg.theme == "slate"
    assert cfg.redact is True
    assert cfg.show_demo_on_first_run is True
    assert cfg.no_watchdog is False


def test_load_tui_config_reads_section():
    loaded = {
        "tui": {
            "theme": "parchment",
            "redact": False,
            "show_demo_on_first_run": False,
            "no_watchdog": True,
        }
    }
    cfg = load_tui_config(loaded)
    assert cfg.theme == "parchment"
    assert cfg.redact is False
    assert cfg.show_demo_on_first_run is False
    assert cfg.no_watchdog is True


def test_load_tui_config_rejects_unknown_theme_silently():
    cfg = load_tui_config({"tui": {"theme": "neon-lime"}})
    assert cfg.theme == "slate"  # fell back to default


def test_with_theme_returns_new_config():
    cfg = TuiConfig()
    new = cfg.with_theme("colorblind")
    assert new.theme == "colorblind"
    assert cfg.theme == "slate"  # original untouched


def test_with_theme_raises_for_unknown():
    with pytest.raises(ValueError):
        TuiConfig().with_theme("hot-pink")


def test_serialize_round_trips():
    cfg = TuiConfig(
        theme="monochrome",
        redact=False,
        show_demo_on_first_run=False,
        no_watchdog=True,
    )
    table = serialize_tui_config(cfg)
    assert load_tui_config({"tui": table}) == cfg
