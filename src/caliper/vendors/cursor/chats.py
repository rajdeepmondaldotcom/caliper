from __future__ import annotations

from pathlib import Path

from caliper.models import UsageEvent
from caliper.vendors.cursor.projects import parse_project_jsonl


def parse_chat_jsonl(path: Path) -> list[UsageEvent]:
    return parse_project_jsonl(path)
