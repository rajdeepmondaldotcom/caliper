from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper.cli import app
from tests.conftest import token_event, turn_context, write_session

runner = CliRunner()


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    sessions = tmp_path / "sessions"
    state = tmp_path / "state.sqlite"
    config = tmp_path / "codex.toml"
    sessions.mkdir(parents=True)
    state.touch()
    events = [
        turn_context(model="gpt-5.5", service_tier="standard"),
        token_event(
            dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC),
            {
                "input_tokens": 290_000,  # crosses long-context threshold
                "cached_input_tokens": 0,
                "output_tokens": 200,
                "reasoning_output_tokens": 0,
                "total_tokens": 290_200,
            },
        ),
        token_event(
            dt.datetime(2026, 5, 12, 13, 0, tzinfo=dt.UTC),
            {
                "input_tokens": 290_000,
                "cached_input_tokens": 0,
                "output_tokens": 200,
                "reasoning_output_tokens": 0,
                "total_tokens": 290_200,
            },
        ),
    ]
    write_session(sessions, "rollout.jsonl", events)
    return sessions, state, config


def _common(sessions: Path, state: Path, config: Path) -> list[str]:
    return [
        "--from-codex",
        str(sessions),
        "--codex-db",
        str(state),
        "--codex-config",
        str(config),
        "--days",
        "30",
        "--until",
        "2026-05-15T00:00:00Z",
    ]


def test_audit_table_runs(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(app, ["audit", *_common(sessions, state, config)])
    assert result.exit_code in {0, 1, 2}
    assert "Caliper - Audit" in result.stdout


def test_audit_json_shape(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app,
        ["audit", "--output-format", "json", *_common(sessions, state, config)],
    )
    assert result.exit_code in {0, 1, 2}
    payload = json.loads(result.stdout)
    assert "findings" in payload
    assert "total_savings_usd" in payload
    assert "monthly_projected_savings_usd" in payload
    assert "waste_share_of_spend" in payload


def test_audit_strict_blocks_when_above_threshold(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app,
        [
            "audit",
            "--strict",
            "--waste-threshold-usd",
            "0.01",
            *_common(sessions, state, config),
        ],
    )
    assert result.exit_code == 2


def test_audit_strict_passes_with_high_threshold(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app,
        [
            "audit",
            "--strict",
            "--waste-threshold-usd",
            "1000000",
            *_common(sessions, state, config),
        ],
    )
    # Even when --strict does not trigger, findings present mean exit 1.
    assert result.exit_code in {0, 1}


def test_predict_runs_table(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(app, ["predict", *_common(sessions, state, config)])
    assert result.exit_code == 0
    assert "Predictive analytics" in result.stdout


def test_predict_json_shape(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app,
        ["predict", "--output-format", "json", *_common(sessions, state, config)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {
        "per_model",
        "seasonality",
        "rate_limits",
        "anomalies",
        "cost_outlook",
    } <= payload.keys()


def test_predict_json_anomalies_include_actionability_metadata(tmp_path: Path):
    sessions = tmp_path / "sessions"
    state = tmp_path / "state.sqlite"
    config = tmp_path / "codex.toml"
    sessions.mkdir(parents=True)
    state.touch()
    base = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC)
    for idx in range(8):
        write_session(
            sessions,
            f"prior-{idx}.jsonl",
            [
                turn_context(model="gpt-5.5", service_tier="standard"),
                token_event(
                    base + dt.timedelta(days=idx),
                    {
                        "input_tokens": 100,
                        "cached_input_tokens": 0,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 0,
                        "total_tokens": 110,
                    },
                ),
            ],
        )
    write_session(
        sessions,
        "huge.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                base + dt.timedelta(days=9),
                {
                    "input_tokens": 10_000_000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100_000,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 10_100_000,
                },
            ),
        ],
    )

    result = runner.invoke(
        app,
        ["predict", "--output-format", "json", *_common(sessions, state, config)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["anomalies"]
    top = payload["anomalies"][0]
    assert top["baseline_sample_count"] >= 4
    assert top["comparison_scope"]
    assert top["reason"]


def test_recommend_markdown(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(app, ["recommend", *_common(sessions, state, config)])
    assert result.exit_code == 0
    assert "Recommendations" in result.stdout or "No actionable" in result.stdout


def test_exec_alias_renders_executive_summary(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(app, ["exec", *_common(sessions, state, config)])
    assert result.exit_code == 0
    assert "Caliper executive summary" in result.stdout or "No actionable" in result.stdout


def test_audit_csv_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["audit", "--output-format", "csv", *_common(sessions, state, config)]
    )
    assert result.exit_code in {0, 1, 2}


def test_audit_markdown_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["audit", "--output-format", "markdown", *_common(sessions, state, config)]
    )
    assert result.exit_code in {0, 1, 2}
    assert "## Audit" in result.stdout or "Audit" in result.stdout


def test_audit_writes_to_output_file(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    out_file = tmp_path / "audit.json"
    result = runner.invoke(
        app,
        [
            "audit",
            "--output-format",
            "json",
            "--out",
            str(out_file),
            *_common(sessions, state, config),
        ],
    )
    assert result.exit_code in {0, 1, 2}
    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    assert "findings" in payload


def test_predict_markdown_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["predict", "--output-format", "markdown", *_common(sessions, state, config)]
    )
    assert result.exit_code == 0
    assert "Predictive analytics" in result.stdout


def test_predict_csv_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["predict", "--output-format", "csv", *_common(sessions, state, config)]
    )
    assert result.exit_code == 0


def test_recommend_json_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["recommend", "--output-format", "json", *_common(sessions, state, config)]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "recommendations" in payload
    assert "total_savings_usd" in payload


def test_recommend_table_format(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app, ["recommend", "--output-format", "table", *_common(sessions, state, config)]
    )
    assert result.exit_code == 0
    assert "Caliper - Recommendations" in result.stdout or "No actionable" in result.stdout


def test_audit_codes_filter_runs(tmp_path: Path):
    sessions, state, config = _setup(tmp_path)
    result = runner.invoke(
        app,
        [
            "audit",
            "--codes",
            "LONG_CONTEXT_MISFIRE,PROMPT_ROT",
            *_common(sessions, state, config),
        ],
    )
    assert result.exit_code in {0, 1, 2}
