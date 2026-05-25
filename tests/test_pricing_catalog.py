from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import pytest

from caliper import network
from caliper import pricing_catalog as pc
from caliper.models import Usage
from caliper.pricing import RateCard, available_model_names, pricing_catalog_status
from caliper.timeutil import iso_z


def _record(name: str = "vendor/model-one") -> dict[str, Any]:
    return {
        "name": name,
        "provider": "provider-a",
        "source": "unit",
        "source_url": "https://example.test/prices.json",
        "api": {
            "input": "2",
            "cached_input": "0.2",
            "output": "8",
            "reasoning_output": "9",
            "cache_creation_input": "2.5",
            "cache_creation_input_1h": "4",
        },
        "long_context": {"threshold": 128000, "input_mult": 2, "output_mult": 1.5},
        "context_window": 128000,
        "max_output_tokens": 8192,
        "aliases": ["model-one-alias", "openrouter/provider-a/model-one"],
        "additional_units": {"audio": "1.25"},
    }


def _payload(fetched_at: dt.datetime | None = None) -> dict[str, Any]:
    return {
        "schema_version": pc.CATALOG_SCHEMA_VERSION,
        "source": "cache",
        "fetched_at": iso_z(fetched_at or dt.datetime.now(tz=dt.UTC)),
        "warnings": ["kept"],
        "models": [
            _record(),
            {"name": ""},
            "not-a-record",
        ],
    }


def test_pricing_catalog_path_prefers_local_data_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert pc.pricing_catalog_path() == tmp_path / "data" / "rates-fetched.json"

    monkeypatch.delenv("CALIPER_DATA_DIR")
    assert pc.pricing_catalog_path() == tmp_path / "xdg" / "caliper" / "rates-fetched.json"


def test_cache_round_trip_and_catalog_records(tmp_path) -> None:
    cache = tmp_path / "rates.json"
    cache.write_text(json.dumps(_payload()))

    catalog = pc.load_cached_catalog(cache)

    assert catalog.source == "cache"
    assert catalog.path == cache
    assert catalog.warnings == ("kept",)
    assert catalog.model_count == 1
    assert {"model-one", "model-one-alias"} <= pc.available_catalog_models(catalog)
    assert {"model-one", "model-one-alias"} <= set(catalog.models)

    model = catalog.models["model-one"]
    assert model.api_rates is not None
    assert model.api_rates.input == Decimal("2")
    assert model.api_rates.cache_creation_input_1h == Decimal("4")
    assert model.long_context is not None
    assert model.long_context.threshold == 128000
    assert model.context_window == 128000
    assert model.additional_units == {"audio": Decimal("1.25")}

    records = pc.catalog_model_records(catalog)
    assert records == [
        {
            "provider": "provider-a",
            "model": "model-one",
            "api_input": "2",
            "api_cached_input": "0.2",
            "api_output": "8",
            "context_window": 128000,
            "max_output_tokens": 8192,
            "source": "unit",
        }
    ]


def test_cache_error_and_malformed_payload_paths(tmp_path) -> None:
    missing = pc.load_cached_catalog(tmp_path / "missing.json")
    assert missing.models == {}
    assert "cache unavailable" in missing.warnings[0]

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{")
    assert pc.load_cached_catalog(bad_json).models == {}

    catalog = pc.catalog_from_payload({"models": "bad", "fetched_at": "not-a-date"})
    assert catalog.models == {}
    assert catalog.fetched_at is None


def test_load_pricing_catalog_offline_and_refresh(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "rates.json"
    old = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=3)
    old_payload = _payload(old)
    old_payload["models"] = [_record("old-model")]
    cache.write_text(json.dumps(old_payload))

    assert pc.load_pricing_catalog(pricing_source="embedded").source == "embedded"
    assert pc.load_pricing_catalog(offline=True, path=cache).models
    assert pc.load_pricing_catalog(offline=False, path=cache, ttl_hours=999).source == "cache"

    fresh_payload = _payload()
    fresh_payload["source"] = "auto"
    fresh_payload["models"] = [_record("new-model")]

    def fetch(source: str) -> dict[str, Any]:
        assert source == "auto"
        return fresh_payload

    monkeypatch.setattr(pc, "fetch_pricing_catalog", fetch)
    refreshed = pc.load_pricing_catalog(offline=False, path=cache, ttl_hours=1)

    assert refreshed.source == "auto"
    saved = json.loads(cache.read_text())
    saved_names = {model["name"] for model in saved["models"]}
    assert saved["source"] == "auto"
    assert saved_names == {"new-model"}
    assert "old-model" not in refreshed.models
    assert "new-model" in refreshed.models


def test_load_pricing_catalog_refresh_failure_keeps_cache(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "rates.json"
    cache.write_text(json.dumps(_payload(dt.datetime(2020, 1, 1, tzinfo=dt.UTC))))

    def explode(_source: str) -> dict[str, Any]:
        raise OSError("offline")

    monkeypatch.setattr(pc, "fetch_pricing_catalog", explode)

    with_cache = pc.load_pricing_catalog(offline=False, path=cache, ttl_hours=1)
    assert with_cache.models
    assert any("refresh failed" in warning for warning in with_cache.warnings)

    empty_cache = tmp_path / "empty.json"
    empty = pc.load_pricing_catalog(offline=False, path=empty_cache, ttl_hours=1)
    assert empty.models == {}
    assert any("refresh failed" in warning for warning in empty.warnings)


def test_load_pricing_catalog_empty_refresh_keeps_cache(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "rates.json"
    cache.write_text(json.dumps(_payload(dt.datetime(2020, 1, 1, tzinfo=dt.UTC))))

    monkeypatch.setattr(
        pc,
        "fetch_pricing_catalog",
        lambda _source: {"source": "auto", "models": [], "warnings": ["all sources failed"]},
    )

    catalog = pc.load_pricing_catalog(offline=False, path=cache, ttl_hours=1)

    assert catalog.models
    assert any("all sources failed" in warning for warning in catalog.warnings)
    assert json.loads(cache.read_text())["models"]


def test_fetch_pricing_catalog_composes_selected_sources(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(pc, "_fetch_portkey_records", lambda: ([_record("gpt-5-5")], [{"p": 1}]))
    monkeypatch.setattr(
        pc,
        "_fetch_litellm_records",
        lambda: (
            [_record("litellm-model") | {"source": "litellm", "provider": "litellm"}],
            {"l": 1},
        ),
    )

    auto = pc.fetch_pricing_catalog("auto")
    assert auto["source"] == "auto"
    assert auto["model_count"] == 2
    assert len(auto["sources"]) == 2

    calls.append(pc.fetch_pricing_catalog("portkey")["source"])
    calls.append(pc.fetch_pricing_catalog("litellm")["source"])
    assert calls == ["portkey", "litellm"]

    with pytest.raises(ValueError, match="pricing source"):
        pc.fetch_pricing_catalog("unknown")


def test_fetch_helpers_and_network_validation(monkeypatch) -> None:
    calls: list[str] = []
    real_fetch_json = pc._fetch_json
    real_fetch_text = pc._fetch_text

    def fake_json(url: str) -> Any:
        calls.append(url)
        if "openai" in url and "configs" in url:
            return {
                "gpt-5-5": {
                    "pricing_config": {
                        "pay_as_you_go": {
                            "request_token": {"price": "0.0005"},
                            "response_token": {"price": "0.001"},
                        }
                    }
                }
            }
        if "anthropic" in url and "configs" in url:
            raise OSError("try fallback")
        if "anthropic" in url:
            return {"models": [{"name": "anthropic.claude-haiku-4-5", "input": 1, "output": 5}]}
        raise OSError("missing")

    monkeypatch.setattr(pc, "_fetch_json", fake_json)
    records, sources = pc._fetch_portkey_records()
    assert {record["name"] for record in records} == {"gpt-5-5", "claude-haiku-4-5"}
    assert any(source["status"] == "error" for source in sources)
    assert any(urlparse(call).netloc == "raw.githubusercontent.com" for call in calls)

    nullable = pc._records_from_portkey(
        "openai",
        {"model-without-price": {"pricing_config": None}},
        "https://example.test/prices.json",
    )
    assert nullable == [
        {
            "name": "model-without-price",
            "provider": "openai",
            "source": "portkey",
            "source_url": "https://example.test/prices.json",
            "api": None,
            "additional_units": {},
        }
    ]

    assert (
        pc._long_context_from_litellm(
            {
                "input_cost_per_token": 0,
                "output_cost_per_token": 0,
                "input_cost_per_token_above_128k_tokens": 0,
                "output_cost_per_token_above_128k_tokens": 0,
            }
        )
        is None
    )

    monkeypatch.setattr(pc, "_fetch_json", lambda _url: {"m": {"input_cost_per_token": 1e-6}})
    litellm_records, litellm_source = pc._fetch_litellm_records()
    assert litellm_records == []
    assert litellm_source["status"] == "ok"

    monkeypatch.setattr(pc, "_fetch_json", lambda _url: (_ for _ in ()).throw(OSError("down")))
    assert pc._fetch_litellm_records()[1]["status"] == "error"

    monkeypatch.setattr(pc, "_fetch_json", real_fetch_json)
    monkeypatch.setattr(pc, "_fetch_text", lambda _url: '{"ok": true}')
    assert pc._fetch_json("https://example.test/json") == {"ok": True}
    monkeypatch.setattr(pc, "_fetch_text", lambda _url: "{")
    with pytest.raises(OSError, match="invalid JSON"):
        pc._fetch_json("https://example.test/json")
    monkeypatch.setattr(pc, "_fetch_text", real_fetch_text)
    with pytest.raises(OSError, match="unsupported"):
        pc._fetch_text("file:///tmp/prices.json")


def test_urlopen_fetch_text(monkeypatch) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"hello"

    def fake_urlopen(request: object, timeout: int) -> Response:
        assert timeout == 5
        assert "caliper/" in str(getattr(request, "headers", {}))
        return Response()

    monkeypatch.setattr(network.urllib.request, "urlopen", fake_urlopen)
    assert pc._fetch_text("https://example.test/prices") == "hello"


def test_fetch_text_retries_403_with_browser_user_agent(monkeypatch) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    user_agents: list[str] = []

    def fake_urlopen(request: object, timeout: int) -> Response:
        assert timeout == 5
        user_agent = str(getattr(request, "headers", {}).get("User-agent", ""))
        user_agents.append(user_agent)
        if len(user_agents) == 1:
            raise network.urllib.error.HTTPError(
                "https://example.test/prices", 403, "Forbidden", hdrs=None, fp=None
            )
        return Response()

    monkeypatch.setattr(network.urllib.request, "urlopen", fake_urlopen)

    assert pc._fetch_text("https://example.test/prices") == "ok"
    assert user_agents[0].startswith("caliper/")
    assert user_agents[1].startswith("Mozilla/")


def test_record_normalizers_cover_provider_shapes() -> None:
    portkey_raw = {
        "default": {},
        "skip": {},
        "with-prices": {
            "pricing_config": {
                "pay_as_you_go": {
                    "request_token": {"price": "0.0005"},
                    "response_token": {"price": "0.001"},
                    "cache_read_input_token": {"price": "0.00005"},
                    "cache_write_input_token": {"price": "0.000625"},
                    "additional_units": {
                        "cache_write_1h": {"price": "0.001"},
                        "thinking_token": {"price": "0.002"},
                        "ignored": {},
                    },
                }
            }
        },
    }
    portkey_records = pc._records_from_portkey("openai", portkey_raw, "https://example.test")
    assert len(portkey_records) == 1
    assert portkey_records[0]["api"]["input"] == "5.0000"
    assert portkey_records[0]["api"]["cache_creation_input_1h"] == "10.000"
    assert portkey_records[0]["additional_units"] == {
        "cache_write_1h": "10.000",
        "thinking_token": "20.000",
    }
    assert pc._records_from_portkey(
        "openai",
        {"models": [{"name": "m", "input": 1, "output": 2}]},
        "u",
    )
    assert pc._records_from_portkey("openai", "bad", "u") == []
    assert pc._rates_from_portkey({"pricing_config": {"pay_as_you_go": []}}) is None

    litellm_raw = {
        "sample_spec": {},
        "bad": {"input_cost_per_token": 1e-6},
        "model/gpt-5-5-latest": {
            "litellm_provider": "openai",
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.000008,
            "cache_read_input_token_cost": 0.0000002,
            "output_cost_per_reasoning_token": 0.000009,
            "cache_creation_input_token_cost": 0.0000025,
            "cache_creation_input_token_cost_above_1hr": 0.000004,
            "input_cost_per_token_above_128k_tokens": 0.000004,
            "output_cost_per_token_above_128k_tokens": 0.000012,
            "max_input_tokens": "128000",
            "max_output_tokens": "8192",
        },
    }
    litellm_records = pc._records_from_litellm(litellm_raw, "https://example.test")
    assert litellm_records[0]["name"] == "gpt-5-5-latest"
    assert litellm_records[0]["api"]["reasoning_output"] == "9.000000"
    assert litellm_records[0]["long_context"] == {
        "threshold": 128000,
        "input_mult": 2.0,
        "output_mult": 1.5,
    }
    assert pc._records_from_litellm("bad", "u") == []
    assert pc._long_context_from_litellm({}) is None


def test_generic_records_and_merge_helpers() -> None:
    generic = pc._generic_model_records(
        "provider",
        [
            {},
            {"name": "models/provider/model_a", "input": 1, "cached_input": 0.1, "output": 2},
            {"name": "no-rates"},
        ],
        "source",
        "https://example.test",
    )
    assert [record["name"] for record in generic] == ["model-a", "no-rates"]
    assert generic[0]["api"]["cached_input"] == "0.1"
    assert generic[1]["api"] is None

    merged = pc._merge_model_records(
        [
            {"name": "openrouter/openai/gpt-5-5", "source": "portkey", "api": {"input": "1"}},
            {
                "name": "gpt-5.5",
                "source": "litellm",
                "provider": "openai",
                "context_window": 400000,
            },
        ],
        prefer="litellm",
    )
    assert merged[0]["name"] == "gpt-5.5"
    assert merged[0]["api"] == {"input": "1"}
    assert merged[0]["context_window"] == 400000


def test_payload_name_datetime_and_validation_helpers() -> None:
    assert pc._rates_from_payload({"input": "", "output": "1"}) is None
    assert pc._rates_from_payload("bad") is None
    assert pc._long_context_from_payload({}) is None
    assert pc._rates_payload(None) is None
    assert pc._portkey_price({}) is None
    assert pc._portkey_price({"price": "not-a-number"}) is None
    assert pc._litellm_price(None) is None
    assert pc._litellm_price("not-a-number") is None
    assert pc._rates_from_payload({"input": "not-a-number", "output": "1"}) is None
    assert (
        pc._long_context_from_payload({"threshold": "128000", "input_mult": "not-a-number"}) is None
    )

    assert pc._clean_model_name("global.anthropic.claude-haiku-4-5") == "claude-haiku-4-5"
    assert pc._model_keys("openrouter/openai/gpt-5-5", "bedrock/anthropic.claude-opus-4-1") == (
        "gpt-5.5",
        "gpt-5-5",
        "openrouter/openai/gpt-5-5",
        "claude-opus-4.1",
        "claude-opus-4-1",
    )
    assert pc._canonical_model_name("claude-sonnet-4-6-20260201") == ("claude-sonnet-4.6-20260201")
    assert pc._normal_text("<b>a</b>&nbsp;b\u2014c") == "a b-c"
    assert pc._parse_datetime("") is None
    assert pc._parse_datetime("2026-05-13T00:00:00") is not None
    assert pc._safe_int("bad") == 0
    assert pc._validate_pricing_source(" PORTKEY ") == "portkey"
    assert pc._empty_payload("embedded")["models"] == []


def test_pricing_catalog_edge_branches() -> None:
    empty_catalog = pc.PricingCatalog(fetched_at=None, source="unit", models={})
    assert pc.catalog_is_stale(empty_catalog, ttl_hours=24) is True
    assert pc.catalog_age_hours(empty_catalog) is None
    assert pc.fetch_pricing_catalog("embedded")["source"] == "embedded"

    assert pc._rates_from_portkey({}) is None
    assert pc._rates_from_portkey({"pricing_config": {"pay_as_you_go": []}}) is None
    assert (
        pc._rates_from_portkey(
            {"pricing_config": {"pay_as_you_go": {"request_token": {"price": "0.1"}}}}
        )
        is None
    )
    portkey_rates = pc._rates_from_portkey(
        {
            "pricing_config": {
                "pay_as_you_go": {
                    "request_token": {"price": "0.1"},
                    "response_token": {"price": "0.2"},
                    "additional_units": [],
                }
            }
        }
    )
    assert portkey_rates is not None
    assert portkey_rates.cached_input == portkey_rates.input

    assert pc._rates_from_litellm({"input_cost_per_token": 1e-6}) is None
    litellm_rates = pc._rates_from_litellm(
        {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 2e-6,
            "input_cost_per_token_cache_hit": 0.5e-6,
        }
    )
    assert litellm_rates is not None
    assert litellm_rates.cached_input == Decimal("0.5000000")
    assert pc._long_context_from_litellm(
        {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 2e-6,
            "output_cost_per_token_above_200k_tokens": 4e-6,
        }
    ) == {"threshold": 200000, "input_mult": 1.0, "output_mult": 2.0}
    assert (
        pc._long_context_from_litellm({"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6})
        is None
    )

    assert pc._additional_units_from_portkey({}) == {}
    assert pc._additional_units_from_portkey({"pricing_config": {"pay_as_you_go": []}}) == {}
    assert (
        pc._additional_units_from_portkey(
            {"pricing_config": {"pay_as_you_go": {"additional_units": []}}}
        )
        == {}
    )

    merged = pc._merge_model_records(
        [
            {"name": "", "source": "portkey"},
            {"name": "gpt-5-5", "source": "litellm", "context_window": 10},
            {"name": "gpt-5.5", "source": "portkey", "api": {"input": "1"}},
        ],
        prefer="portkey",
    )
    assert merged[0]["source"] == "portkey"
    assert merged[0]["context_window"] == 10
    assert pc._merge_record(
        {"name": "x"}, {"aliases": ["x", "y"], "api": {"input": "1"}}, ("base", "z")
    )["aliases"] == ["base", "y", "z"]

    model = pc._catalog_model_from_record({"name": "models/vendor/model_a", "additional_units": []})
    assert model.name == "model-a"
    assert model.additional_units == {}

    minimal_payload = pc._rates_payload(pc.Rates("1", "1", "2"))
    assert minimal_payload is not None
    assert minimal_payload["reasoning_output"] is None
    assert pc._clean_model_name("openrouter/openai/gpt-5-5") == "openrouter/openai/gpt-5-5"
    assert pc._clean_model_name("vendor/model_a") == "model-a"
    assert pc._model_keys("", "bedrock/anthropic.claude-opus-4-1") == (
        "claude-opus-4.1",
        "claude-opus-4-1",
    )
    assert pc._canonical_model_name("unlisted-model") == "unlisted-model"
    assert pc._parse_datetime("not-a-date") is None
    assert pc._safe_int(object()) == 0


def test_rate_card_uses_catalog_models(monkeypatch) -> None:
    catalog = pc.catalog_from_payload(_payload())
    card = RateCard.load(None, catalog=catalog)
    usage = Usage(input_tokens=1000, output_tokens=100, total_tokens=1100)

    cost, long_context, unknown = card.cost_for(usage, "model-one", "standard")

    assert unknown is False
    assert long_context is False
    assert cost.cost_usd == Decimal("0.0028")
    assert pricing_catalog_status(card)["models"] == 1
    assert pricing_catalog_status(RateCard.load(None))["source"] == "embedded"

    monkeypatch.setattr(pc, "load_cached_catalog", lambda: catalog)
    monkeypatch.setattr("caliper.pricing.load_cached_catalog", lambda: catalog)
    assert "model-one" in available_model_names()
    assert "gpt-5.5" in available_model_names(include_cached_catalog=False)


def test_rate_card_from_options_loads_catalog(monkeypatch, tmp_path) -> None:
    from caliper.config import build_options

    catalog = pc.catalog_from_payload(_payload())

    def load_catalog(**kwargs: object) -> pc.PricingCatalog:
        assert kwargs["pricing_source"] == "embedded"
        assert kwargs["ttl_hours"] == 12
        assert kwargs["offline"] is True
        return catalog

    monkeypatch.setattr("caliper.pricing.load_pricing_catalog", load_catalog)
    options = build_options(
        days=1,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
        pricing_source="embedded",
        pricing_cache_ttl_hours=12,
    )

    card = RateCard.from_options(options)

    assert card.pricing_catalog is catalog
    assert card.catalog_cards["model-one"].api_rates is not None


def test_rate_card_from_options_is_cache_only_even_when_online(monkeypatch) -> None:
    from caliper.config import build_options

    calls: list[bool] = []

    def load_catalog(**kwargs: object) -> pc.PricingCatalog:
        calls.append(bool(kwargs["offline"]))
        return pc.PricingCatalog(fetched_at=None, source="auto", models={})

    monkeypatch.setattr("caliper.pricing.load_pricing_catalog", load_catalog)
    options = build_options(days=1, pricing_source="auto", offline=False)

    RateCard.from_options(options)

    assert calls == [True]


def test_live_catalog_rates_override_embedded_known_models() -> None:
    payload = {
        "schema_version": pc.CATALOG_SCHEMA_VERSION,
        "source": "unit",
        "fetched_at": iso_z(dt.datetime.now(tz=dt.UTC)),
        "models": [
            {
                "name": "gpt-5.5",
                "provider": "openai",
                "source": "unit",
                "api": {"input": "9", "cached_input": "0.9", "output": "90"},
            }
        ],
    }
    card = RateCard.load(None, catalog=pc.catalog_from_payload(payload))
    usage = Usage(input_tokens=100_000, output_tokens=0, total_tokens=100_000)

    cost, _long_context, unknown = card.cost_for(usage, "gpt-5.5", "fast")

    assert unknown is False
    assert cost.cost_usd == Decimal("2.25")
    assert cost.calculated_cost_usd == Decimal("2.25")
