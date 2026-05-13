from __future__ import annotations

from caliper.humanize import compact_number


def test_compact_number_uses_readable_suffixes() -> None:
    assert compact_number(999) == "999"
    assert compact_number(1_500) == "1.5K"
    assert compact_number(2_345_000) == "2.35M"
    assert compact_number(1_234_567_890) == "1.23B"
    assert compact_number(1_760.99, prefix="$") == "$1.76K"
