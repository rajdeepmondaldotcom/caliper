from __future__ import annotations

import datetime as dt
import json

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage

SECRET = "REDACTED_SECRET_THAT_MUST_NEVER_LEAK"

# The privacy gate from HANDOFF.md: no protocol-bearing URLs, no <script,
# no <link. The renderer is wholly self-contained.
FORBIDDEN = ("://", "<script", "<link")


def _write_session(tmp_path):
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = [
        {
            "type": "assistant",
            "sessionId": "claude-session-1",
            "uuid": f"event-{i}",
            "parentUuid": f"parent-{i}",
            "timestamp": f"2026-05-12T10:{i:02d}:00.000Z",
            "cwd": "/tmp/project-alpha",
            "requestId": f"req-{i}",
            "message": {
                "id": f"msg-{i}",
                "role": "assistant",
                "model": "claude-sonnet-4-6-20260501",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"secret": SECRET}},
                    {"type": "tool_use", "name": "Edit", "input": {"secret": SECRET}},
                    {"type": "text", "text": SECRET},
                ],
                "usage": {"input_tokens": 100 + i, "output_tokens": 25},
            },
        }
        for i in range(1, 4)
    ]
    (projects / "claude-session-1.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def _options(tmp_path):
    return build_options(
        since="2026-05-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _render(monkeypatch, tmp_path, *, theme: str = "dark", density: str = "comfortable") -> str:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    payload = build_handoff_dashboard(
        result,
        options,
        with_deltas=False,
        generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC),
    )
    return render_dashboard(payload, theme=theme, density=density)


def test_dashboard_privacy_gate(monkeypatch, tmp_path) -> None:
    """The CI privacy gate from HANDOFF.md: no ://, no <script, no <link."""
    html = _render(monkeypatch, tmp_path)
    for needle in FORBIDDEN:
        assert needle not in html, f"Privacy gate broken — dashboard contains {needle!r}"


def test_dashboard_does_not_leak_tool_use_input(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    assert SECRET not in html


def test_dashboard_renders_section_markers(monkeypatch, tmp_path) -> None:
    """§ N markers are the design's audit-doc anchor."""
    html = _render(monkeypatch, tmp_path)
    # In non-empty rich state, we expect § 01 (cost) through § 09 (evidence).
    for marker in ("§&nbsp;01", "§&nbsp;02", "§&nbsp;03", "§&nbsp;04", "§&nbsp;07"):
        assert marker in html, f"Section marker {marker!r} missing"


def test_dashboard_renders_dark_theme_attribute(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="dark")
    assert 'data-theme="dark"' in html


def test_dashboard_renders_light_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="light")
    assert 'data-theme="light"' in html
    for needle in FORBIDDEN:
        assert needle not in html


def test_dashboard_renders_print_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="print")
    assert 'data-theme="print"' in html
    for needle in FORBIDDEN:
        assert needle not in html


def test_dashboard_renders_compact_density(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, density="compact")
    assert 'data-density="compact"' in html


def test_dashboard_renders_when_no_events(tmp_path) -> None:
    options = _options(tmp_path)
    result = load_usage(options)
    payload = build_handoff_dashboard(
        result,
        options,
        with_deltas=False,
        generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC),
    )
    html = render_dashboard(payload)
    assert "<title>" in html
    assert "Caliper Dashboard" in html
    for needle in FORBIDDEN:
        assert needle not in html
    # Empty state still renders the page header + footer + empty placeholders.
    assert "no data for this window" in html
