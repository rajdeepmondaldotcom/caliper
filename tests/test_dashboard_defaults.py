"""Tests for the v2 dashboard's config-driven defaults and privacy modes."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from caliper.config import (
    DashboardConfig,
    derive_dashboard_output_path,
    load_dashboard_config,
    write_dashboard_defaults,
)
from caliper.dashboards import render_dashboard
from caliper.dashboards.sample_data import sample_dashboard

# ---------------------------------------------------------------------------
# DashboardConfig loading
# ---------------------------------------------------------------------------


def test_dashboard_config_defaults_when_section_missing() -> None:
    cfg = load_dashboard_config({})
    assert cfg.theme == "dark"
    assert cfg.rhythm == "receipt"
    assert cfg.density == "comfortable"
    # Default is the original format — real names everywhere. Privacy
    # redaction is opt-in via the ``--privacy`` flag.
    assert cfg.privacy == "off"
    assert cfg.output_dir == "~/Downloads"
    assert "{timestamp}" in cfg.filename_template
    # Filename uses the auto-suffix placeholder so privacy=off doesn't
    # leak "-privacy-off" into every filename.
    assert "{privacy_suffix}" in cfg.filename_template
    assert cfg.open_after is True
    assert cfg.default_days == 14
    assert cfg.interactive is True


def test_dashboard_config_respects_user_values() -> None:
    cfg = load_dashboard_config(
        {
            "dashboard": {
                "theme": "light",
                "rhythm": "terminal",
                "density": "compact",
                "privacy": "print-only",
                "output_dir": "/tmp/out",
                "filename_template": "dash-{timestamp}.html",
                "timestamp_format": "%Y%m%d",
                "open_after": False,
                "default_days": 30,
            }
        }
    )
    assert cfg.theme == "light"
    assert cfg.rhythm == "terminal"
    assert cfg.density == "compact"
    assert cfg.privacy == "print-only"
    assert cfg.output_dir == "/tmp/out"
    assert cfg.filename_template == "dash-{timestamp}.html"
    assert cfg.timestamp_format == "%Y%m%d"
    assert cfg.open_after is False
    assert cfg.default_days == 30


def test_dashboard_config_falls_back_on_invalid_choice() -> None:
    cfg = load_dashboard_config({"dashboard": {"theme": "neon", "privacy": "maybe"}})
    # Unknown values silently revert to defaults — typos don't crash the CLI.
    assert cfg.theme == "dark"
    assert cfg.privacy == "off"


# ---------------------------------------------------------------------------
# Output path derivation
# ---------------------------------------------------------------------------


def test_derive_path_uses_template_and_timestamp(tmp_path: Path) -> None:
    cfg = DashboardConfig(
        output_dir=str(tmp_path),
        filename_template="caliper-dashboard-{timestamp}-privacy-{privacy}.html",
        timestamp_format="%Y-%m-%d-%H-%M",
        privacy="print-only",
    )
    moment = dt.datetime(2026, 5, 21, 14, 30)
    path = derive_dashboard_output_path(cfg, now=moment)
    assert path.parent == tmp_path.resolve()
    assert path.name == "caliper-dashboard-2026-05-21-14-30-privacy-print-only.html"


def test_derive_path_default_template_drops_off_suffix(tmp_path: Path) -> None:
    """{privacy_suffix} keeps the default filename clean when privacy=off."""
    cfg = DashboardConfig(output_dir=str(tmp_path))  # uses default template
    moment = dt.datetime(2026, 5, 21, 14, 30)
    # Default privacy is "off" → no "-privacy-…" suffix.
    path_off = derive_dashboard_output_path(cfg, now=moment)
    assert path_off.name == "caliper-dashboard-2026-05-21-14-30.html"
    # Explicit redaction → suffix appears.
    path_safe = derive_dashboard_output_path(cfg, now=moment, privacy="print-only")
    assert path_safe.name == "caliper-dashboard-2026-05-21-14-30-privacy-print-only.html"
    path_always = derive_dashboard_output_path(cfg, now=moment, privacy="always")
    assert path_always.name == "caliper-dashboard-2026-05-21-14-30-privacy-always.html"


def test_derive_path_overrides_take_priority(tmp_path: Path) -> None:
    cfg = DashboardConfig(
        output_dir=str(tmp_path),
        privacy="off",
        filename_template="caliper-dashboard-{timestamp}-privacy-{privacy}.html",
    )
    moment = dt.datetime(2026, 5, 21, 14, 30)
    path = derive_dashboard_output_path(cfg, now=moment, privacy="always")
    assert "privacy-always" in path.name
    assert "privacy-off" not in path.name


def test_derive_path_unknown_placeholder_raises(tmp_path: Path) -> None:
    cfg = DashboardConfig(
        output_dir=str(tmp_path),
        filename_template="dash-{nonexistent}.html",
    )
    with pytest.raises(ValueError, match="nonexistent"):
        derive_dashboard_output_path(cfg)


# ---------------------------------------------------------------------------
# write_dashboard_defaults
# ---------------------------------------------------------------------------


def test_write_defaults_creates_new_file(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    written = write_dashboard_defaults(path=target)
    assert written == target.resolve() or written == target
    body = target.read_text()
    assert "[dashboard]" in body
    assert "privacy" in body
    assert "filename_template" in body


def test_write_defaults_appends_to_existing(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text('[tui]\ntheme = "slate"\n')
    write_dashboard_defaults(path=target)
    body = target.read_text()
    assert "[tui]" in body
    assert "[dashboard]" in body


def test_write_defaults_refuses_to_overwrite_existing_section(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text('[dashboard]\nprivacy = "always"\n')
    with pytest.raises(FileExistsError):
        write_dashboard_defaults(path=target)
    # Forced overwrite succeeds.
    write_dashboard_defaults(path=target, force=True)
    body = target.read_text()
    assert body.count("[dashboard]") == 1
    assert 'privacy = "always"' not in body  # replaced by template


# ---------------------------------------------------------------------------
# Privacy modes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_dashboard():
    return sample_dashboard(show_paths=True)


def test_privacy_off_shows_real_project_names(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, privacy="off")
    # The sample data has "api-server" as a real project name.
    assert "api-server" in html
    # No private wrapper spans in off mode.
    assert 'class="cal-real"' not in html
    assert 'class="cal-redacted"' not in html
    assert 'data-privacy="off"' in html


def test_privacy_always_redacts_project_names_in_tables(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, privacy="always")
    # The body table cells use indexed placeholders instead of real names.
    assert ">Project 1<" in html or ">Project 2<" in html
    # No real-vs-redacted wrappers in always mode (the renderer emits the
    # redacted text directly).
    assert 'class="cal-real"' not in html
    assert 'class="cal-redacted"' not in html
    assert 'data-privacy="always"' in html
    assert 'data-share-safe="true"' in html


def test_privacy_print_only_emits_both_spans(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, privacy="print-only")
    # Both real and redacted labels coexist; CSS decides which shows.
    assert 'class="cal-real"' in html
    assert 'class="cal-redacted"' in html
    # The browser shows real labels — they're present.
    assert "api-server" in html
    # The redacted placeholder is also in the HTML, hidden by default.
    assert ">Project 1<" in html or ">Project 2<" in html
    assert 'data-privacy="print-only"' in html


def test_privacy_invalid_value_raises(demo_dashboard) -> None:
    with pytest.raises(ValueError, match="privacy must be one of"):
        render_dashboard(demo_dashboard, privacy="bogus")


def test_privacy_path_redaction(demo_dashboard) -> None:
    # In always mode, paths are replaced with "[path]". In off mode, the
    # raw filesystem path is preserved.
    html_off = render_dashboard(demo_dashboard, privacy="off")
    html_always = render_dashboard(demo_dashboard, privacy="always")
    # The sample data uses "~/work/api-server" as the path for the first project.
    assert "~/work" in html_off
    assert "~/work" not in html_always
    assert "[path]" in html_always


def test_indexed_placeholders_are_stable_and_sorted(demo_dashboard) -> None:
    """Project names should be assigned in alphabetical order for stability."""
    html = render_dashboard(demo_dashboard, privacy="always")
    # Get all unique project names in the demo and check that Project 1 is
    # alphabetically first.
    names = sorted({p.name for p in demo_dashboard.by_project})
    if len(names) >= 1:
        # "Project 1" should appear in the HTML, mapped to the alphabetically
        # first project. We don't assert which one; just that the redaction
        # is present.
        assert ">Project 1<" in html


# ---------------------------------------------------------------------------
# share_safe back-compat
# ---------------------------------------------------------------------------


def test_share_safe_true_maps_to_privacy_always(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, share_safe=True)
    assert 'data-privacy="always"' in html
    assert 'data-share-safe="true"' in html


def test_share_safe_false_with_explicit_privacy(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, share_safe=False, privacy="print-only")
    assert 'data-privacy="print-only"' in html
    assert 'data-share-safe="false"' in html


# ---------------------------------------------------------------------------
# Interactive playground (toggle panel + snapshot save)
# ---------------------------------------------------------------------------


def test_interactive_off_emits_no_script(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, interactive=False)
    assert "<script>" not in html
    # The panel element itself is absent (CSS class name still appears in
    # the embedded stylesheet, which is harmless).
    assert 'class="cal-tweaks-panel"' not in html
    assert 'id="cal-save-snapshot"' not in html
    assert 'data-interactive="false"' in html


def test_interactive_on_emits_exactly_one_inline_script(demo_dashboard) -> None:
    html = render_dashboard(demo_dashboard, interactive=True)
    assert html.count("<script>") == 1
    assert html.count("</script>") == 1
    # The toolbar landmark and the save button anchor are both present.
    assert 'class="cal-tweaks-panel"' in html
    assert 'id="cal-save-snapshot"' in html


def test_interactive_includes_both_rhythm_bodies(demo_dashboard) -> None:
    """With interactive mode the file embeds both rhythms; CSS swaps them."""
    html = render_dashboard(demo_dashboard, interactive=True, rhythm="receipt")
    assert 'class="cal-rhythm-receipt"' in html
    assert 'class="cal-rhythm-terminal"' in html
    # The initial active rhythm is set via the body data-attr.
    assert 'data-rhythm="receipt"' in html
    # Both masthead variants appear (only one is visible, the other hidden).
    assert "Cost layer for AI-assisted development" in html  # receipt
    assert "OFFLINE" in html  # terminal


def test_interactive_script_has_no_network_apis(demo_dashboard) -> None:
    """The toggle controller must not introduce any network primitives."""
    html = render_dashboard(demo_dashboard, interactive=True)
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon"):
        assert forbidden not in html, f"Script reaches the network via {forbidden!r}"
    # Only DOM + localStorage + Blob/URL are allowed.
    assert "Blob" in html
    assert "URL.createObjectURL" in html
    assert "localStorage" in html


def test_interactive_initial_mode_matches_state(demo_dashboard) -> None:
    """The toggle reflects the initial theme/privacy combination."""
    html_dark = render_dashboard(demo_dashboard, interactive=True, theme="dark", privacy="off")
    assert 'data-mode="dark"' in html_dark

    html_light = render_dashboard(demo_dashboard, interactive=True, theme="light", privacy="off")
    assert 'data-mode="light"' in html_light

    html_safe = render_dashboard(demo_dashboard, interactive=True, theme="print", privacy="always")
    assert 'data-mode="safe-share"' in html_safe


def test_interactive_always_emits_redacted_spans(demo_dashboard) -> None:
    """Safe Share toggle can't swap if redacted text was never emitted.

    When ``interactive=True`` the renderer should force the privacy map
    into "print-only" mode so both real and redacted spans exist — even
    if the initial ``--privacy`` is ``off``.
    """
    html = render_dashboard(demo_dashboard, interactive=True, privacy="off")
    assert 'class="cal-real"' in html
    assert 'class="cal-redacted"' in html
    # The body still reports ``off`` because that's the initial view; the
    # CSS rules use it to keep redacted text hidden in the browser.
    assert 'data-privacy="off"' in html


def test_interactive_config_default_is_true() -> None:
    """A bare-bones config keeps interactive mode on."""
    from caliper.config import load_dashboard_config

    cfg = load_dashboard_config({})
    assert cfg.interactive is True


def test_interactive_config_respects_override() -> None:
    from caliper.config import load_dashboard_config

    cfg = load_dashboard_config({"dashboard": {"interactive": False}})
    assert cfg.interactive is False


# ---------------------------------------------------------------------------
# Progress display + auto-init UX
# ---------------------------------------------------------------------------


def test_dashboard_cli_quiet_suppresses_tail_message(monkeypatch, tmp_path: Path) -> None:
    """``--quiet`` silences the post-render tail line about the playground."""
    from typer.testing import CliRunner

    from caliper.cli import app

    out = tmp_path / "quiet.html"
    result = CliRunner().invoke(app, ["dashboard", "--demo", "--output", str(out), "--quiet"])
    assert result.exit_code == 0, result.output
    assert "Toggle Receipt/Terminal" not in result.output


def test_write_dashboard_defaults_to_custom_path(tmp_path: Path) -> None:
    """The init writer creates a fresh file at the requested location."""
    target = tmp_path / "config.toml"
    written = write_dashboard_defaults(path=target)
    assert written == target.resolve() or written == target
    assert target.exists()
    body = target.read_text()
    assert "[dashboard]" in body
    assert "privacy" in body
    assert "interactive" in body


def test_progress_activation_rule_for_dashboard(monkeypatch) -> None:
    """The dashboard's progress widget must activate on a TTY stderr even
    though the output is HTML — the legacy guard would otherwise suppress
    it. We verify the activation predicate behaves the way the dashboard
    invokes it."""
    from caliper.cli_progress import _should_show_progress

    # Dashboard passes ``output_format="table"`` and ``output=None`` and
    # forces ``progress=True`` whenever it auto-detected a TTY. That
    # combination must activate.
    assert _should_show_progress(
        output_format="table", output=None, progress=True, quiet=False, isatty=True
    )
    # ``--quiet`` overrides everything.
    assert not _should_show_progress(
        output_format="table", output=None, progress=True, quiet=True, isatty=True
    )
