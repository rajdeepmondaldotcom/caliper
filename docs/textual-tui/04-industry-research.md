# Phase 4 — Industry Standards Research

**Status:** Draft (Phase 4)
**Date:** 2026-05-14
**Anchor rule:** research *refines*, it does not redirect. The core
architecture (single-process pure-Python, reactive `AppState`,
optional `[tui]` extra, 16 screens) is locked. This document records
how each cross-checked design choice maps to upstream best practice
*as of May 2026*.

Each section ends with one of three dispositions:
- **CONFIRMS plan** — proceed as written.
- **REFINES plan** — small adjustment, recorded for Phase 5.
- **OPEN** — needs more data before Phase 5 closes it.

Sources are listed at the end.

---

## 1. Textual version pinning

**Question:** Phase 1 wrote `textual>=0.85,<1`. Is that still correct?

**Finding:** Textual is **8.2.6** on PyPI as of May 2026. The
`0.x` line ended with the `1.0` ship in late 2024; the `8.x` line is
current stable. Requires `python <4.0,>=3.9`. Runtime deps include
`rich>=14.2.0`, `platformdirs<5,>=3.6.0`, `markdown-it-py[linkify]`,
`mdit-py-plugins`, `pygments`, `typing-extensions`.

**Impact on Caliper:** the existing `rich>=13.7` floor must be lifted
to `rich>=14.2.0` *when the `tui` extra is installed*. Since `rich` is
a required dependency of `caliper-ai` itself, the cleanest path is to
lift the base floor too (`rich>=14.2.0`) and re-run the test suite for
any Rich 14 breakage in `render.py`. If the suite is clean, the bump
is silent. If it isn't, we keep the base floor lower and use Textual's
own `rich` dep as the floor inside the `tui` extra.

**Disposition:** **REFINES plan.**
- Pin `textual>=8.2,<9`.
- Probe rich-14 compatibility under a feature branch before the first
  Textual commit. Add `tests/test_rich_14_compat.py` as a smoke layer.

## 2. Worker model and cancellation

**Question:** Plan §3.3 uses `@work(exclusive=True, group="data",
thread=True)`. Are these flags real? How do we cancel cleanly mid-IO?

**Finding:**
- `@work(exclusive=True, thread=True, exit_on_error=True, group="name")`
  are all real on current Textual.
- `exclusive=True` cancels any prior worker in the same group before
  starting a new one. Race condition for free.
- Thread workers cannot be cooperatively cancelled the way coroutines
  can. The recommended idiom is:
  ```python
  from textual.worker import get_current_worker
  worker = get_current_worker()
  for path in paths:
      if worker.is_cancelled:
          break
      ...
  ```
- `post_message(...)` is **thread-safe**. Everything else (widget
  mutation, reactive writes) requires `app.call_from_thread(...)`.

**Impact on Caliper:** Phase 3 §3 promised a `ParseProgress` protocol.
The implementation pattern is now precise:

```python
class TextualParseProgress(ParseProgress):
    def __init__(self, app):
        self._app = app
        self._worker = get_current_worker()
    def starting(self, total_files: int) -> None:
        self._app.post_message(LoadStarting(total_files))
    def file_done(self, path: Path) -> None:
        if self._worker.is_cancelled:
            raise WorkerCancelled
        self._app.post_message(LoadFileDone(path))
    ...
```

A new `WorkerCancelled` exception class lets the parser unwind without
poisoning `load_usage`'s normal return path. Add a try/except in the
worker body so the cancellation looks like a graceful "previous load
was aborted" toast, not a stack trace.

**Disposition:** **REFINES plan.** Adopt `Worker.is_cancelled`-poll
pattern. Adopt `post_message` for incremental progress. Reserve
`call_from_thread` for state writes that don't fit the message bus.

## 3. App.suspend() for $EDITOR

**Question:** Plan §13 promised suspend-to-editor. Real?

**Finding:**
- `with self.suspend(): ...` is a context manager.
- POSIX (Linux, macOS): full support.
- Windows + `textual-web`: **silently ignored**. The block runs without
  releasing the terminal.

**Impact on Caliper:** the Phase 3 D6 decision stands — suspend on
POSIX, print path on Windows. Add a small platform check around the
`with self.suspend()` call.

**Disposition:** **CONFIRMS plan.**

## 4. Command palette

**Question:** Plan §5.15 promised `Ctrl+P` palette with custom commands.

**Finding:** Real, well-supported. Customisation is via a `Provider`
subclass:

```python
from textual.command import Provider, Hit, DiscoveryHit

class CaliperCommands(Provider):
    async def discover(self):
        yield DiscoveryHit("Go to Daily", lambda: self.app.switch_screen("intervals"))
        # ...
    async def search(self, query: str):
        matcher = self.matcher(query)
        for label, action in self._commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), action)

class CaliperApp(App):
    COMMANDS = App.COMMANDS | {CaliperCommands}
```

Screen-specific commands live on `Screen.COMMANDS`. Callbacks may be
sync or async. `app.run_worker(...)` is the bridge if a command should
launch a long-running task.

**Impact on Caliper:** one `CaliperCommands` provider exposes
"Go to *", "Refresh", "Toggle redact", "Cycle theme", "Open
caliper.toml". Screen-local commands (e.g. "Sort by cost desc" on
Models) live on each screen.

**Disposition:** **CONFIRMS plan.** Numbered commit T21 stays as
written.

## 5. Theme registration and NO_COLOR

**Question:** Plan §7 listed three themes. How does Textual expose
theme registration? Does it honour `NO_COLOR`?

**Finding:**
- `App.register_theme(Theme(name=..., primary=..., ...))` in
  `on_mount`. Then `self.theme = "name"`. Only `primary` is required;
  Textual derives the rest.
- Built-in themes ship with Textual (nord, monokai, dracula, etc.). We
  do not have to invent everything; we can register `slate` as our
  default and lean on built-ins for `parchment` (light) baseline.
- **`NO_COLOR` is not auto-handled by Textual.** The developer must
  read `os.environ.get("NO_COLOR")` and switch theme manually.
  Textual exposes `App.ansi_color = True` to skip ANSI color
  translation, useful when running inside another color-aware renderer.

**Impact on Caliper:** add `theme.py` with three named themes:
- `slate` — warm dark gray, indigo accent.
- `parchment` — off-white, sienna accent.
- `colorblind` — blue / orange severity instead of red / green.
- *On launch*, if `NO_COLOR` env var is set, force a fourth registered
  theme `monochrome` (no hue, weight + italic only for hierarchy) and
  ignore the saved `[tui] theme = ...` setting for the session. The
  saved value is kept, not overwritten.

**Disposition:** **REFINES plan.** Adds a fourth registered theme
(monochrome) gated on `NO_COLOR`. Adds explicit `App.ansi_color`
handling for terminals that double-translate ANSI.

## 6. Watchdog vs polling

**Question:** Plan §5.8 (Live) and §3.3 (worker table) used watchdog.
Is it dependable in 2026?

**Finding:**
- watchdog is healthy on PyPI, Python 3.11/3.12/3.13 supported (3.13
  free-threaded under partial audit, particularly the macOS FSEvents
  interface).
- Local FS: inotify (Linux), FSEvents (macOS), ReadDirectoryChangesW
  (Windows). Reliable.
- **Network FS (NFS/SMB/CIFS, sshfs):** inotify misses remote
  changes; latency >200 ms breaks the API. Recommendation: use
  `PollingObserver` explicitly.
- `PollingObserver` is always available; safe portable fallback.

**Impact on Caliper:**
- Detect whether the watched paths (`~/.codex`, `~/.config/claude-code`,
  etc.) sit on a network filesystem. Cheap heuristic: `os.stat`
  `st_dev` compared to user home; flag mismatched mounts and switch to
  `PollingObserver` proactively.
- Add `caliper tui --no-watchdog` flag (already in Phase 3 §1) to
  force `PollingObserver` regardless.
- Cap poll interval at 2 s. Debounce filesystem events to one refresh
  per 2 s to avoid event storms.

**Disposition:** **REFINES plan.** Add NFS heuristic, document the
`--no-watchdog` flag, and document the 2 s debounce.

## 7. pytest-textual-snapshot

**Question:** Plan §10 promised pilot snapshot tests. Stable?

**Finding:** Stable. Built on syrupy. Snapshots are SVGs on disk;
diff is HTML. `snap_compare` fixture takes either an `App` instance
or a path to a Python file containing an `App` subclass. Update with
`pytest --snapshot-update`. `pytest-xdist` works.

**Impact on Caliper:**
- Add to `[dependency-groups.dev]`: `pytest-textual-snapshot==X.Y`
  (pin to the current minor; bumping major requires regenerating
  all SVGs and reviewing the diffs in PR).
- Store snapshots under `tests/tui/snapshots/__snapshots__/` (Textual
  convention).
- Add `tests/tui/snapshots/README.md` with the refresh recipe and a
  rule that snapshot updates *must* be reviewed in PR with the SVG
  diff attached.

**Disposition:** **CONFIRMS plan.** Adds README guidance.

## 8. OSC52 clipboard support

**Question:** Plan D7 chose OSC52 primary. Sufficient?

**Finding:** Wide support across modern terminals: alacritty,
contour, foot, hterm, iterm2, kitty, rxvt, st, tmux, wezterm,
Windows Terminal, Zellij. Clipboard *write* is more universal than
*read*. Caliper only writes (it never pastes).

Caveat: **tmux** acts as a terminal emulator and may intercept OSC52
unless `set -g allow-passthrough on` is configured in `.tmux.conf`.
Document the one-liner for users.

**Impact on Caliper:** the layered fallback already chosen (OSC52 →
`pyperclip` → inline) is correct. Add a help-screen note about tmux.

**Disposition:** **CONFIRMS plan.** Adds the tmux note.

## 9. Hatchling data files for `.tcss`

**Question:** Phase 2 §C12 promised `.tcss` files would ship in the
wheel. What is the right hatchling incantation in 2026?

**Finding:** Two viable patterns in modern hatchling:

a. `force-include` keyed by repository path → wheel path:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/caliper/tui/tcss" = "caliper/tui/tcss"
```

b. `only-include` inside the wheel target, paired with `packages`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/caliper"]
only-include = ["src/caliper"]
```

Default hatchling rules already package every file inside a discovered
package directory, so (b) alone is usually enough. Option (a) is the
belt-and-braces variant we will use because it makes intent explicit
and is unaffected by glob heuristics drift in future hatchling
releases.

**Impact on Caliper:** add `force-include` block plus a CI check:
```bash
python -m build --wheel
unzip -l dist/*.whl | grep -E '\.tcss$' || { echo "missing tcss"; exit 1; }
```
Skipped on Windows CI if `python -m build` is too slow there.

**Disposition:** **REFINES plan.** Concrete pyproject snippet locked.

## 10. Accessibility

**Question:** Plan §4.14 promised colorblind theme and themed-not-painted.
Where does Textual stand on screen readers and other a11y in 2026?

**Finding:** Textual lists screen-reader integration as an
accessibility feature in 2025 marketing, but the field is hard
(terminals + screen readers are historically a poor fit). Concrete
implementation lags marketing. The realistic position for May 2026:

- High-contrast + colorblind themes: solid, well-documented.
- Monochrome / NO_COLOR fallback: doable manually.
- Screen reader output: **partial; do not promise**.
- Keyboard-only navigation: first-class.
- Focus indicators: first-class.

**Impact on Caliper:** the plan never promised perfect screen-reader
output. We keep:
- Three named themes plus monochrome.
- Every action keyboard-reachable.
- Visible focus indicators.
- `aria`-ish text-only summaries available via `caliper overview --format
  markdown` for users who prefer the structured CLI.

Add an explicit "Accessibility" subsection to the README that names
what works and what is deferred. Mark "screen-reader narration" as a
known limitation upstream of Caliper.

**Disposition:** **CONFIRMS plan.** Adds README a11y subsection.

## 11. Distribution and installation UX

**Question:** Is the optional-extra approach idiomatic? Does it raise
red flags?

**Finding:** Optional dependency groups via
`[project.optional-dependencies]` are PEP 621 standard and supported by
pip, uv, pipx. `pip install "caliper-ai[tui]"` is widely understood.
`uvx --with caliper-ai[tui] caliper tui` works for one-shot users.

For brew/scoop/winget down the line, the extra would have to be a
*separate* recipe pulling in textual + watchdog as runtime deps, but
that is a future-work concern.

**Impact on Caliper:** no change. Phase 1 §3.5 stands.

**Disposition:** **CONFIRMS plan.**

## 12. Performance budgets

**Question:** Phase 3 D-new-1 pinned 200 ms / 2 s budgets. Are these
realistic?

**Finding:** Anecdotal but consistent: Textual apps with deferred work
(`post_message` for state mutation, threaded workers for IO) routinely
land in 50–150 ms first-paint range on modern hardware. A 200 ms
budget for the demo path is achievable. The 2 s budget for a real
load is *aspirational* if the user has multi-GB log directories; the
LoadingOverlay was already planned to cover anything beyond 200 ms.

**Impact on Caliper:**
- Keep the 200 ms first-paint budget for `--demo` path.
- Drop the 2 s claim for real loads. Replace with: "first paint of
  empty Home overlay ≤200 ms, then LoadingOverlay until data ready."
  This is honest and matches the UX pillar "Loading is honest."

**Disposition:** **REFINES plan.** Tighten the budget language.

## 13. Mouse, touch, and resize

**Question:** Plan §4.4 keyboard-first, mouse-welcome. Caveats?

**Finding:** Textual's mouse + touch + resize handling is first-class.
DataTable supports click-to-sort and row click. Tab strips clickable.
Modal close on outside click is a configuration. No code changes
needed beyond enabling these features per widget.

**Impact on Caliper:** no architectural change. Phase 7 review should
include "every interaction works on mouse too" as a checklist item.

**Disposition:** **CONFIRMS plan.**

## 14. Items that remain OPEN

These would benefit from further investigation but do not block Phase
5 (since Phase 5 is plan-only).

- **Textual Web compatibility.** If Caliper ever ships a hosted
  preview, App.suspend, OSC52, and watchdog all need re-evaluation.
  Out of scope for now.
- **Plot widget choice.** `textual-plotext` is the most-cited
  option; not yet integrated. Phase 7 may defer the inline chart and
  fall back to the existing ASCII sparkline. Phase 8 revisits.
- **Snapshot stability across font widths.** SVG output renders glyphs
  by Unicode codepoint, so column-width assumptions matter. CI uses a
  pinned font in container; we rely on Textual's deterministic
  renderer to keep this stable.

## 15. Summary of refinements to fold into Phase 5

1. **Textual pin:** `textual>=8.2,<9`; lift `rich` floor to `>=14.2.0`
   and probe in a feature branch before the first Textual commit.
2. **`watchdog` pin:** `watchdog>=4.0,<7`; add `--no-watchdog` flag;
   add NFS heuristic; debounce 2 s.
3. **Worker pattern:** adopt `get_current_worker().is_cancelled` +
   `post_message` everywhere blocking IO talks to the UI. Add a
   `WorkerCancelled` exception used by the parser callback.
4. **NO_COLOR:** register a `monochrome` theme; switch to it on session
   start when `NO_COLOR` is in the environment; do not overwrite the
   saved theme.
5. **Hatchling:** add `force-include` for `src/caliper/tui/tcss` and a
   CI wheel-content grep.
6. **First-paint budget:** ≤200 ms for `--demo`; real loads use the
   LoadingOverlay until data ready. Drop the 2 s claim.
7. **Accessibility:** README subsection naming the deferred items
   (screen reader narration upstream limitation).
8. **tmux clipboard:** help-screen note about
   `set -g allow-passthrough on`.

## Sources

- [Textual on PyPI](https://pypi.org/pypi/textual/json) — current
  version, requires_python, runtime dependencies.
- [Textual — Workers guide](https://textual.textualize.io/guide/workers/) —
  `@work` decorator semantics, thread cancellation, `post_message`.
- [Textual — App guide](https://textual.textualize.io/guide/app/) —
  `App.suspend()` context manager, Windows caveat.
- [Textual — Command palette guide](https://textual.textualize.io/guide/command_palette/) —
  `Provider`, `Hit`, `DiscoveryHit`.
- [Textual — Design guide](https://textual.textualize.io/guide/design/) —
  `App.register_theme`, `Theme` class.
- [pytest-textual-snapshot README](https://github.com/Textualize/pytest-textual-snapshot/blob/main/README.md) — fixture API, syrupy base.
- [Workers discussion #3049](https://github.com/Textualize/textual/discussions/3049) — thread→UI messaging.
- [Workers discussion #1828](https://github.com/Textualize/textual/discussions/1828) — long-running API patterns.
- [watchdog on PyPI](https://pypi.org/project/watchdog/) — current
  state, observer types.
- [Hatch build configuration](https://hatch.pypa.io/1.13/config/build/) —
  `force-include`, `only-include`, `packages`.
- [OSC52 support overview — DEV.to](https://dev.to/djmitche/clipboards-terminals-and-linux-3pk5) — terminal compatibility matrix.
- [On tmux OSC-52 support](https://kalnytskyi.com/posts/on-tmux-osc52-support/) — `allow-passthrough` configuration.
- [Textual — FAQ](https://textual.textualize.io/FAQ/) — accessibility status.
