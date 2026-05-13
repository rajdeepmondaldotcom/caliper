from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from caliper.models import VENDOR_OPENAI_CODEX, LoadResult, RuntimeOptions


@dataclass(frozen=True)
class CodexParser:
    id: str = VENDOR_OPENAI_CODEX
    label: str = "OpenAI Codex"
    schema_version: str = "1"

    def discover(self, options: RuntimeOptions) -> list[Path]:
        from caliper.parser import session_files

        return list(session_files(options.session_root))

    def parse(self, options: RuntimeOptions) -> LoadResult:
        from caliper.parser import load_codex_usage

        return load_codex_usage(options)


PARSER = CodexParser()
