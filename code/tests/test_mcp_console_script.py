from __future__ import annotations

import builtins
import logging
from pathlib import Path

from harness_mem.commands import token_estimator


def test_package_has_no_user_command_or_memory_server_entrypoint() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "harness-mem-mcp" not in pyproject
    assert 'harness-mem = "harness_mem.cli:main"' not in pyproject


def test_hook_console_script_uses_the_packaged_host_entrypoint() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'harness-mem-hook = "harness_mem.host_entry.__main__:main"' in pyproject


def test_missing_optional_tiktoken_logs_a_concise_fallback_warning(
    monkeypatch, caplog, request
) -> None:
    original_import = builtins.__import__

    def missing_tiktoken(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("no module named tiktoken")
        return original_import(name, *args, **kwargs)

    token_estimator.reset_for_tests()
    request.addfinalizer(token_estimator.reset_for_tests)
    monkeypatch.setattr(builtins, "__import__", missing_tiktoken)
    caplog.set_level(logging.WARNING, logger="harness_mem.commands.token_estimator")

    assert token_estimator.count_tokens("a short message") == 3
    assert "optional tiktoken is not installed" in caplog.text
    assert "Traceback" not in caplog.text
