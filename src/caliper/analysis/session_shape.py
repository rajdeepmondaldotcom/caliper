from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field

from caliper.models import (
    UNKNOWN_PROJECT,
    LoadResult,
    UsageEvent,
    project_name_from_path,
)

EXPLORATION_TOOLS = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "WebFetch",
        "WebSearch",
        "List",
        "LS",
        "NotebookRead",
        "Explore",
    }
)
EXECUTION_TOOLS = frozenset(
    {
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "Update",
        "Patch",
    }
)
DIAGNOSTIC_TOOLS = frozenset(
    {
        "Bash",
        "Run",
        "Test",
        "Shell",
        "BashOutput",
        "KillShell",
        # Task / planning tooling — agent orchestration falls under "diagnose"
        # because it's how Claude Code investigates / coordinates work rather
        # than reading or editing.
        "Task",
        "TaskCreate",
        "TaskUpdate",
        "TaskList",
        "TaskGet",
        "TaskStop",
        "TaskOutput",
        "TodoWrite",
        "Agent",
    }
)

CATEGORY_EXPLORATION = "exploration"
CATEGORY_EXECUTION = "execution"
CATEGORY_DIAGNOSTIC = "diagnostic"
CATEGORY_MIXED = "mixed"
CATEGORY_NONE = "no-tools"

_CATEGORY_LABELS = {
    CATEGORY_EXPLORATION: "exploration (read-heavy)",
    CATEGORY_EXECUTION: "execution (edit-heavy)",
    CATEGORY_DIAGNOSTIC: "diagnostic (bash/grep-heavy)",
    CATEGORY_MIXED: "mixed",
    CATEGORY_NONE: "no tool calls",
}


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category)


@dataclass(frozen=True)
class ToolUseBreakdown:
    total_calls: int
    per_tool: tuple[tuple[str, int], ...]

    @property
    def top(self) -> tuple[tuple[str, int], ...]:
        return self.per_tool

    def top_n(self, limit: int) -> tuple[tuple[str, int], ...]:
        return self.per_tool[:limit]


@dataclass(frozen=True)
class SessionShape:
    session_id: str
    project_name: str
    vendor: str
    total_turns: int
    total_tool_uses: int
    tool_counts: tuple[tuple[str, int], ...]
    category: str
    first_seen: dt.datetime | None
    last_seen: dt.datetime | None
    thinking_turns: int

    @property
    def tools_per_turn(self) -> float:
        if self.total_turns == 0:
            return 0.0
        return self.total_tool_uses / self.total_turns


@dataclass(frozen=True)
class ProjectShape:
    project_name: str
    sessions: int
    total_turns: int
    total_tool_uses: int
    top_tools: tuple[tuple[str, int], ...] = ()

    @property
    def tools_per_turn(self) -> float:
        if self.total_turns == 0:
            return 0.0
        return self.total_tool_uses / self.total_turns


@dataclass(frozen=True)
class DailyShape:
    day: str
    turns: int
    tool_uses: int
    category: str = CATEGORY_NONE


@dataclass(frozen=True)
class SessionShapeReport:
    sessions: tuple[SessionShape, ...] = ()
    projects: tuple[ProjectShape, ...] = ()
    daily: tuple[DailyShape, ...] = ()
    tool_use: ToolUseBreakdown = field(
        default_factory=lambda: ToolUseBreakdown(total_calls=0, per_tool=())
    )
    category_counts: tuple[tuple[str, int], ...] = ()
    coverage_events: int = 0
    coverage_total_events: int = 0

    @property
    def total_sessions(self) -> int:
        return len(self.sessions)

    @property
    def total_turns(self) -> int:
        return sum(item.total_turns for item in self.sessions)

    @property
    def total_tool_uses(self) -> int:
        return self.tool_use.total_calls

    @property
    def tools_per_turn(self) -> float:
        turns = self.total_turns
        if turns == 0:
            return 0.0
        return self.total_tool_uses / turns


def classify_session(counter: Counter[str]) -> str:
    if not counter:
        return CATEGORY_NONE
    totals = {
        CATEGORY_EXPLORATION: sum(
            count for name, count in counter.items() if name in EXPLORATION_TOOLS
        ),
        CATEGORY_EXECUTION: sum(
            count for name, count in counter.items() if name in EXECUTION_TOOLS
        ),
        CATEGORY_DIAGNOSTIC: sum(
            count for name, count in counter.items() if name in DIAGNOSTIC_TOOLS
        ),
    }
    total = sum(counter.values())
    if total == 0:
        return CATEGORY_NONE
    top_category, top_value = max(totals.items(), key=lambda item: item[1])
    if top_value == 0:
        return CATEGORY_MIXED
    if top_value / total >= 0.5:
        return top_category
    return CATEGORY_MIXED


def compute_session_shape(result: LoadResult) -> SessionShapeReport:
    events = [event for event in result.events if event.turn_facts is not None]
    if not events:
        return SessionShapeReport(
            coverage_events=0,
            coverage_total_events=len(result.events),
        )

    session_acc: dict[str, _SessionAccumulator] = {}
    project_acc: dict[str, _ProjectAccumulator] = {}
    daily_acc: dict[str, _DailyAccumulator] = {}
    global_tool_counter: Counter[str] = Counter()

    for event in events:
        facts = event.turn_facts
        if facts is None:
            continue
        project = _project_name_for(event)
        session = session_acc.setdefault(
            event.session_id,
            _SessionAccumulator(
                session_id=event.session_id,
                project_name=project,
                vendor=event.vendor,
            ),
        )
        session.add(event, facts)

        project_state = project_acc.setdefault(project, _ProjectAccumulator(project_name=project))
        project_state.add(event, facts)

        day = event.timestamp.astimezone(dt.UTC).date().isoformat()
        day_state = daily_acc.setdefault(day, _DailyAccumulator(day=day))
        day_state.add(event.session_id, facts)

        for name in facts.tool_names:
            global_tool_counter[name] += 1
        if facts.tool_use_count and not facts.tool_names:
            global_tool_counter["unknown"] += facts.tool_use_count

    sessions = tuple(
        sorted(
            (state.build() for state in session_acc.values()),
            key=lambda item: (item.last_seen or dt.datetime.min, item.session_id),
            reverse=True,
        )
    )
    projects = tuple(
        sorted(
            (state.build() for state in project_acc.values()),
            key=lambda item: (-item.total_turns, item.project_name),
        )
    )
    daily = tuple(
        sorted(
            (state.build() for state in daily_acc.values()),
            key=lambda item: item.day,
        )
    )
    tool_use = ToolUseBreakdown(
        total_calls=sum(global_tool_counter.values()),
        per_tool=tuple(global_tool_counter.most_common()),
    )
    category_counter: Counter[str] = Counter(item.category for item in sessions)
    category_counts = tuple(category_counter.most_common())
    return SessionShapeReport(
        sessions=sessions,
        projects=projects,
        daily=daily,
        tool_use=tool_use,
        category_counts=category_counts,
        coverage_events=len(events),
        coverage_total_events=len(result.events),
    )


def _project_name_for(event: UsageEvent) -> str:
    if event.thread.cwd:
        return project_name_from_path(event.thread.cwd)
    return UNKNOWN_PROJECT


@dataclass
class _SessionAccumulator:
    session_id: str
    project_name: str
    vendor: str
    turn_indices: set[int] = field(default_factory=set)
    tools: Counter = field(default_factory=Counter)
    tool_use_total: int = 0
    thinking_turns: int = 0
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    def add(self, event: UsageEvent, facts) -> None:  # type: ignore[no-untyped-def]
        self.turn_indices.add(facts.turn_index)
        self.tool_use_total += facts.tool_use_count
        for name in facts.tool_names:
            self.tools[name] += 1
        if facts.has_thinking_block:
            self.thinking_turns += 1
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp

    def build(self) -> SessionShape:
        return SessionShape(
            session_id=self.session_id,
            project_name=self.project_name,
            vendor=self.vendor,
            total_turns=len(self.turn_indices),
            total_tool_uses=self.tool_use_total,
            tool_counts=tuple(self.tools.most_common()),
            category=classify_session(self.tools),
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            thinking_turns=self.thinking_turns,
        )


@dataclass
class _ProjectAccumulator:
    project_name: str
    session_ids: set[str] = field(default_factory=set)
    turn_keys: set[tuple[str, int]] = field(default_factory=set)
    tool_use_total: int = 0
    tools: Counter = field(default_factory=Counter)

    def add(self, event: UsageEvent, facts) -> None:  # type: ignore[no-untyped-def]
        self.session_ids.add(event.session_id)
        self.turn_keys.add((event.session_id, facts.turn_index))
        self.tool_use_total += facts.tool_use_count
        for name in facts.tool_names:
            self.tools[name] += 1

    def build(self) -> ProjectShape:
        return ProjectShape(
            project_name=self.project_name,
            sessions=len(self.session_ids),
            total_turns=len(self.turn_keys),
            total_tool_uses=self.tool_use_total,
            top_tools=tuple(self.tools.most_common(3)),
        )


@dataclass
class _DailyAccumulator:
    day: str
    turn_keys: set[tuple[str, int]] = field(default_factory=set)
    tool_use_total: int = 0
    tools: Counter = field(default_factory=Counter)

    def add(self, session_id: str, facts) -> None:  # type: ignore[no-untyped-def]
        self.turn_keys.add((session_id, facts.turn_index))
        self.tool_use_total += facts.tool_use_count
        for name in facts.tool_names:
            self.tools[name] += 1

    def build(self) -> DailyShape:
        return DailyShape(
            day=self.day,
            turns=len(self.turn_keys),
            tool_uses=self.tool_use_total,
            category=classify_session(self.tools),
        )
