from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper.arbitrage import explain, suggest
from caliper.arbitrage_rules import HEURISTICS_VERSION
from caliper.cli import app
from caliper.models import ThreadMeta, Usage, UsageEvent

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _event(model: str = "gpt-5.5", tier: str = "fast") -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id="session",
        usage=Usage(input_tokens=1000, output_tokens=100, total_tokens=1100),
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(),
    )


def test_arbitrage_suggestions_include_rule_confidence_and_evidence() -> None:
    rows = suggest([_event()])

    assert rows
    assert rows[0].rule_id in {"premium-short-context", "fast-tier-low-output"}
    assert rows[0].confidence >= 0.6
    assert rows[0].evidence["model"] == "gpt-5.5"


def test_strict_threshold_filters_lower_confidence_rules() -> None:
    rows = suggest([_event()], threshold=0.8)

    assert all(row.confidence >= 0.8 for row in rows)


def test_explain_rule() -> None:
    payload = explain("premium-short-context")

    assert payload["heuristics_version"] == HEURISTICS_VERSION
    assert payload["rule_id"] == "premium-short-context"


def test_advise_cli_json(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-advise.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="fast"),
            token_event(now, {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    result = runner.invoke(
        app,
        [
            "advise",
            "--days",
            "1",
            "--until",
            (now + dt.timedelta(seconds=1)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--vendor",
            "openai-codex",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["records"]
