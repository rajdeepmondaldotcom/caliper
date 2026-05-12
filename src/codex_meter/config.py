from __future__ import annotations

import datetime as dt
import os
import tomllib
from pathlib import Path

from codex_meter.models import RuntimeOptions
from codex_meter.pricing import normalize_service_tier
from codex_meter.timeutil import load_timezone, local_timezone, parse_datetime

USER_CONFIG = Path.home() / ".config" / "codex-meter" / "config.toml"
LOCAL_CONFIG = Path(".codex-meter.toml")


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
    end = parse_datetime(until, dt.datetime.now(tz=local_timezone()))
    if since:
        start = parse_datetime(since)
    elif days is not None:
        if days <= 0:
            raise ValueError("--days must be greater than 0")
        start = end - dt.timedelta(days=days)
    else:
        default_days = float(loaded.get("default_days", 30))
        if default_days <= 0:
            raise ValueError("default_days must be greater than 0")
        start = end - dt.timedelta(days=default_days)
    if start >= end:
        raise ValueError("--since/--start must be before --until/--end")

    timezone_value = str(cfg(loaded, "timezone", timezone, "local"))
    load_timezone(timezone_value)
    pricing_mode_value = validate_choice(
        "--pricing-mode",
        str(cfg(loaded, "pricing_mode", pricing_mode, "model")),
        {"flat", "model"},
    )
    service_tier_value = str(cfg(loaded, "service_tier", service_tier, "auto"))
    if service_tier_value != "auto":
        service_tier_value = normalize_service_tier(service_tier_value)
    service_tier_value = validate_choice(
        "--service-tier",
        service_tier_value,
        {"auto", "fast", "standard"},
    )
    unknown_service_tier_value = str(
        cfg(loaded, "unknown_service_tier", unknown_service_tier, "current-config")
    )
    if unknown_service_tier_value != "current-config":
        unknown_service_tier_value = normalize_service_tier(unknown_service_tier_value)
    unknown_service_tier_value = validate_choice(
        "--unknown-service-tier",
        unknown_service_tier_value,
        {"current-config", "fast", "standard"},
    )
    top_threads_value = int(cfg(loaded, "top_threads", top_threads, 10))
    if top_threads_value <= 0:
        raise ValueError("--top-threads must be greater than 0")
    width_value = cfg(loaded, "width", width, None)
    if width_value is not None:
        width_value = int(width_value)
        if width_value <= 0:
            raise ValueError("--width must be greater than 0")
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
