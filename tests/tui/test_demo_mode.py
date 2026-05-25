from __future__ import annotations

from caliper.config import build_options
from caliper.models import VENDOR_OPENAI_CODEX
from caliper.tui.app import CaliperApp
from caliper.tui.demo import materialize_demo
from caliper.vendors import vendor_file_count


def test_demo_mode_is_scoped_to_synthetic_codex_files(tmp_path, monkeypatch) -> None:
    claude_file = tmp_path / "claude" / "projects" / "p" / "session.jsonl"
    claude_file.parent.mkdir(parents=True)
    claude_file.write_text("{}\n")
    cursor_file = tmp_path / "cursor" / "chats" / "session.jsonl"
    cursor_file.parent.mkdir(parents=True)
    cursor_file.write_text("{}\n")
    aider_file = tmp_path / "aider" / "repo" / ".aider.chat.history.md"
    aider_file.parent.mkdir(parents=True)
    aider_file.write_text("Tokens: 1k sent, 1 received. Cost: $0.01 message, $0.01 session.\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))

    template = build_options(
        days=90,
        session_root=tmp_path / "real-codex",
        state_db=tmp_path / "real-state.sqlite",
        codex_config=tmp_path / "real-config.toml",
    )
    options = materialize_demo(template)

    assert options.vendors == (VENDOR_OPENAI_CODEX,)
    assert options.session_root != template.session_root
    assert options.state_db.parent == options.session_root
    assert options.config_path.parent == options.session_root
    assert vendor_file_count(options) == 30


def test_demo_app_cleans_synthetic_root(tmp_path) -> None:
    template = build_options(
        days=90,
        session_root=tmp_path / "real-codex",
        state_db=tmp_path / "real-state.sqlite",
        codex_config=tmp_path / "real-config.toml",
    )
    app = CaliperApp(template, demo=True)
    root = app.snapshot.options.session_root

    assert root.exists()

    app._cleanup_demo_root()

    assert not root.exists()
