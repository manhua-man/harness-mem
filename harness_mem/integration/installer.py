"""Generic IDE hook installer for the maintenance CLI.

The installer renders packaged templates into concrete hook/config artifacts for
multiple host families:

- shell hook files (Cursor, Claude Code)
- JSON hook manifests (Grok, Codex)
- plugin source files (OpenCode)

Every generated command is bound to one verified, absolute
``harness-mem-hook`` console entry. The check runs at install time, before the
file is written, so a drifting template cannot reintroduce a bare ``python``
runtime dependency.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from string import Template

from harness_mem.integration.hook_runner import probe_hook_runner, resolve_hook_runner

__all__ = [
    "DEFAULT_DOC_POINTER",
    "HookInstallResult",
    "HookSpec",
    "verified_hook_runner",
    "install_antigravity_hook_suite",
    "install_hermes_hook_suite",
    "install_hook",
    "install_hook_suite",
]

# Default documentation pointer baked into generated hook headers.
DEFAULT_DOC_POINTER = "docs/quickstart.md"

_TEMPLATES_PACKAGE = "harness_mem.integration.templates"
_LEGACY_HOST_ENTRY = "harness_mem.host_entry"
_FORBIDDEN_PYTHON_HOST_ENTRY = re.compile(r"^[^#]*\bpython(?:3)?\s+-m\s+harness_mem\.host_entry")
_HERMES_CONFIG_DIRNAME = ".hermes"
_HERMES_CONFIG_FILENAME = "config.yaml"
_HERMES_PRE_LLM_EVENT = "pre_llm_call"
_HERMES_POST_LLM_EVENT = "post_llm_call"
_HERMES_EVENT_LINE = re.compile(r"^  [A-Za-z0-9_:-]+:(?:\s*.*)?$")
_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z0-9_:-]+:(?:\s*.*)?$")


def _render(
    body: str,
    *,
    project_root_abs: str,
    harness_mem_version: str,
    generated_at_iso: str,
    doc_pointer: str,
    hook_runner: Path,
    template_vars: Mapping[str, str] | None = None,
) -> str:
    """Substitute the four documented variables into the template body.

    Uses :meth:`string.Template.substitute` (not ``safe_substitute``) so a
    template referencing an undefined variable raises ``KeyError`` and surfaces
    template/installer drift loudly instead of silently emitting ``${FOO}``.
    """
    render_vars: dict[str, str] = {
        "PROJECT_ROOT": project_root_abs,
        "PROJECT_ROOT_SHELL": shlex.quote(project_root_abs),
        "PROJECT_ROOT_JSON": json.dumps(project_root_abs),
        "PROJECT_ROOT_BASENAME": Path(project_root_abs).name,
        "HARNESS_MEM_VERSION": harness_mem_version,
        "HARNESS_MEM_VERSION_JSON": json.dumps(harness_mem_version),
        "GENERATED_AT": generated_at_iso,
        "GENERATED_AT_JSON": json.dumps(generated_at_iso),
        "DOC_POINTER": doc_pointer,
        "DOC_POINTER_JSON": json.dumps(doc_pointer),
        "HOOK_RUNNER": hook_runner.as_posix(),
        "HOOK_RUNNER_SHELL": shlex.quote(hook_runner.as_posix()),
        "HOOK_RUNNER_JSON": json.dumps(hook_runner.as_posix()),
    }
    if template_vars:
        render_vars.update(template_vars)
    return Template(body).substitute(render_vars)


def _assert_boundary(rendered: str, *, hook_runner: Path) -> None:
    """Enforce the hook boundary on a rendered body.

    Raises:
        RuntimeError: the body is missing the verified Hook runner, an action,
            or contains a legacy bare-Python host entry invocation.
    """
    if hook_runner.as_posix() not in rendered:
        raise RuntimeError("rendered template contains forbidden pattern")
    compact = re.sub(r"[\s\"']+", "", rendered)
    if not any(
        action in rendered or f"--action,{action}" in compact
        for action in ("dream-end", "post-turn-maintenance", "wake-start")
    ) and "--adapter" not in rendered:
        raise RuntimeError("rendered template contains forbidden pattern")
    for line in rendered.splitlines():
        if _FORBIDDEN_PYTHON_HOST_ENTRY.search(line):
            raise RuntimeError("rendered template contains forbidden pattern")


def verified_hook_runner() -> Path:
    """Return the installed Hook executable after a bounded version probe."""

    path = resolve_hook_runner()
    probe = probe_hook_runner(hook_runner=path)
    if not probe.ok:
        raise RuntimeError(f"harness-mem-hook is unavailable: {probe.error or 'unknown error'}")
    return path


def _is_legacy_hook(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _LEGACY_HOST_ENTRY in text


def install_hook(
    *,
    template_name: str,
    target_path: Path,
    project_root: Path,
    force: bool = False,
    harness_mem_version: str,
    generated_at: datetime,
    doc_pointer: str = DEFAULT_DOC_POINTER,
    template_vars: Mapping[str, str] | None = None,
    hook_runner: Path | None = None,
) -> Path:
    """Render a Hook_Template and write it to ``target_path``.

    Substitutes ``${PROJECT_ROOT}`` (the absolute path of ``project_root`` at
    generation time), ``${HARNESS_MEM_VERSION}``, ``${GENERATED_AT}`` (ISO 8601
    rendering of ``generated_at``), and ``${DOC_POINTER}`` into the template
    body. The file is written only when ``target_path`` does not exist or
    ``force=True``.

    Args:
        template_name: File name under ``harness_mem.integration.templates``.
        target_path: Destination path for the generated hook script.
        project_root: Repo whose absolute path is baked into the hook.
        force: Overwrite an existing ``target_path`` when ``True``.
        harness_mem_version: Version string for the comment header.
        generated_at: Generation timestamp for the comment header.
        doc_pointer: Documentation path baked into the header.

    Returns:
        The absolute :class:`~pathlib.Path` written.

    Raises:
        FileExistsError: ``target_path`` exists and ``force`` is ``False``.
        RuntimeError: the rendered body violates the hook boundary.
        KeyError: the template references an undefined substitution variable.
        OSError: the file or its parent directory cannot be written.
    """
    if target_path.exists() and not force and not _is_legacy_hook(target_path):
        raise FileExistsError(str(target_path))

    resolved_root = Path(project_root).resolve()
    resolved_runner = Path(hook_runner).resolve() if hook_runner is not None else verified_hook_runner()
    body = (
        resources.files(_TEMPLATES_PACKAGE)
        .joinpath(template_name)
        .read_text(encoding="utf-8")
    )
    rendered = _render(
        body,
        project_root_abs=resolved_root.as_posix(),
        harness_mem_version=harness_mem_version,
        generated_at_iso=generated_at.isoformat(),
        doc_pointer=doc_pointer,
        hook_runner=resolved_runner,
        template_vars=template_vars,
    )
    _assert_boundary(rendered, hook_runner=resolved_runner)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(rendered, encoding="utf-8")
    if os.name == "posix":
        os.chmod(target_path, 0o755)
    return target_path.resolve()


@dataclass(frozen=True)
class HookSpec:
    """One IDE hook template and its destination path."""

    template_name: str
    target_path: Path
    template_vars: Mapping[str, str] | None = None


@dataclass(frozen=True)
class HookInstallResult:
    """Result of installing one hook script in a suite."""

    target_path: Path
    status: str


def install_hook_suite(
    *,
    specs: list[HookSpec] | tuple[HookSpec, ...],
    project_root: Path,
    force: bool = False,
    harness_mem_version: str,
    generated_at: datetime,
    doc_pointer: str = DEFAULT_DOC_POINTER,
    hook_runner: Path | None = None,
) -> list[HookInstallResult]:
    """Install a set of hooks idempotently.

    Existing files are reported as ``exists`` unless ``force`` is set. Missing
    files are rendered with the same boundary checks as :func:`install_hook`.
    """

    resolved_runner = Path(hook_runner).resolve() if hook_runner is not None else verified_hook_runner()
    results: list[HookInstallResult] = []
    for spec in specs:
        target_existed = spec.target_path.exists()
        if target_existed and not force:
            if _is_legacy_hook(spec.target_path):
                written = install_hook(
                    template_name=spec.template_name,
                    target_path=spec.target_path,
                    project_root=project_root,
                    force=True,
                    harness_mem_version=harness_mem_version,
                    generated_at=generated_at,
                    doc_pointer=doc_pointer,
                    template_vars=spec.template_vars,
                    hook_runner=resolved_runner,
                )
                results.append(HookInstallResult(target_path=written, status="updated"))
                continue
            results.append(
                HookInstallResult(
                    target_path=spec.target_path.resolve(),
                    status="exists",
                )
            )
            continue
        written = install_hook(
            template_name=spec.template_name,
            target_path=spec.target_path,
            project_root=project_root,
            force=force,
            harness_mem_version=harness_mem_version,
            generated_at=generated_at,
            doc_pointer=doc_pointer,
            template_vars=spec.template_vars,
            hook_runner=resolved_runner,
        )
        results.append(
            HookInstallResult(
                target_path=written,
                status="updated" if target_existed else "installed",
            )
        )
    return results


def install_antigravity_hook_suite(
    *,
    project_root: Path,
    force: bool = False,
    harness_mem_version: str,
    generated_at: datetime,
    doc_pointer: str = DEFAULT_DOC_POINTER,
    hook_runner: Path | None = None,
) -> list[HookInstallResult]:
    """Install Antigravity event entries bound to the Hook console entry."""

    root = project_root.resolve()
    resolved_runner = Path(hook_runner).resolve() if hook_runner is not None else verified_hook_runner()

    manifest_path = root / ".agents" / "hooks.json"
    before = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    try:
        manifest = json.loads(before) if before.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Antigravity hooks JSON: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"invalid Antigravity hooks JSON object: {manifest_path}")
    hooks = manifest.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"invalid Antigravity hooks mapping: {manifest_path}")

    managed = {
        "PreInvocation": (
            ("--adapter antigravity-pre", "harness_mem_pre_invocation.py"),
            _antigravity_hook_group(resolved_runner, "antigravity-pre", root),
        ),
        "Stop": (
            ("--adapter antigravity-stop", "harness_mem_stop.py"),
            _antigravity_hook_group(resolved_runner, "antigravity-stop", root),
        ),
    }
    for event, (markers, group) in managed.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"invalid Antigravity {event} hook list: {manifest_path}")
        groups[:] = [
            existing
            for existing in groups
            if not any(marker in json.dumps(existing, sort_keys=True) for marker in markers)
        ]
        groups.append(group)

    after = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if after != before:
        manifest_path.write_text(after, encoding="utf-8")
        status = "updated" if before else "installed"
    else:
        status = "exists"
    return [HookInstallResult(target_path=manifest_path.resolve(), status=status)]


def _antigravity_hook_group(hook_runner: Path, adapter: str, project_root: Path) -> dict[str, object]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": _hook_command(hook_runner, "--adapter", adapter, "--project-root", project_root.as_posix()),
            }
        ]
    }


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _join_lines(lines: list[str], newline: str) -> str:
    if not lines:
        return ""
    return newline.join(lines) + newline


def _find_top_level_key(lines: list[str], key: str) -> int | None:
    prefix = f"{key}:"
    for idx, line in enumerate(lines):
        if line.startswith(prefix) and (line == prefix or line[len(prefix)] in " #{"):
            return idx
    return None


def _find_top_level_block_end(lines: list[str], start: int) -> int:
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if _TOP_LEVEL_KEY.match(line):
            return idx
    return len(lines)


def _find_hermes_event_start(lines: list[str], start: int, end: int, event: str) -> int | None:
    prefix = f"  {event}:"
    for idx in range(start + 1, end):
        if lines[idx].startswith(prefix):
            return idx
    return None


def _find_hermes_event_end(lines: list[str], start: int, end: int) -> int:
    for idx in range(start + 1, end):
        if _HERMES_EVENT_LINE.match(lines[idx]):
            return idx
    return end


def _hermes_item_lines(event: str, command: str, timeout: int) -> list[str]:
    return [
        f"    # harness-mem:begin {event}",
        f"    - command: {json.dumps(command)}",
        f"      timeout: {timeout}",
        f"    # harness-mem:end {event}",
    ]


def _ensure_hermes_event(
    lines: list[str],
    *,
    hooks_start: int,
    event: str,
    command: str,
    timeout: int,
) -> list[str]:
    hooks_end = _find_top_level_block_end(lines, hooks_start)
    event_start = _find_hermes_event_start(lines, hooks_start, hooks_end, event)
    managed = _hermes_item_lines(event, command, timeout)

    if event_start is None:
        insert_at = hooks_end
        return lines[:insert_at] + [f"  {event}:"] + managed + lines[insert_at:]

    updated = list(lines)
    if updated[event_start].strip() != f"{event}:":
        updated[event_start] = f"  {event}:"
    event_end = _find_hermes_event_end(updated, event_start, hooks_end)

    begin_marker = f"# harness-mem:begin {event}"
    end_marker = f"# harness-mem:end {event}"
    begin_idx: int | None = None
    end_idx: int | None = None
    for idx in range(event_start + 1, event_end):
        stripped = updated[idx].strip()
        if stripped == begin_marker:
            begin_idx = idx
        if stripped == end_marker:
            end_idx = idx
            break

    if begin_idx is not None and end_idx is not None and begin_idx <= end_idx:
        return updated[:begin_idx] + managed + updated[end_idx + 1 :]

    insert_at = event_start + 1
    return updated[:insert_at] + managed + updated[insert_at:]


def _merge_hermes_config(text: str, *, pre_command: str, post_command: str) -> str:
    newline = _detect_newline(text)
    lines = text.splitlines()

    hooks_start = _find_top_level_key(lines, "hooks")
    if hooks_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("hooks:")
        hooks_start = len(lines) - 1
    elif re.match(r"^hooks:\s*(\{\s*\}|\[\s*\])\s*$", lines[hooks_start]):
        lines[hooks_start] = "hooks:"

    lines = _ensure_hermes_event(
        lines,
        hooks_start=hooks_start,
        event=_HERMES_PRE_LLM_EVENT,
        command=pre_command,
        timeout=30,
    )
    lines = _ensure_hermes_event(
        lines,
        hooks_start=hooks_start,
        event=_HERMES_POST_LLM_EVENT,
        command=post_command,
        timeout=300,
    )
    return _join_lines(lines, newline)


def install_hermes_hook_suite(
    *,
    project_root: Path,
    force: bool = False,
    harness_mem_version: str,
    generated_at: datetime,
    doc_pointer: str = DEFAULT_DOC_POINTER,
    home_dir: Path | None = None,
    hook_runner: Path | None = None,
) -> list[HookInstallResult]:
    """Install Hermes event entries bound to the Hook console entry."""

    home = Path.home() if home_dir is None else home_dir
    hermes_root = home / _HERMES_CONFIG_DIRNAME
    config_path = hermes_root / _HERMES_CONFIG_FILENAME
    resolved_runner = Path(hook_runner).resolve() if hook_runner is not None else verified_hook_runner()
    pre_command = _hook_command(resolved_runner, "--adapter", "hermes-pre")
    post_command = _hook_command(resolved_runner, "--adapter", "hermes-post")
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    after = _merge_hermes_config(
        before,
        pre_command=pre_command,
        post_command=post_command,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if after != before:
        config_path.write_text(after, encoding="utf-8")
        status = "updated" if before else "installed"
    else:
        status = "exists"

    return [HookInstallResult(target_path=config_path.resolve(), status=status)]


def _hook_command(hook_runner: Path, *args: str) -> str:
    """Quote a Hook console invocation for shell-style host command fields."""

    return " ".join(shlex.quote(value) for value in (hook_runner.as_posix(), *args))
