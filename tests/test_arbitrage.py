from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper.arbitrage import explain, recommend, suggest
from caliper.arbitrage_rules import HEURISTICS_VERSION
from caliper.cli import app
from caliper.models import ThreadMeta, Usage, UsageEvent
from caliper.pricing import RateCard

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


def test_recommendations_group_repeated_events_and_estimate_savings() -> None:
    rows = recommend([_event(), _event()], RateCard.load(None, "model"))

    assert rows
    top = rows[0]
    assert top.events == 2
    assert top.sessions == 1
    assert top.next_command.startswith("caliper whatif")
    assert top.examples
    assert "heuristics_version" in top.to_record()


# ---------------------------------------------------------------------------
# Catalog-driven target selection — recommendations should follow the rate
# card, not a hard-coded list. New cheap models land in the catalog and
# start being recommended without changes to this file.
# ---------------------------------------------------------------------------


def test_recommendation_for_opus_ranks_active_alternatives() -> None:
    """Model recommendations are ranked by active rate-card repricing."""
    rows = recommend(
        [_event(model="claude-opus-4.7", tier="standard")] * 2,
        RateCard.load(None, "model"),
    )
    model_rows = [row for row in rows if row.target_model]
    assert model_rows
    top = model_rows[0]
    assert top.target_model == "claude-sonnet-4.6"
    assert top.alternatives
    targets = [item.model for item in top.alternatives]
    assert targets[0] == "claude-sonnet-4.6"
    assert "gpt-5.4" in targets
    assert "claude-haiku-4.5" not in targets
    assert "claude-3-haiku" not in top.detail
    assert "Test current alternatives:" in top.detail


def test_recommendation_for_sonnet_prefers_cheapest_ranked_model() -> None:
    rows = recommend(
        [_event(model="claude-sonnet-4.6", tier="standard")] * 2,
        RateCard.load(None, "model"),
    )
    targets = {row.target_model for row in rows if row.target_model}
    assert "gpt-5.4" in targets


def test_recommendation_can_cross_vendors_from_haiku() -> None:
    rows = recommend(
        [_event(model="claude-haiku-4.5", tier="standard")] * 2,
        RateCard.load(None, "model"),
    )
    targets = {row.target_model for row in rows if row.target_model}
    assert "gpt-5.4-mini" in targets


def test_recommendation_skips_when_no_cheaper_priced_model_exists() -> None:
    rows = recommend(
        [_event(model="gpt-5.4-mini", tier="standard")] * 2,
        RateCard.load(None, "model"),
    )
    assert all(row.target_model == "" for row in rows)


def test_recommendation_for_gpt55_picks_gpt54_first() -> None:
    """GPT-5.4 is the current cheaper capable alternative for this shape."""
    rows = recommend(
        [_event(model="gpt-5.5", tier="standard")] * 2,
        RateCard.load(None, "model"),
    )
    targets = {row.target_model for row in rows if row.target_model}
    assert "gpt-5.4" in targets


def test_candidate_roster_is_capped_and_memoised_on_card() -> None:
    """Regression guard for the dashboard "Building · signals" hang.

    A large network catalog must not make the advisor reprice every event
    against every model. The candidate roster is capped to the cheapest
    ``_MAX_CANDIDATE_MODELS`` and memoised on the rate card, and per-event
    alternatives are cached per token shape so the build's repeated
    repricing passes collapse into one computation per shape.
    """
    import dataclasses

    from caliper.arbitrage import (
        _MAX_CANDIDATE_MODELS,
        _candidate_model_names,
        model_alternatives_for_event,
    )
    from caliper.pricing import MODELS_BY_NAME

    card = RateCard.load(None, "model")
    # Inflate the catalog far beyond the cap by cloning real priced cards.
    real = dict(MODELS_BY_NAME)
    base_names = list(real)
    inflated = dict(real)
    for i in range(120):
        inflated[f"sim-model-{i}"] = real[base_names[i % len(base_names)]]

    import caliper.arbitrage as arb_mod

    original = arb_mod.MODELS_BY_NAME
    arb_mod.MODELS_BY_NAME = inflated
    try:
        roster = _candidate_model_names(card)
        assert len(roster) <= _MAX_CANDIDATE_MODELS
        # Memoised: a second call returns the identical cached tuple.
        assert _candidate_model_names(card) is roster
        assert card._arbitrage_candidate_cache  # populated

        # Per-event alternatives are cached by token shape on the card.
        event = _event(model="claude-opus-4-7", tier="standard")
        first = model_alternatives_for_event(event, card, limit=3)
        assert card._arbitrage_alt_cache  # populated
        # A second event with an identical shape reuses the cached ranking.
        twin = dataclasses.replace(event, session_id="other-session")
        before = len(card._arbitrage_alt_cache)
        again = model_alternatives_for_event(twin, card, limit=3)
        assert again == first
        assert len(card._arbitrage_alt_cache) == before  # no new entry
    finally:
        arb_mod.MODELS_BY_NAME = original


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
    assert payload["recommendations"]
    assert payload["record_count"] == len(payload["records"])
