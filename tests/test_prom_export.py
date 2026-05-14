from __future__ import annotations

import datetime as dt
import io
import json

from typer.testing import CliRunner

from caliper.cli import app
from caliper.prom_export import (
    MetricsSnapshot,
    build_metrics_text,
    make_handler,
    serve_forever,
)
from caliper.timeutil import local_timezone

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _receipt_fixture(tmp_path, when: dt.datetime | None = None) -> tuple:
    session_root = tmp_path / "sessions"
    now = when or dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 500,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 25,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db, now


def test_metrics_text_includes_all_expected_metric_names() -> None:
    snapshot = MetricsSnapshot(
        cost_usd=123.45,
        burn_per_hour=10.5,
        primary_window_percent=42.0,
        secondary_window_percent=8.0,
        events_total=12,
        long_context_events_total=2,
        tokens_total={
            ("gpt-5.5", "fast", "input"): 1000,
            ("gpt-5.5", "fast", "output"): 200,
        },
    )
    body = build_metrics_text(snapshot).decode()
    for metric in (
        "caliper_cost_usd",
        "caliper_burn_per_hour",
        "caliper_window_used_percent",
        "caliper_tokens_total",
        "caliper_events_total",
        "caliper_long_context_events_total",
    ):
        assert metric in body
    assert 'window="primary"' in body
    assert 'window="secondary"' in body
    assert 'model="gpt-5.5"' in body
    assert 'kind="output"' in body


def test_metrics_text_handles_empty_tokens_dict() -> None:
    snapshot = MetricsSnapshot(
        cost_usd=0.0,
        burn_per_hour=0.0,
        primary_window_percent=0.0,
        secondary_window_percent=0.0,
        events_total=0,
        long_context_events_total=0,
    )
    body = build_metrics_text(snapshot).decode()
    assert "caliper_cost_usd 0.0" in body


def test_metrics_handler_serves_metrics_and_404s() -> None:
    snapshot = MetricsSnapshot(
        cost_usd=1.0,
        burn_per_hour=2.0,
        primary_window_percent=3.0,
        secondary_window_percent=4.0,
        events_total=5,
        long_context_events_total=6,
    )
    handler_cls = make_handler(lambda: snapshot)

    class TestHandler(handler_cls):
        def __init__(self, path: str) -> None:
            self.path = path
            self.wfile = io.BytesIO()
            self.status: int | None = None
            self.headers: dict[str, str] = {}

        def send_response(self, code: int, message: str | None = None) -> None:
            del message
            self.status = code

        def send_header(self, keyword: str, value: str) -> None:
            self.headers[keyword] = value

        def end_headers(self) -> None:
            return

        def send_error(self, code: int, message: str | None = None, explain=None) -> None:
            del message, explain
            self.status = code

    ok = TestHandler("/metrics")
    ok.do_GET()
    assert ok.status == 200
    assert ok.headers["Content-Type"].startswith("text/plain")
    assert b"caliper_cost_usd 1.0" in ok.wfile.getvalue()

    missing = TestHandler("/")
    missing.do_GET()
    assert missing.status == 404


def test_metrics_handler_ignores_client_disconnect() -> None:
    snapshot = MetricsSnapshot(
        cost_usd=1.0,
        burn_per_hour=2.0,
        primary_window_percent=3.0,
        secondary_window_percent=4.0,
        events_total=5,
        long_context_events_total=6,
    )
    handler_cls = make_handler(lambda: snapshot)

    class BrokenWriter:
        def write(self, _body: bytes) -> None:
            raise BrokenPipeError

    class TestHandler(handler_cls):
        def __init__(self) -> None:
            self.path = "/metrics"
            self.wfile = BrokenWriter()
            self.status: int | None = None

        def send_response(self, code: int, message: str | None = None) -> None:
            del message
            self.status = code

        def send_header(self, keyword: str, value: str) -> None:
            del keyword, value

        def end_headers(self) -> None:
            return

    handler = TestHandler()
    handler.do_GET()

    assert handler.status == 200


def test_serve_forever_closes_server(monkeypatch) -> None:
    calls: list[str] = []

    class FakeServer:
        def __init__(self, address, handler_cls) -> None:
            self.address = address
            self.handler_cls = handler_cls

        def serve_forever(self) -> None:
            calls.append("serve")
            raise KeyboardInterrupt

        def server_close(self) -> None:
            calls.append("close")

    monkeypatch.setattr("http.server.ThreadingHTTPServer", FakeServer)

    serve_forever(
        "127.0.0.1",
        0,
        lambda: MetricsSnapshot(
            cost_usd=0,
            burn_per_hour=0,
            primary_window_percent=0,
            secondary_window_percent=0,
            events_total=0,
            long_context_events_total=0,
        ),
    )

    assert calls == ["serve", "close"]


def test_export_grafana_cli_emits_valid_dashboard_json() -> None:
    result = runner.invoke(app, ["export", "grafana"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["title"] == "Caliper"
    assert {panel["type"] for panel in parsed["panels"]} >= {"stat", "gauge", "timeseries"}


def test_export_receipt_cli_renders_markdown(tmp_path) -> None:
    session_root, state_db, now = _receipt_fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "export",
            "receipt",
            "--month",
            now.strftime("%Y-%m"),
            "--format",
            "markdown",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "# Caliper Receipt" in result.output
    assert "## Totals" in result.output
    assert "/tmp/project-alpha" not in result.output
    assert "2026-05-12T00-00-00-test" not in result.output
    assert "Synthetic private prompt" not in result.output


def test_export_receipt_show_sensitive_restores_full_labels(tmp_path) -> None:
    session_root, state_db, now = _receipt_fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "export",
            "receipt",
            "--month",
            now.strftime("%Y-%m"),
            "--format",
            "markdown",
            "--show-sensitive",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "/tmp/project-alpha" in result.output
    assert "2026-05-12T00-00-00-test" in result.output


def test_export_receipt_includes_last_moment_of_month(tmp_path) -> None:
    local_end = dt.datetime(2026, 5, 31, 23, 59, 59, 500_000, tzinfo=local_timezone())
    session_root, state_db, _now = _receipt_fixture(tmp_path, local_end)

    result = runner.invoke(
        app,
        [
            "export",
            "receipt",
            "--month",
            "2026-05",
            "--format",
            "markdown",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "| Events | 1 |" in result.output


def test_export_receipt_rejects_bad_month() -> None:
    result = runner.invoke(app, ["export", "receipt", "--month", "potato"])
    assert result.exit_code == 2
    assert "YYYY-MM" in result.output


def test_export_receipt_rejects_bad_format() -> None:
    result = runner.invoke(app, ["export", "receipt", "--format", "pdf"])
    assert result.exit_code == 2
    assert "markdown, html" in result.output
