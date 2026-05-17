"""Guardrail: the on-disk `styles.css` must match the INLINE_STYLES string.

The renderer inlines its CSS for the offline invariant. The on-disk
`styles.css` is the source of truth that the designer edits. This test
makes sure neither drifts away from the other.
"""

from __future__ import annotations

from pathlib import Path

from caliper.dashboards.html import INLINE_STYLES

STYLES_PATH = Path(__file__).resolve().parents[1] / "src" / "caliper" / "dashboards" / "styles.css"


def test_inline_styles_match_disk_source() -> None:
    on_disk = STYLES_PATH.read_text()
    # The inline string adds one leading/trailing newline pair around the
    # raw stylesheet for readability; compare the trimmed bodies.
    assert INLINE_STYLES.strip("\n") == on_disk.rstrip("\n"), (
        "INLINE_STYLES has drifted from styles.css. Re-run the inline patch."
    )


def test_styles_have_no_external_imports() -> None:
    on_disk = STYLES_PATH.read_text()
    forbidden = ("@import url(", "://")
    for needle in forbidden:
        assert needle not in on_disk, f"styles.css contains forbidden token {needle!r}"
