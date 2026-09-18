"""Provider selection and command parsing. No network."""

import os

import pytest

from jev_usecases.llm import resolve_llm
from jev_usecases.use_cases.security_copilot import _parse_command


def test_parse_command_json():
    command, why = _parse_command('{"command": "ss -lntp", "why": "list listeners"}')
    assert command == "ss -lntp"
    assert "listeners" in why


def test_parse_command_fenced():
    command, _why = _parse_command('```json\n{"command": "ss -lntp", "why": "ports"}\n```')
    assert command == "ss -lntp"


def test_prefers_claude_over_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-claude-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    cfg = resolve_llm()
    assert cfg.provider == "anthropic"
    assert cfg.key_env == "ANTHROPIC_API_KEY"
    assert cfg.model == "claude-sonnet-4-5"


def test_falls_back_to_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    cfg = resolve_llm()
    assert cfg.provider == "openai"
    assert cfg.key_env == "OPENAI_API_KEY"
    assert os.getenv("OPENAI_API_KEY")
