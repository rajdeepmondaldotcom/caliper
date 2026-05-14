from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from caliper.config import TuiConfig, build_options
from caliper.models import LoadResult
from caliper.tui.app import CaliperApp
from caliper.tui.manifest import TuiLoadManifest, build_load_manifest
from caliper.tui.messages import LoadSucceeded


def _options(tmp_path: Path):
    return build_options(
        days=7,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
        no_parse_cache=True,
    )


def _result() -> LoadResult:
    return LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


def _derived() -> dict:
    return {
        "overview_windows": (),
        "overview_total": None,
        "daily": (),
        "weekly": (),
        "monthly": (),
        "sessions": (),
        "projects": (),
        "models": (),
        "insights": (),
        "primary_window": None,
        "secondary_window": None,
    }


def test_stale_load_success_is_ignored(tmp_path):
    app = CaliperApp(_options(tmp_path), tui_config=TuiConfig(no_watchdog=True))
    app._load_generation = 2

    app.on_load_succeeded(
        LoadSucceeded(
            _result(),
            object(),  # type: ignore[arg-type]
            _derived(),
            TuiLoadManifest((), ()),
            generation=1,
        )
    )

    assert app.snapshot.load_result is None


def test_watch_snapshot_forwards_to_active_screen(tmp_path):
    app = CaliperApp(_options(tmp_path), tui_config=TuiConfig(no_watchdog=True))
    seen = []

    class Active:
        def update_from_snapshot(self, snapshot):
            seen.append(snapshot)

    app._screen_stacks[app._current_mode].append(Active())  # type: ignore[arg-type]
    app.watch_snapshot(app.snapshot)

    assert seen == [app.snapshot]


def test_load_worker_reuses_unchanged_manifest(tmp_path, monkeypatch):
    options = _options(tmp_path)
    app = CaliperApp(options, tui_config=TuiConfig(no_watchdog=True))
    manifest = TuiLoadManifest(("same",), ())
    result = _result()
    derived = _derived()
    messages = []

    class Worker:
        is_cancelled = False

    monkeypatch.setattr("caliper.tui.app.get_current_worker", lambda: Worker())
    monkeypatch.setattr("caliper.tui.app.build_load_manifest", lambda _options: manifest)
    monkeypatch.setattr(
        "caliper.tui.app.run_load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reread")),
    )
    monkeypatch.setattr(app, "post_message", lambda message: messages.append(message))

    body = app._load_worker(
        generation=3,
        snapshot=app.snapshot,
        previous_manifest=manifest,
        previous_result=result,
        previous_card=object(),
        previous_derived=derived,
    )
    body()

    success = [message for message in messages if isinstance(message, LoadSucceeded)]
    assert success
    assert success[0].reused is True


def test_manifest_changes_when_session_file_changes(tmp_path):
    options = _options(tmp_path)
    session_dir = options.session_root / "2026" / "05" / "14"
    session_dir.mkdir(parents=True)
    path = session_dir / "rollout-demo.jsonl"
    path.write_text("{}\n")

    first = build_load_manifest(options)
    path.write_text('{"changed": true}\n')
    now = dt.datetime.now().timestamp()
    os.utime(path, (now + 1, now + 1))
    second = build_load_manifest(options)

    assert first != second
