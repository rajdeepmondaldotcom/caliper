from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path

from codex_meter.models import RuntimeOptions
from codex_meter.timeutil import local_timezone, parse_datetime

DEFAULT_SESSION_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_STATE_DB = Path.home() / ".codex" / "state_5.sqlite"
DEFAULT_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
USER_CONFIG = Path.home() / ".config" / "codex-meter" / "config.toml"
LOCAL_CONFIG = Path(".codex-meter.toml")


def load_config(explicit_path: Path | None = None) -> dict:
    paths = [explicit_path] if explicit_path else [LOCAL_CONFIG, USER_CONFIG]
    for path in paths:
        if path is None:
            continue
        expanded = path.expanduser()
        if not expanded.exists():
            continue
        try:
            return tomllib.loads(expanded.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Could not load config {expanded}: {exc}") from exc
    return {}


def cfg(config: dict, key: str, default):
    return config.get(key, default)


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
    default_model: str = "gpt-5.5",
    show_prompts: bool = False,
    offline: bool = True,
    compact: bool = False,
    top_threads: int = 10,
) -> RuntimeOptions:
    loaded = load_config(config)
    end = parse_datetime(until, dt.datetime.now(tz=local_timezone()))
    if since:
        start = parse_datetime(since)
    elif days is not None:
        start = end - dt.timedelta(days=days)
    else:
        start = end - dt.timedelta(days=float(cfg(loaded, "default_days", 30)))
    if start >= end:
        raise ValueError("--since/--start must be before --until/--end")

    return RuntimeOptions(
        session_root=Path(
            cfg(loaded, "session_root", session_root or DEFAULT_SESSION_ROOT)
        ).expanduser(),
        state_db=Path(cfg(loaded, "state_db", state_db or DEFAULT_STATE_DB)).expanduser(),
        config_path=Path(
            cfg(loaded, "codex_config", codex_config or DEFAULT_CODEX_CONFIG)
        ).expanduser(),
        start=start,
        end=end,
        timezone=str(cfg(loaded, "timezone", timezone)),
        pricing_mode=str(cfg(loaded, "pricing_mode", pricing_mode)),
        service_tier=str(cfg(loaded, "service_tier", service_tier)),
        unknown_service_tier=str(cfg(loaded, "unknown_service_tier", unknown_service_tier)),
        tier_overrides=Path(tier_overrides).expanduser() if tier_overrides else None,
        rates_file=Path(rates_file).expanduser() if rates_file else None,
        dedupe=not no_dedupe,
        default_model=str(cfg(loaded, "default_model", default_model)),
        show_prompts=bool(cfg(loaded, "show_prompts", show_prompts)),
        offline=bool(cfg(loaded, "offline", offline)),
        compact=bool(cfg(loaded, "compact", compact)),
        top_threads=int(cfg(loaded, "top_threads", top_threads)),
    )
