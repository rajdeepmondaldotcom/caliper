from __future__ import annotations

from caliper.humanize import compact_number


def test_compact_number_uses_readable_suffixes() -> None:
    assert compact_number(999) == "999"
    assert compact_number(1_500) == "1.5K"
    assert compact_number(2_345_000) == "2.35M"
    assert compact_number(1_234_567_890) == "1.23B"
    assert compact_number(1_760.99, prefix="$") == "$1.76K"


def test_sparkline_empty():
    from caliper.humanize import sparkline

    assert sparkline([]) == ""


def test_sparkline_all_equal_returns_lowest_bar():
    from caliper.humanize import sparkline

    assert sparkline([5.0, 5.0, 5.0]) == "▁▁▁"


def test_sparkline_renders_ascending_series():
    from caliper.humanize import sparkline

    out = sparkline([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    assert out[0] == "▁"
    assert out[-1] == "█"
    assert len(out) == 8


def test_live_module_alias_still_works():
    from caliper.live import _sparkline

    assert _sparkline([1.0, 2.0, 3.0]) == "▁▅█"
