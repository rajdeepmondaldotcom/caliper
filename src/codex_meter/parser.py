from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from codex_meter.models import LoadResult, RuntimeOptions, ThreadMeta, TierOverride, UsageEvent
from codex_meter.pricing import normalize_model, normalize_service_tier
from codex_meter.timeutil import parse_datetime, parse_event_timestamp


def session_files(session_root: Path) -> Iterable[Path]:
    if not session_root.exists():
        return []
    return sorted(session_root.glob("**/*.jsonl"))


def session_id_from_path(path: Path) -> str:
    return path.stem.removeprefix("rollout-")


def safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_usage(raw: dict) -> dict[str, int]:
    return {
        "input_tokens": safe_int(raw.get("input_tokens")),
        "cached_input_tokens": safe_int(raw.get("cached_input_tokens")),
        "output_tokens": safe_int(raw.get("output_tokens")),
        "reasoning_output_tokens": safe_int(raw.get("reasoning_output_tokens")),
        "total_tokens": safe_int(raw.get("total_tokens")),
    }


def usage_key(timestamp: str, usage: dict[str, int]) -> tuple:
    return (
        timestamp,
        usage.get("input_tokens", 0),
        usage.get("cached_input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("reasoning_output_tokens", 0),
        usage.get("total_tokens", 0),
    )


def load_thread_metadata(state_db: Path) -> dict[str, ThreadMeta]:
    if not state_db.exists():
        return {}
    try:
        with sqlite3.connect(state_db) as conn:
            rows = conn.execute(
                """
                select
                    rollout_path,
                    coalesce(title, ''),
                    coalesce(first_user_message, ''),
                    coalesce(cwd, ''),
                    coalesce(git_branch, ''),
                    coalesce(git_origin_url, ''),
                    coalesce(model, ''),
                    coalesce(reasoning_effort, ''),
                    coalesce(created_at, 0),
                    coalesce(updated_at, 0)
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
            model=str(row[6]),
            reasoning_effort=str(row[7]),
            created_at=int(row[8] or 0),
            updated_at=int(row[9] or 0),
        )
        metas[str(row[0])] = meta
        metas[Path(str(row[0])).name] = meta
    return metas


def current_config_service_tier(config_path: Path) -> str:
    try:
        text = config_path.read_text(errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("service_tier"):
            _, _, raw_value = stripped.partition("=")
            return normalize_service_tier(raw_value.strip().strip('"').strip("'"))
    return ""


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
) -> tuple[str, str, bool]:
    if options.service_tier != "auto":
        return options.service_tier, "cli-override", False
    override = tier_override_for(path, event_time, overrides)
    if override:
        return override, "override-file", False
    if logged_tier:
        return logged_tier, "logged", False
    if options.unknown_service_tier == "current-config" and config_tier:
        return config_tier, "current-config", True
    if options.unknown_service_tier == "current-config":
        return "standard", "assumed", True
    return options.unknown_service_tier, "assumed", True


def update_context_from_event(
    event: dict, current: ThreadMeta, current_tier: str
) -> tuple[ThreadMeta, str]:
    payload = event.get("payload") or {}
    event_type = event.get("type")
    payload_type = payload.get("type")

    if event_type == "turn_context":
        model = payload.get("model") or current.model
        effort = payload.get("effort") or current.reasoning_effort
        collaboration_settings = (payload.get("collaboration_mode") or {}).get("settings") or {}
        effort = collaboration_settings.get("reasoning_effort") or effort
        tier = normalize_service_tier(payload.get("service_tier")) or current_tier
        return (
            ThreadMeta(
                rollout_path=current.rollout_path,
                title=current.title,
                first_user_message=current.first_user_message,
                cwd=current.cwd,
                git_branch=current.git_branch,
                git_origin_url=current.git_origin_url,
                model=str(model or ""),
                reasoning_effort=str(effort or ""),
                created_at=current.created_at,
                updated_at=current.updated_at,
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
    credit_samples: list[UsageEvent] = []
    warnings: list[str] = []

    if not options.session_root.exists():
        warnings.append(f"Session root does not exist: {options.session_root}")

    for path in session_files(options.session_root):
        try:
            if path.stat().st_mtime < start_utc.timestamp():
                continue
        except OSError:
            continue

        thread_meta = metadata.get(
            str(path), metadata.get(path.name, ThreadMeta(rollout_path=str(path)))
        )
        current_meta = thread_meta
        logged_tier = ""

        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue

        with handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                current_meta, logged_tier = update_context_from_event(
                    event, current_meta, logged_tier
                )
                if event.get("type") != "event_msg":
                    continue
                payload = event.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                usage = normalize_usage((payload.get("info") or {}).get("last_token_usage") or {})
                if not any(usage.values()):
                    continue
                timestamp = event.get("timestamp") or ""
                event_time = parse_event_timestamp(timestamp)
                if event_time is None or event_time < start_utc or event_time >= end_utc:
                    continue
                key = usage_key(timestamp, usage)
                if options.dedupe and key in seen:
                    duplicates += 1
                    continue
                seen.add(key)

                model = normalize_model(current_meta.model) or normalize_model(thread_meta.model)
                model = model or normalize_model(options.default_model)
                tier, tier_source, _unknown_tier = service_tier_for_event(
                    path=path,
                    event_time=event_time,
                    logged_tier=logged_tier,
                    options=options,
                    config_tier=config_tier,
                    overrides=overrides,
                )
                tier_sources[tier_source] = tier_sources.get(tier_source, 0) + 1

                rate_limits = payload.get("rate_limits") or {}
                plan_type = str(rate_limits.get("plan_type") or "")
                if plan_type:
                    plan_types.add(plan_type)

                usage_event = UsageEvent(
                    timestamp=event_time,
                    path=path,
                    session_id=session_id_from_path(path),
                    usage=usage,
                    model=model,
                    service_tier=tier,
                    tier_source=tier_source,
                    thread=current_meta,
                    plan_type=plan_type,
                    credits=rate_limits.get("credits"),
                    primary_used_percent=(rate_limits.get("primary") or {}).get("used_percent"),
                    secondary_used_percent=(rate_limits.get("secondary") or {}).get("used_percent"),
                )
                events.append(usage_event)
                if "credits" in rate_limits:
                    credit_samples.append(usage_event)

    credit_samples = sorted(credit_samples, key=lambda event: event.timestamp)[-5:]
    events.sort(key=lambda event: event.timestamp)
    return LoadResult(
        events=events,
        duplicates=duplicates,
        tier_sources=tier_sources,
        plan_types=plan_types,
        credit_samples=credit_samples,
        warnings=warnings,
    )
