from __future__ import annotations

import json
from io import BytesIO

from typer.testing import CliRunner

from codex_meter.cli import app
from codex_meter.models import Usage
from codex_meter.pricing import MODEL_CARDS, MODELS_BY_NAME, estimate_event_cost

runner = CliRunner()


def test_rates_show_table_lists_every_model() -> None:
    result = runner.invoke(app, ["rates", "show"])
    assert result.exit_code == 0, result.output
    assert "Codex Meter - Rate Card" in result.output
    for card in MODEL_CARDS:
        assert card.name[:12] in result.output


def test_rates_show_json_schema() -> None:
    result = runner.invoke(app, ["rates", "show", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {"checked", "age_days", "stale", "models"} <= set(payload.keys())
    assert len(payload["models"]) == len(MODEL_CARDS)
    gpt55 = next(model for model in payload["models"] if model["name"] == "gpt-5.5")
    assert gpt55["fast_multiplier"] == 2.5
    assert gpt55["long_context"]["threshold"] == 272_000
    assert gpt55["api"]["reasoning_output"] == gpt55["api"]["output"]
    gpt54 = next(model for model in payload["models"] if model["name"] == "gpt-5.4")
    assert gpt54["long_context"] is None
    max_card = next(model for model in payload["models"] if model["name"] == "gpt-5.1-codex-max")
    assert max_card["api"]["input"] == 1.25
    assert max_card["api"]["cached_input"] == 0.125
    assert max_card["api"]["output"] == 10.0


def test_rates_show_markdown() -> None:
    result = runner.invoke(app, ["rates", "show", "--format", "markdown"])
    assert result.exit_code == 0, result.output
    assert "| model | fast_multiplier | api_input | credits_input |" in result.output


def test_rates_show_bad_format_reports_choices() -> None:
    result = runner.invoke(app, ["rates", "show", "--format", "xml"])
    assert result.exit_code == 2
    assert "table, json" in result.output


def test_rates_refresh_requires_explicit_network_opt_in() -> None:
    result = runner.invoke(app, ["rates", "refresh"])
    assert result.exit_code == 2
    assert "needs --allow-network" in result.output


def test_rates_refresh_allow_network_writes_sidecar(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_METER_DATA_DIR", str(tmp_path))

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(_request, timeout):
        assert timeout == 5
        return Response(b'{"models":[{"name":"gpt-5.5","input":5}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = runner.invoke(app, ["rates", "refresh", "--allow-network"])
    assert result.exit_code == 0, result.output
    target = tmp_path / "rates-fetched.json"
    assert target.exists()
    payload = json.loads(target.read_text())
    assert payload["models"][0]["name"] == "gpt-5.5"
    assert payload["observed_models"][0]["name"] == "gpt-5.5"
    assert any(model["name"] == "gpt-5.1-codex-max" for model in payload["embedded_models"])
    assert "discrepancies" in payload
    assert len(payload["sources"]) >= 1


def test_rates_file_override_with_reasoning_field(tmp_path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "api": {
                    "gpt-5.5": {
                        "input": 1.0,
                        "cached_input": 0.0,
                        "output": 10.0,
                        "reasoning_output": 100.0,
                    }
                }
            }
        )
    )
    usage = Usage(
        input_tokens=1000,
        output_tokens=1000,
        reasoning_output_tokens=1000,
        total_tokens=3000,
    )
    cost, _, _ = estimate_event_cost(usage, "gpt-5.5", "standard", "model", rates_path)
    # input 1000 × 1 + output 1000 × 10 + reasoning 1000 × 100 = 111,000 → /1M = 0.111
    assert round(cost.api_dollars, 6) == 0.111


def test_long_context_threshold_uses_model_card_value() -> None:
    """The 272K threshold lives on the gpt-5.5 ModelCard, not a global constant."""
    assert MODELS_BY_NAME["gpt-5.5"].long_context is not None
    threshold = MODELS_BY_NAME["gpt-5.5"].long_context.threshold
    just_under = Usage(input_tokens=threshold, output_tokens=10, total_tokens=threshold + 10)
    just_over = Usage(input_tokens=threshold + 1, output_tokens=10, total_tokens=threshold + 11)
    _, lc_under, _ = estimate_event_cost(just_under, "gpt-5.5", "standard", "model", None)
    _, lc_over, _ = estimate_event_cost(just_over, "gpt-5.5", "standard", "model", None)
    assert lc_under is False
    assert lc_over is True
