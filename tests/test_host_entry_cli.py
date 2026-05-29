"""Tests for the host-entry CLI main module (v2.4.1 Task 4, Req 1, 2, 5, 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.config.merge import MergedConfig
from harness_mem.host_entry.__main__ import (
    apply_config_overrides,
    build_parser,
    main,
    run,
    validate_args,
)
from tests.helpers import run as run_async


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


def _isolate_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


# ---- build_parser: required args + choices (Req 2.2, 2.3, 2.7) -----------


def test_build_parser_missing_project_root_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(["--source", "ide_hook"])
    assert exc.value.code == 2


def test_build_parser_missing_source_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(["--project-root", "/tmp/x"])
    assert exc.value.code == 2


def test_build_parser_invalid_source_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(["--project-root", "/tmp/x", "--source", "bogus"])
    assert exc.value.code == 2


def test_build_parser_unknown_flag_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(["--project-root", "/tmp/x", "--source", "user", "--nope", "1"])
    assert exc.value.code == 2


def test_build_parser_defaults(tmp_path: Path) -> None:
    args = _parse(["--project-root", str(tmp_path), "--source", "user"])
    assert args.trigger_id is None
    assert args.session_ids == []
    assert args.config_override == []


def test_build_parser_no_abbreviation() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse(["--project", "/tmp/x", "--source", "user"])
    assert exc.value.code == 2


# ---- validate_args bounds (Req 2.2, 2.4, 2.5) ----------------------------


def test_validate_args_valid(tmp_path: Path) -> None:
    args = _parse(["--project-root", str(tmp_path), "--source", "user"])
    assert validate_args(args) is None


def test_validate_args_non_absolute_project_root(tmp_path: Path) -> None:
    args = _parse(["--project-root", "relative/path", "--source", "user"])
    err = validate_args(args)
    assert err is not None
    assert "--project-root" in err
    assert "absolute" in err


def test_validate_args_nonexistent_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    args = _parse(["--project-root", str(missing), "--source", "user"])
    err = validate_args(args)
    assert err is not None
    assert "--project-root" in err
    assert "existing directory" in err


def test_validate_args_project_root_too_long() -> None:
    long_path = "/" + "a" * 5000
    args = _parse(["--project-root", long_path, "--source", "user"])
    err = validate_args(args)
    assert err is not None
    assert "--project-root" in err
    assert "4096" in err


def test_validate_args_trigger_id_too_long(tmp_path: Path) -> None:
    args = _parse(
        [
            "--project-root",
            str(tmp_path),
            "--source",
            "user",
            "--trigger-id",
            "t" * 257,
        ]
    )
    err = validate_args(args)
    assert err is not None
    assert "--trigger-id" in err
    assert "256" in err


def test_validate_args_too_many_session_ids(tmp_path: Path) -> None:
    args = _parse(
        ["--project-root", str(tmp_path), "--source", "user", "--session-ids"]
        + [f"s{i}" for i in range(1025)]
    )
    err = validate_args(args)
    assert err is not None
    assert "--session-ids" in err
    assert "1024" in err


def test_validate_args_session_id_too_long(tmp_path: Path) -> None:
    args = _parse(
        [
            "--project-root",
            str(tmp_path),
            "--source",
            "user",
            "--session-ids",
            "ok",
            "x" * 257,
        ]
    )
    err = validate_args(args)
    assert err is not None
    assert "--session-ids" in err
    assert "256" in err


# ---- apply_config_overrides (Req 2.6) ------------------------------------


def test_apply_config_overrides_flips_trigger() -> None:
    base = MergedConfig()
    result = apply_config_overrides(base, ["triggers.after_agent=on"])
    assert result.triggers_after_agent == "on"
    assert base.triggers_after_agent == "off"
    assert result is not base


def test_apply_config_overrides_flips_distill_mode() -> None:
    base = MergedConfig()
    result = apply_config_overrides(base, ["distill.mode=worker"])
    assert result.distill_mode == "worker"
    assert base.distill_mode == "defer_to_agent"


def test_apply_config_overrides_multiple_tokens() -> None:
    base = MergedConfig()
    result = apply_config_overrides(
        base, ["triggers.after_agent=on", "worker.mode=on"]
    )
    assert result.triggers_after_agent == "on"
    assert result.worker_mode == "on"


def test_apply_config_overrides_empty_is_noop() -> None:
    base = MergedConfig()
    result = apply_config_overrides(base, [])
    assert result == base


def test_apply_config_overrides_malformed_raises() -> None:
    with pytest.raises(ValueError):
        apply_config_overrides(MergedConfig(), ["noequals"])


def test_apply_config_overrides_unrecognized_key_raises() -> None:
    with pytest.raises(ValueError):
        apply_config_overrides(MergedConfig(), ["foo.bar=x"])


def test_apply_config_overrides_value_with_equals_sign() -> None:
    result = apply_config_overrides(MergedConfig(), ["distill.mode=a=b"])
    assert result.distill_mode == "a=b"


# ---- run(): default-off short-circuit (Req 4.1, 4.2, 4.3, 5.8) -----------


def test_run_default_off_skips_without_reflection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    called = {"hit": False}

    async def _boom(*a, **k):  # pragma: no cover
        called["hit"] = True
        raise AssertionError("reflection_once must not be called in default-off path")

    import harness_mem.commands.reflection_jobs as rj

    monkeypatch.setattr(rj, "reflection_once", _boom)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))

    assert exit_code == 0
    assert payload is not None
    doc = json.loads(payload)
    assert doc["status"] == "skipped_default_off"
    assert called["hit"] is False
    assert not (home / ".harness-mem" / "data").exists()


def test_run_bad_project_root_returns_arg_error(tmp_path: Path) -> None:
    args = _parse(["--project-root", "relative/path", "--source", "user"])
    exit_code, payload = run_async(run(args))
    assert exit_code == 2
    assert payload is None


def test_run_malformed_override_returns_arg_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    args = _parse(
        [
            "--project-root",
            str(project_root),
            "--source",
            "user",
            "--config-override",
            "noequals",
        ]
    )
    exit_code, payload = run_async(run(args))
    assert exit_code == 2
    assert payload is None


def test_run_invalid_config_returns_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "maybe"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))
    assert exit_code == 3
    assert payload is None


# ---- main(): stdout/stderr discipline (Req 5.7) --------------------------


def test_main_default_off_writes_one_json_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    code = main(["--project-root", str(project_root), "--source", "ide_hook"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.endswith("\n")
    lines = captured.out.splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["status"] == "skipped_default_off"
    assert "skipped_default_off" not in captured.err


def test_main_arg_error_writes_no_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    code = main(["--project-root", "relative/path", "--source", "user"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""


def test_main_stdout_is_pure_json_on_default_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _isolate_home(monkeypatch, home)

    main(["--project-root", str(project_root), "--source", "scheduler"])
    captured = capsys.readouterr()

    doc = json.loads(captured.out.strip())
    assert set(doc.keys()) == {
        "phase",
        "status",
        "next_step",
        "job_id",
        "candidates_written",
        "observations_written",
        "error",
    }
