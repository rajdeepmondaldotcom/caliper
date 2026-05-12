"""Codex session JSONL + state DB parser."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tomllib
from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path

from codex_meter.models import (
    LoadResult,
    RateLimitSample,
    RuntimeOptions,
    ThreadMeta,
    TierOverride,
    Usage,
    UsageEvent,
)
from codex_meter.parse_cache import ParseCache
from codex_meter.pricing import normalize_model, normalize_service_tier
from codex_meter.timeutil import parse_datetime, parse_event_timestamp

PARSER_CACHE_VERSION = 4


def session_files(session_root: Path) -> Iterable[Path]:
    if not session_root.exists():
        return []
    return sorted(session_root.glob("**/*.jsonl"))


def session_id_from_path(path: Path) -> str:
    return path.stem.removeprefix("rollout-")


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_key(path: Path, timestamp: str, usage: Usage) -> tuple:
    return (
        str(path),
        timestamp,
        usage.input_tokens,
        usage.cached_input_tokens,
        usage.output_tokens,
        usage.reasoning_output_tokens,
        usage.total_tokens,
    )


def _usage_delta(current: Usage, previous: Usage | None) -> Usage:
    if previous is None:
        return current
    if (
        current.input_tokens < previous.input_tokens
        or current.cached_input_tokens < previous.cached_input_tokens
        or current.output_tokens < previous.output_tokens
        or current.reasoning_output_tokens < previous.reasoning_output_tokens
        or current.total_tokens < previous.total_tokens
    ):
        return current
    return Usage(
        input_tokens=max(0, current.input_tokens - previous.input_tokens),
        cached_input_tokens=max(0, current.cached_input_tokens - previous.cached_input_tokens),
        output_tokens=max(0, current.output_tokens - previous.output_tokens),
        reasoning_output_tokens=max(
            0, current.reasoning_output_tokens - previous.reasoning_output_tokens
        ),
        total_tokens=max(0, current.total_tokens - previous.total_tokens),
    )


def _is_total_reset(current: Usage, previous: Usage) -> bool:
    return (
        current.input_tokens < previous.input_tokens
        or current.cached_input_tokens < previous.cached_input_tokens
        or current.output_tokens < previous.output_tokens
        or current.reasoning_output_tokens < previous.reasoning_output_tokens
        or current.total_tokens < previous.total_tokens
    )


def token_usage_from_info(
    info: dict,
    previous_total: Usage | None,
) -> tuple[Usage, Usage | None, str, int, bool]:
    model_context_window = _safe_int(info.get("model_context_window"))
    total_raw = info.get("total_token_usage")
    total_usage = Usage.from_dict(total_raw) if isinstance(total_raw, dict) else None

    last_raw = info.get("last_token_usage")
    if isinstance(last_raw, dict):
        usage = Usage.from_dict(last_raw)
        if total_usage is not None:
            new_total = total_usage
        elif previous_total is not None:
            new_total = Usage(
                input_tokens=previous_total.input_tokens + usage.input_tokens,
                cached_input_tokens=previous_total.cached_input_tokens + usage.cached_input_tokens,
                output_tokens=previous_total.output_tokens + usage.output_tokens,
                reasoning_output_tokens=previous_total.reasoning_output_tokens
                + usage.reasoning_output_tokens,
                total_tokens=previous_total.total_tokens + usage.total_tokens,
            )
        else:
            new_total = usage
        return usage, new_total, "last_token_usage", model_context_window, False

    if total_usage is not None:
        reset = previous_total is not None and _is_total_reset(total_usage, previous_total)
        return (
            _usage_delta(total_usage, previous_total),
            total_usage,
            "total_delta_reset" if reset else "total_delta",
            model_context_window,
            reset,
        )

    return Usage(), previous_total, "", model_context_window, False


def load_thread_metadata(state_db: Path) -> dict[str, ThreadMeta]:
    if not state_db.exists():
        return {}
    try:
        with closing(sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)) as conn:
            columns = {row[1] for row in conn.execute("pragma table_info(threads)").fetchall()}
            if "rollout_path" not in columns:
                return {}

            def text_col(name: str) -> str:
                return f"coalesce({name}, '')" if name in columns else "''"

            def int_col(name: str) -> str:
                return f"coalesce({name}, 0)" if name in columns else "0"

            rows = conn.execute(
                f"""
                select
                    rollout_path,
                    {text_col("title")},
                    {text_col("first_user_message")},
                    {text_col("cwd")},
                    {text_col("git_branch")},
                    {text_col("git_origin_url")},
                    {text_col("git_sha")},
                    {text_col("model")},
                    {text_col("reasoning_effort")},
                    {int_col("created_at")},
                    {int_col("updated_at")},
                    {text_col("source")},
                    {text_col("model_provider")},
                    {text_col("cli_version")},
                    {text_col("agent_role")},
                    {text_col("agent_nickname")},
                    {text_col("memory_mode")},
                    {text_col("thread_source")}
                from threads
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    metas: dict[str, ThreadMeta] = {}
    for row in rows:
        meta = ThreadMeta(
            rollout_path=str(row[0]),
            title=str(row[1]),
            first_user_message=str(row[2]),
            cwd=str(row[3]),
            git_branch=str(row[4]),
            git_origin_url=str(row[5]),
            git_sha=str(row[6]),
            model=str(row[7]),
            reasoning_effort=str(row[8]),
            created_at=int(row[9] or 0),
            updated_at=int(row[10] or 0),
            source=str(row[11]),
            model_provider=str(row[12]),
            cli_version=str(row[13]),
            agent_role=str(row[14]),
            agent_nickname=str(row[15]),
            memory_mode=str(row[16]),
            thread_source=str(row[17]),
        )
        metas[str(row[0])] = meta
        metas[Path(str(row[0])).name] = meta
    return metas


def current_config_service_tier(config_path: Path) -> str:
    try:
        raw = tomllib.loads(config_path.read_text(errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    tier = normalize_service_tier(raw.get("service_tier"))
    if tier:
        return tier
    features = raw.get("features")
    if isinstance(features, dict) and features.get("fast_mode") is True:
        return "fast"
    return tier


def load_tier_overrides(path: Path | None) -> list[TierOverride]:
    if path is None:
        return []
    try:
        raw = json.loads(path.expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read tier override file {path}: {exc}") from exc
    items = raw.get("overrides", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("--tier-overrides must be a JSON list or an object with an overrides list")
    overrides: list[TierOverride] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each tier override must be an object")
        tier = normalize_service_tier(str(item.get("service_tier") or item.get("tier") or ""))
        if tier not in {"standard", "fast"}:
            raise ValueError("Each tier override must set service_tier to standard or fast")
        start = parse_datetime(str(item["start"])) if item.get("start") else None
        end = parse_datetime(str(item["end"])) if item.get("end") else None
        if start and end and start >= end:
            raise ValueError("Tier override start must be before end")
        overrides.append(
            TierOverride(
                service_tier=tier,
                session=str(item["session"]) if item.get("session") else None,
                start=start.astimezone(dt.UTC) if start else None,
                end=end.astimezone(dt.UTC) if end else None,
            )
        )
    return overrides


def tier_override_for(path: Path, event_time: dt.datetime, overrides: list[TierOverride]) -> str:
    path_text = str(path)
    for override in overrides:
        if (
            override.session
            and override.session not in {path_text, path.name}
            and not path_text.endswith(override.session)
        ):
            continue
        if override.start and event_time < override.start:
            continue
        if override.end and event_time >= override.end:
            continue
        return override.service_tier
    return ""


def service_tier_for_event(
    path: Path,
    event_time: dt.datetime,
    logged_tier: str,
    options: RuntimeOptions,
    config_tier: str,
    overrides: list[TierOverride],
) -> tuple[str, str]:
    if options.service_tier != "auto":
        return options.service_tier, "cli-override"
    override = tier_override_for(path, event_time, overrides)
    if override:
        return override, "override-file"
    if logged_tier:
        return logged_tier, "logged"
    if options.unknown_service_tier == "current-config" and config_tier:
        return config_tier, "current-config"
    if options.unknown_service_tier == "current-config":
        return "standard", "assumed"
    return options.unknown_service_tier, "assumed"


def update_context_from_event(
    event: dict, current: ThreadMeta, current_tier: str
) -> tuple[ThreadMeta, str]:
    payload = event.get("payload") or {}
    event_type = event.get("type")
    payload_type = payload.get("type")

    if event_type == "turn_context":
        model = payload.get("model") or current.model
        effort = payload.get("effort") or current.reasoning_effort
        cwd = payload.get("cwd") or current.cwd
        collaboration = (payload.get("collaboration_mode") or {}).get("settings") or {}
        effort = collaboration.get("reasoning_effort") or effort
        tier = normalize_service_tier(payload.get("service_tier")) or current_tier
        return (
            replace(
                current,
                cwd=str(cwd or ""),
                model=str(model or ""),
                reasoning_effort=str(effort or ""),
            ),
            tier,
        )

    if event_type == "session_meta":
        tier = normalize_service_tier(payload.get("service_tier")) or current_tier
        return current, tier

    if event_type == "event_msg" and payload_type == "session_configured":
        tier = normalize_service_tier(payload.get("service_tier")) or current_tier
        return current, tier

    if event_type == "event_msg" and payload_type == "user_message":
        message = str(payload.get("message") or "").strip().lower()
        if message.startswith("/fast on"):
            return current, "fast"
        if message.startswith("/fast off"):
            return current, "standard"

    return current, current_tier


def rate_limit_sample(*, path: Path, event_time: dt.datetime, rate_limits: dict) -> RateLimitSample:
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    return RateLimitSample(
        timestamp=event_time,
        path=path,
        session_id=session_id_from_path(path),
        plan_type=str(rate_limits.get("plan_type") or ""),
        credits=rate_limits.get("credits"),
        primary_used_percent=primary.get("used_percent"),
        primary_window_minutes=primary.get("window_minutes"),
        primary_resets_at=primary.get("resets_at"),
        secondary_used_percent=secondary.get("used_percent"),
        secondary_window_minutes=secondary.get("window_minutes"),
        secondary_resets_at=secondary.get("resets_at"),
        rate_limit_reached_type=str(rate_limits.get("rate_limit_reached_type") or ""),
    )


def load_usage(options: RuntimeOptions) -> LoadResult:
    start_utc = options.start.astimezone(dt.UTC)
    end_utc = options.end.astimezone(dt.UTC)
    config_tier = current_config_service_tier(options.config_path)
    overrides = load_tier_overrides(options.tier_overrides)
    metadata = load_thread_metadata(options.state_db)

    events: list[UsageEvent] = []
    duplicates = 0
    seen: set[tuple] = set()
    tier_sources: dict[str, int] = {}
    plan_types: set[str] = set()
    credit_samples: list[RateLimitSample] = []
    warnings: list[str] = []
    reset_warnings: set[Path] = set()
    cache = ParseCache.default() if options.parse_cache else None

    if not options.session_root.exists():
        warnings.append(f"Session root does not exist: {options.session_root}")

    for path in session_files(options.session_root):
        thread_meta = metadata.get(
            str(path), metadata.get(path.name, ThreadMeta(rollout_path=str(path)))
        )
        signature = _parse_cache_signature(options, config_tier, overrides, thread_meta)
        parsed = cache.get(path, signature) if cache else None
        if parsed is None:
            parsed = list(
                _parse_session(
                    path,
                    thread_meta=thread_meta,
                    options=options,
                    config_tier=config_tier,
                    overrides=overrides,
                )
            )
            if cache:
                cache.put(path, signature, parsed)
        for usage_event, reset, sample in parsed:
            sample_in_window = sample is not None and start_utc <= sample.timestamp < end_utc
            if sample_in_window:
                credit_samples.append(sample)
                if sample.plan_type:
                    plan_types.add(sample.plan_type)
            if usage_event is None:
                continue
            if usage_event.timestamp < start_utc or usage_event.timestamp >= end_utc:
                continue
            if reset and path not in reset_warnings:
                warnings.append(f"Token counter reset detected in {path}; used current totals")
                reset_warnings.add(path)
            key = usage_key(path, usage_event.timestamp.isoformat(), usage_event.usage)
            if options.dedupe and key in seen:
                duplicates += 1
                continue
            seen.add(key)
            tier_sources[usage_event.tier_source] = tier_sources.get(usage_event.tier_source, 0) + 1
            events.append(usage_event)

    credit_samples.sort(key=lambda sample: sample.timestamp)
    events.sort(key=lambda event: event.timestamp)
    return LoadResult(
        events=events,
        duplicates=duplicates,
        tier_sources=tier_sources,
        plan_types=plan_types,
        credit_samples=credit_samples,
        warnings=warnings,
    )


def _parse_cache_signature(
    options: RuntimeOptions,
    config_tier: str,
    overrides: list[TierOverride],
    thread_meta: ThreadMeta,
) -> str:
    payload = {
        "version": PARSER_CACHE_VERSION,
        "service_tier": options.service_tier,
        "unknown_service_tier": options.unknown_service_tier,
        "default_model": options.default_model,
        "config_tier": config_tier,
        "overrides": [
            {
                "service_tier": item.service_tier,
                "session": item.session,
                "start": item.start.isoformat() if item.start else None,
                "end": item.end.isoformat() if item.end else None,
            }
            for item in overrides
        ],
        "thread": asdict(thread_meta),
    }
    return json.dumps(payload, sort_keys=True)


def _parse_session(
    path: Path,
    *,
    thread_meta: ThreadMeta,
    options: RuntimeOptions,
    config_tier: str,
    overrides: list[TierOverride],
):
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    current_meta = thread_meta
    logged_tier = ""
    previous_total_usage: Usage | None = None
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            current_meta, logged_tier = update_context_from_event(event, current_meta, logged_tier)
            if event.get("type") != "event_msg":
                continue
            payload = event.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            event_time = parse_event_timestamp(event.get("timestamp") or "")
            if event_time is None:
                continue
            info = payload.get("info") or {}
            usage, previous_total_usage, usage_source, model_context_window, total_reset = (
                token_usage_from_info(info if isinstance(info, dict) else {}, previous_total_usage)
            )

            rate_limits = payload.get("rate_limits") or {}
            sample = (
                rate_limit_sample(path=path, event_time=event_time, rate_limits=rate_limits)
                if rate_limits
                else None
            )

            if usage.is_zero():
                yield None, total_reset, sample
                continue

            model = (
                normalize_model(current_meta.model)
                or normalize_model(thread_meta.model)
                or normalize_model(options.default_model)
            )
            tier, tier_source = service_tier_for_event(
                path=path,
                event_time=event_time,
                logged_tier=logged_tier,
                options=options,
                config_tier=config_tier,
                overrides=overrides,
            )
            primary = rate_limits.get("primary") or {}
            secondary = rate_limits.get("secondary") or {}
            usage_event = UsageEvent(
                timestamp=event_time,
                path=path,
                session_id=session_id_from_path(path),
                usage=usage,
                model=model,
                service_tier=tier,
                tier_source=tier_source,
                thread=current_meta,
                usage_source=usage_source,
                model_context_window=model_context_window,
                plan_type=str(rate_limits.get("plan_type") or ""),
                credits=rate_limits.get("credits"),
                primary_used_percent=primary.get("used_percent"),
                primary_window_minutes=primary.get("window_minutes"),
                primary_resets_at=primary.get("resets_at"),
                secondary_used_percent=secondary.get("used_percent"),
                secondary_window_minutes=secondary.get("window_minutes"),
                secondary_resets_at=secondary.get("resets_at"),
                rate_limit_reached_type=str(rate_limits.get("rate_limit_reached_type") or ""),
            )
            yield usage_event, total_reset, sample
