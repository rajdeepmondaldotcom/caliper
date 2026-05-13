from __future__ import annotations

import datetime as dt
import os
import tomllib
from pathlib import Path

from caliper.models import RuntimeOptions
from caliper.pricing import normalize_service_tier
from caliper.timeutil import load_timezone, local_timezone, parse_datetime

USER_CONFIG = Path.home() / ".config" / "caliper" / "config.toml"
LOCAL_CONFIG = Path(".caliper.toml")


def default_codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def default_session_root() -> Path:
    return default_codex_home() / "sessions"


def default_state_db() -> Path:
    return default_codex_home() / "state_5.sqlite"


def default_codex_config() -> Path:
    return default_codex_home() / "config.toml"


def load_config(explicit_path: Path | None = None) -> dict:
    paths = [USER_CONFIG, LOCAL_CONFIG]
    if explicit_path:
        paths.append(explicit_path)
    loaded: dict = {}
    for path in paths:
        if path is None:
            continue
        expanded = path.expanduser()
        if not expanded.exists():
            continue
        try:
            loaded |= tomllib.loads(expanded.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Could not load config {expanded}: {exc}") from exc
    return loaded


def cfg(config: dict, key: str, value, default):
    if value != default:
        return value
    return config.get(key, default)


def cfg_path(config: dict, key: str, value: Path | None, default: Path) -> Path:
    if value is not None:
        return Path(value).expanduser()
    return Path(config.get(key, default)).expanduser()


def cfg_optional_path(config: dict, key: str, value: Path | None) -> Path | None:
    if value is not None:
        return Path(value).expanduser()
    configured = config.get(key)
    return Path(configured).expanduser() if configured else None


def cfg_bool(config: dict, key: str, value: bool, default: bool) -> bool:
    if value != default:
        return bool(value)
    return bool(config.get(key, default))


def validate_choice(name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def build_options(
    *,
    since: str | None = None,
    until: str | None = None,
    days: float | None = None,
    timezone: str = "local",
    session_root: Path | None = None,
    state_db: Path | None = None,
    codex_config: Path | None = None,
    config: Path | None = None,
    pricing_mode: str = "model",
    service_tier: str = "auto",
    unknown_service_tier: str = "current-config",
    tier_overrides: Path | None = None,
    rates_file: Path | None = None,
    no_dedupe: bool = False,
    no_parse_cache: bool = False,
    default_model: str = "gpt-5.5",
    show_prompts: bool = False,
    offline: bool = True,
    compact: bool = False,
    width: int | None = None,
    top_threads: int = 10,
) -> RuntimeOptions:
    loaded = load_config(config)
    start, end = _time_window(loaded, since=since, until=until, days=days)

    timezone_value = str(cfg(loaded, "timezone", timezone, "local"))
    load_timezone(timezone_value)
    pricing_mode_value = validate_choice(
        "--pricing-mode",
        str(cfg(loaded, "pricing_mode", pricing_mode, "model")),
        {"flat", "model"},
    )
    service_tier_value = _service_tier(loaded, service_tier)
    unknown_service_tier_value = _unknown_service_tier(loaded, unknown_service_tier)
    top_threads_value = _positive_int(
        cfg(loaded, "top_threads", top_threads, 10),
        "--top-threads",
    )
    width_value = _positive_optional_int(cfg(loaded, "width", width, None), "--width")
    no_dedupe_value = cfg_bool(loaded, "no_dedupe", no_dedupe, False)
    no_parse_cache_value = cfg_bool(loaded, "no_parse_cache", no_parse_cache, False)

    return RuntimeOptions(
        session_root=cfg_path(loaded, "session_root", session_root, default_session_root()),
        state_db=cfg_path(loaded, "state_db", state_db, default_state_db()),
        config_path=cfg_path(loaded, "codex_config", codex_config, default_codex_config()),
        start=start,
        end=end,
        timezone=timezone_value,
        pricing_mode=pricing_mode_value,
        service_tier=service_tier_value,
        unknown_service_tier=unknown_service_tier_value,
        tier_overrides=cfg_optional_path(loaded, "tier_overrides", tier_overrides),
        rates_file=cfg_optional_path(loaded, "rates_file", rates_file),
        dedupe=not no_dedupe_value,
        parse_cache=not no_parse_cache_value,
        default_model=str(cfg(loaded, "default_model", default_model, "gpt-5.5")),
        show_prompts=cfg_bool(loaded, "show_prompts", show_prompts, False),
        offline=cfg_bool(loaded, "offline", offline, True),
        compact=cfg_bool(loaded, "compact", compact, False),
        width=width_value,
        top_threads=top_threads_value,
    )


def _time_window(
    loaded: dict,
    *,
    since: str | None,
    until: str | None,
    days: float | None,
) -> tuple[dt.datetime, dt.datetime]:
    end = parse_datetime(until, dt.datetime.now(tz=local_timezone()))
    start = _start_time(loaded, since=since, days=days, end=end)
    if start >= end:
        raise ValueError("--since/--start must be before --until/--end")
    return start, end


def _start_time(
    loaded: dict,
    *,
    since: str | None,
    days: float | None,
    end: dt.datetime,
) -> dt.datetime:
    if since:
        return parse_datetime(since)
    if days is not None:
        if days <= 0:
            raise ValueError("--days must be greater than 0")
        return end - dt.timedelta(days=days)
    default_days = float(loaded.get("default_days", 30))
    if default_days <= 0:
        raise ValueError("default_days must be greater than 0")
    return end - dt.timedelta(days=default_days)


def _service_tier(loaded: dict, value: str) -> str:
    tier = str(cfg(loaded, "service_tier", value, "auto"))
    if tier != "auto":
        tier = normalize_service_tier(tier)
    return validate_choice("--service-tier", tier, {"auto", "fast", "standard"})


def _unknown_service_tier(loaded: dict, value: str) -> str:
    tier = str(cfg(loaded, "unknown_service_tier", value, "current-config"))
    if tier != "current-config":
        tier = normalize_service_tier(tier)
    return validate_choice(
        "--unknown-service-tier",
        tier,
        {"current-config", "fast", "standard"},
    )


def _positive_int(value, name: str) -> int:
    coerced = int(value)
    if coerced <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return coerced


def _positive_optional_int(value, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)
