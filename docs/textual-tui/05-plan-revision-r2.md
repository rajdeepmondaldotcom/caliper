# Phase 5 — Plan Revision (Round 2)

**Status:** Draft (Phase 5)
**Date:** 2026-05-14
**Anchor:** Phase 1 + Phase 3 are the architectural source of truth.
This document folds the eight Phase 4 refinements into the plan
without redesigning anything. Phase 6 will produce the consolidated
final plan from which implementation proceeds.

---

## Changes adopted from Phase 4

### R1. Dependency pins (replaces Phase 1 §3.5)

```toml
[project]
# bump rich floor to match textual's own minimum
dependencies = [
  "platformdirs>=4.3",
  "rich>=14.2.0",
  "typer>=0.12",
]

[project.optional-dependencies]
prom = ["prometheus-client>=0.20"]
tui  = [
  "textual>=8.2,<9",
  "watchdog>=4.0,<7",
]

[dependency-groups]
dev = [
  # existing entries kept
  "pytest-textual-snapshot",   # version pinned in P10 prerequisite
]
```

Add a prerequisite commit P0 before P1:

> **P0** `chore(deps): bump rich floor to 14.2.0 (textual prereq)`
> with a CI run on a feature branch to confirm `render.py` still
> snapshot-matches existing tests.

If Rich 14 breaks any `render.py` test, P0 stays on the feature branch
until those tests are repaired *under the existing CLI behavior*; we
do not change CLI output to suit Rich 14.

### R2. Watchdog policy

- Pin `watchdog>=4.0,<7` as a `tui` extra (so the base install stays
  zero-extra-deps).
- New flag `--no-watchdog` on `caliper tui` forces `PollingObserver`.
- NFS / sshfs heuristic in `caliper.tui.watch.choose_observer(paths)`:
  - For each path, compare `os.stat(path).st_dev` to the user's home
    `st_dev`. Mismatch → likely a remote mount → use `PollingObserver`.
  - Linux: also short-circuit on `Path("/proc/mounts")` lines starting
    with `nfs`, `cifs`, `sshfs`, `fuse.sshfs`.
- Debounce filesystem events to one refresh per 2 s.

### R3. Worker cancellation (replaces Phase 1 §3.3 mechanism)

Every thread worker follows this template:

```python
from textual.worker import get_current_worker

class WorkerCancelled(RuntimeError):
    """Sentinel raised by progress callbacks when a worker is cancelled."""

class TextualParseProgress:
    def __init__(self, app, total: int = 0):
        self._app = app
        self._worker = get_current_worker()
        self._total = total
    def starting(self, total: int) -> None:
        self._total = total
        self._app.post_message(LoadStarted(total))
    def file_done(self, path) -> None:
        if self._worker.is_cancelled:
            raise WorkerCancelled
        self._app.post_message(LoadFileDone(path))
    def cache_hit(self, path) -> None:
        if self._worker.is_cancelled:
            raise WorkerCancelled
        self._app.post_message(LoadFileCacheHit(path))
    def finished(self) -> None:
        self._app.post_message(LoadFinished())

@work(thread=True, exclusive=True, group="data", exit_on_error=False)
def load_usage_worker(self, options):
    progress = TextualParseProgress(self.app)
    try:
        result = load_usage(options, progress=progress)
    except WorkerCancelled:
        self.app.post_message(LoadCancelled())
        return
    self.app.post_message(LoadSucceeded(result))
```

This pattern propagates to every thread worker the plan introduces.

### R4. NO_COLOR handling (adds to Phase 1 §7)

Themes registered in `caliper.tui.app.CaliperApp.on_mount`:

```python
self.register_theme(SLATE)
self.register_theme(PARCHMENT)
self.register_theme(COLORBLIND)
self.register_theme(MONOCHROME)

saved = self.config.theme       # from [tui] section
if os.environ.get("NO_COLOR"):
    self.theme = "monochrome"   # session only, saved value untouched
    self.ansi_color = True      # avoid double-translation
else:
    self.theme = saved
```

The Help screen surfaces "Active theme: X (overridden by NO_COLOR)"
when applicable so the user is not confused by their saved choice not
applying.

### R5. Hatchling wheel data files

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/caliper"]

[tool.hatch.build.targets.wheel.force-include]
"src/caliper/tui/tcss" = "caliper/tui/tcss"
```

CI step appended to `.github/workflows/ci.yml`:

```yaml
- name: Verify wheel ships TCSS
  run: |
    python -m build --wheel
    unzip -l dist/*.whl | grep -E '\.tcss$' || { echo "missing tcss in wheel"; exit 1; }
```

### R6. First-paint budget (tightens Phase 3 D-new-1)

| Path | Budget | Mechanism |
| --- | --- | --- |
| `caliper tui --demo` | ≤200 ms to Home full-render | demo fixture in memory, zero IO |
| `caliper tui` (real) | ≤200 ms to **LoadingOverlay** visible | parser runs in worker, overlay is the first paint |
| Real Home render | best-effort | LoadingOverlay reports file progress; honest is better than fast |

Drop any prior "2 s real load" claim.

### R7. Accessibility wording (README addition)

A short section to be added in Phase 7's T26 `docs(tui)` commit:

```
## Accessibility

Caliper TUI ships keyboard-first navigation, visible focus indicators,
three named themes including a colorblind palette, and a monochrome
fallback that activates automatically when NO_COLOR is set.

Screen-reader narration in terminals is an evolving area upstream of
Caliper; we do not promise rich screen-reader support today. For
narration-friendly output, the structured CLI surface remains the
recommended path:

    caliper overview --format markdown
    caliper daily   --format markdown
    caliper limits  --format json
```

### R8. tmux clipboard note

In `caliper.tui.screens.help.HelpScreen`, the clipboard section reads:

> Copy uses OSC52. If you run Caliper inside tmux and copy does
> nothing, add `set -g allow-passthrough on` to your `.tmux.conf` and
> reload. Caliper never reads from the clipboard.

## Items deliberately not changed

These were probed in Phase 4 and stand as planned:

- Command palette `Provider` registration pattern (Phase 1 §5.15 / Phase 4 §4).
- `App.suspend()` POSIX-only suspend-to-editor (Phase 3 D6 / Phase 4 §3).
- Optional `[tui]` extra and `pip install 'caliper-ai[tui]'`
  distribution (Phase 1 §3.5 / Phase 4 §11).
- 200 ms / LoadingOverlay UX pillar (Phase 1 §4.7).
- Reactive `AppSnapshot` mediator and 16-screen map.

## Phasing impact

R1 adds **P0** to the prerequisite block, sliding the prerequisites
from P1–P10 to P0–P10 (eleven commits) before the first Textual commit.
No commit drops out. The Textual sequence (T01–T27) is unchanged in
count and intent but small bodies pick up the R3/R4/R5/R7/R8 details:

- T01 includes the R1 dependency pins.
- T02 includes the `WorkerCancelled` exception and the
  `TextualParseProgress` adapter.
- T04 includes the four registered themes and the `NO_COLOR` switch.
- T06 incorporates the `Worker.is_cancelled` polling.
- T14 includes the watchdog/PollingObserver picker.
- T20 includes the tmux clipboard note in HelpScreen.
- T26 adds the Accessibility section.

## Verdict

All eight Phase 4 refinements fit inside existing Phase 3 commit slots
or as P0 before P1. **No architectural changes.** Phase 6 will produce
the consolidated final plan that supersedes 01 + 03 + 05 for
implementation purposes, with 02 and 04 retained as historical
artifacts.
