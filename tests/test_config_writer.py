"""Tests for ``harness_mem.config.writer.set_value`` (v2.4.3 Task 1, Req 2).

HOME isolation
--------------
``set_value`` resolves the user-level config path via ``Path.home()`` (Req 2.3),
mirroring ``load_merged_config``. Tests redirect that lookup to a tmp directory
by monkeypatching ``Path.home`` so no test ever writes the real
``~/.harness-mem/config.toml`` (project rule P1: data-path isolation). A
``project`` directory under ``tmp_path`` stands in for the project root.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from harness_mem.config.errors import ConfigParseError, ConfigValidationError
from harness_mem.config.merge import _RECOGNIZED_KEYS, load_merged_config
from harness_mem.config.writer import set_value


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` to an isolated tmp dir for user-config writes."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An existing absolute project directory under tmp_path."""
    proj = tmp_path / "project"
    proj.mkdir()
    return proj


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---- tomli_w dependency is importable (Req: Task 1.10) -------------------


def test_tomli_w_is_importable() -> None:
    import tomli_w

    assert hasattr(tomli_w, "dumps")


# ---- round-trip set -> read for every Recognized_Key allowed value -------


@pytest.mark.parametrize(
    ("key_path", "value"),
    [
        (key_path, value)
        for key_path, _attr, allowed, _default in _RECOGNIZED_KEYS
        for value in allowed
    ],
)
def test_round_trip_recognized_keys_user_scope(
    home_dir: Path, project_dir: Path, key_path: str, value: str
) -> None:
    target = set_value(
        scope="user", project_root=project_dir, key_path=key_path, value=value
    )
    found, resolved = _get_dotted(_read_toml(target), key_path)
    assert found
    assert resolved == value


@pytest.mark.parametrize(
    ("key_path", "value"),
    [
        (key_path, value)
        for key_path, _attr, allowed, _default in _RECOGNIZED_KEYS
        for value in allowed
    ],
)
def test_round_trip_recognized_keys_project_scope(
    home_dir: Path, project_dir: Path, key_path: str, value: str
) -> None:
    target = set_value(
        scope="project", project_root=project_dir, key_path=key_path, value=value
    )
    found, resolved = _get_dotted(_read_toml(target), key_path)
    assert found
    assert resolved == value


def _get_dotted(d: dict, dotted: str) -> tuple[bool, object]:
    cur: object = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return (False, None)
        cur = cur[part]
    return (True, cur)


# ---- set value survives the v2.4.1 loader round-trip ---------------------


def test_set_value_then_load_merged_config_reads_it_back(
    home_dir: Path, project_dir: Path
) -> None:
    set_value(
        scope="project",
        project_root=project_dir,
        key_path="distill.mode",
        value="worker",
    )
    cfg = load_merged_config(str(project_dir))
    assert cfg.distill_mode == "worker"


# ---- preserve pre-existing keys (Req 2.6) --------------------------------


def test_preserves_other_keys(home_dir: Path, project_dir: Path) -> None:
    target = project_dir / ".harness-mem.toml"
    target.write_text(
        '[logging]\nlevel = "debug"\n[triggers]\nscheduler = "on"\n',
        encoding="utf-8",
    )
    set_value(
        scope="project",
        project_root=project_dir,
        key_path="triggers.after_agent",
        value="on",
    )
    data = _read_toml(target)
    assert data["triggers"]["after_agent"] == "on"
    # Pre-existing sibling + unrelated table survive untouched.
    assert data["triggers"]["scheduler"] == "on"
    assert data["logging"]["level"] == "debug"


def test_preserves_non_recognized_key(home_dir: Path, project_dir: Path) -> None:
    target = set_value(
        scope="project",
        project_root=project_dir,
        key_path="telemetry.endpoint",
        value="https://example.test",
    )
    assert _read_toml(target)["telemetry"]["endpoint"] == "https://example.test"


# ---- create file + parent dir when absent (Req 2.3) ----------------------


def test_creates_user_file_and_parent_dir_when_absent(
    home_dir: Path, project_dir: Path
) -> None:
    cfg_dir = home_dir / ".harness-mem"
    assert not cfg_dir.exists()
    target = set_value(
        scope="user",
        project_root=project_dir,
        key_path="worker.mode",
        value="on",
    )
    assert target == (cfg_dir / "config.toml").resolve()
    assert target.is_file()
    assert _read_toml(target)["worker"]["mode"] == "on"


def test_creates_project_file_when_absent(
    home_dir: Path, project_dir: Path
) -> None:
    target = project_dir / ".harness-mem.toml"
    assert not target.exists()
    result = set_value(
        scope="project",
        project_root=project_dir,
        key_path="triggers.after_agent",
        value="on",
    )
    assert result == target.resolve()
    assert target.is_file()


# ---- reject invalid Recognized_Key value (Req 2.5) -----------------------


def test_invalid_recognized_value_raises_and_does_not_write(
    home_dir: Path, project_dir: Path
) -> None:
    target = project_dir / ".harness-mem.toml"
    with pytest.raises(ConfigValidationError) as excinfo:
        set_value(
            scope="project",
            project_root=project_dir,
            key_path="triggers.after_agent",
            value="sometimes",
        )
    err = excinfo.value
    assert err.key_path == "triggers.after_agent"
    assert err.value == "sometimes"
    assert err.source_path == str(target)
    # Req 2.5: the file must not be created when validation fails.
    assert not target.exists()


def test_invalid_value_does_not_clobber_existing_file(
    home_dir: Path, project_dir: Path
) -> None:
    target = project_dir / ".harness-mem.toml"
    original = '[triggers]\nafter_agent = "on"\n'
    target.write_text(original, encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        set_value(
            scope="project",
            project_root=project_dir,
            key_path="distill.mode",
            value="nonsense",
        )
    # File is byte-identical: validation happens before any write.
    assert target.read_text(encoding="utf-8") == original


# ---- user scope vs project scope hit the correct path --------------------


def test_user_scope_writes_user_path_only(
    home_dir: Path, project_dir: Path
) -> None:
    set_value(
        scope="user",
        project_root=project_dir,
        key_path="worker.mode",
        value="on",
    )
    assert (home_dir / ".harness-mem" / "config.toml").is_file()
    assert not (project_dir / ".harness-mem.toml").exists()


def test_project_scope_writes_project_path_only(
    home_dir: Path, project_dir: Path
) -> None:
    set_value(
        scope="project",
        project_root=project_dir,
        key_path="worker.mode",
        value="on",
    )
    assert (project_dir / ".harness-mem.toml").is_file()
    assert not (home_dir / ".harness-mem" / "config.toml").exists()


# ---- malformed existing TOML surfaces as ConfigParseError ----------------


def test_malformed_existing_file_raises_parse_error(
    home_dir: Path, project_dir: Path
) -> None:
    target = project_dir / ".harness-mem.toml"
    target.write_text("this is = = not valid toml\n", encoding="utf-8")
    with pytest.raises(ConfigParseError) as excinfo:
        set_value(
            scope="project",
            project_root=project_dir,
            key_path="worker.mode",
            value="on",
        )
    assert excinfo.value.source_path == str(target)
