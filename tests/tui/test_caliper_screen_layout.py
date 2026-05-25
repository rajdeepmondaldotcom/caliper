"""Pin the three-band layout invariant on every CaliperScreen subclass.

Runtime Screen instantiation needs an active App. Tests stay
dependency-free by inspecting the source of the base class instead.
"""

from __future__ import annotations

import inspect

from caliper.tui.screens import _base


def test_caliper_screen_source_declares_three_containers():
    src = inspect.getsource(_base.CaliperScreen.compose)
    assert 'id="top"' in src, "Missing #top container in CaliperScreen.compose"
    assert 'id="middle"' in src, "Missing #middle container"
    assert 'id="footer-band"' in src, "Missing #footer-band container"
    assert "markup=False" in src, "Footer shortcut hints must render literal brackets"


def test_caliper_screen_default_footer_pills_carry_globals():
    pills = _base.CaliperScreen.footer_pills(_base.CaliperScreen)
    assert "refresh" in pills
    assert "help" in pills
    assert "quit" in pills


def test_caliper_screen_top_uses_screen_title_and_question():
    src = inspect.getsource(_base.CaliperScreen.top)
    assert "SCREEN_TITLE" in src
    assert "SCREEN_QUESTION" in src


def test_caliper_screen_css_caps_top_band_height():
    css = _base.CaliperScreen.DEFAULT_CSS
    assert "#top" in css
    assert "max-height" in css


def test_caliper_screen_css_pins_footer_to_one_line():
    css = _base.CaliperScreen.DEFAULT_CSS
    assert "#footer-band" in css
    assert "height: 1" in css


def test_caliper_screen_middle_is_flex_one():
    css = _base.CaliperScreen.DEFAULT_CSS
    assert "#middle" in css
    assert "1fr" in css
