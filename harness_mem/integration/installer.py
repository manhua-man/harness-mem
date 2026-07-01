"""Generic IDE hook installer for the maintenance CLI.

The installer renders packaged templates into concrete hook/config artifacts for
multiple host families:

- shell hook files (Cursor, Claude Code)
- JSON hook manifests (Grok, Codex)
- helper wrapper scripts (Codex, Hermes)
- plugin source files (OpenCode)

Boundary self-check: after substitution the rendered body MUST contain a
``harness_mem.host_entry`` invocation with an explicit hook action and MUST NOT
contain any non-comment line that invokes the ``harness-mem`` console script.
The check runs at install time, before the file is written, so a drifting
template can never produce a violating artifact on disk.
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

__all__ = [
    "DEFAULT_DOC_POINTER",
    "HookInstallResult",
    "HookSpec",
    "install_hermes_hook_suite",
    "install_hook",
    "install_hook_suite",
]

# Default documentation pointer baked into generated hook headers.
DEFAULT_DOC_POINTER = "docs/quickstart.md"

_TEMPLATES_PACKAGE = "harness_mem.integration.templates"
_REQUIRED_HOST_ENTRY = "harness_mem.host_entry"
# An executable invocation of the console script: a non-comment line where
# ``harness-mem`` is followed by whitespace and at least one more argument.
# ``^[^#]*`` cannot cross a ``#``, so any comment (leading or inline) is exempt.
_FORBIDDEN_INVOCATION = re.compile(r"^[^#]*\bharness-mem\s+\S")
_HERMES_CONFIG_DIRNAME = ".hermes"
_HERMES_AGENT_HOOK_DIRNAME = "agent-hooks"
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
    }
    if template_vars:
        render_vars.update(template_vars)
    return Template(body).substitute(render_vars)


def _assert_boundary(rendered: str) -> None:
    """Enforce the hook boundary on a rendered body.

    Raises:
        RuntimeError: the body is missing the host-entry invocation or contains
            a non-comment ``harness-mem`` console-script invocation.
    """
    if _REQUIRED_HOST_ENTRY not in rendered:
        raise RuntimeError("rendered template contains forbidden pattern")
    if (
        "dream-end" not in rendered
        and "post-turn-maintenance" not in rendered
        and "wake-start" not in rendered
    ):
        raise RuntimeError("rendered template contains forbidden pattern")
    for line in rendered.splitlines():
        if _FORBIDDEN_INVOCATION.search(line):
            raise RuntimeError("rendered template contains forbidden pattern")


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
    if target_path.exists() and not force:
        raise FileExistsError(str(target_path))

    resolved_root = Path(project_root).resolve()
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
        template_vars=template_vars,
    )
    _assert_boundary(rendered)

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
) -> list[HookInstallResult]:
    """Install a set of hooks idempotently.

    Existing files are reported as ``exists`` unless ``force`` is set. Missing
    files are rendered with the same boundary checks as :func:`install_hook`.
    """

    results: list[HookInstallResult] = []
    for spec in specs:
        if spec.target_path.exists() and not force:
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
        )
        results.append(HookInstallResult(target_path=written, status="installed"))
    return results


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
) -> list[HookInstallResult]:
    """Install Hermes helper scripts plus managed shell-hook config entries."""

    home = Path.home() if home_dir is None else home_dir
    hermes_root = home / _HERMES_CONFIG_DIRNAME
    hook_dir = hermes_root / _HERMES_AGENT_HOOK_DIRNAME
    config_path = hermes_root / _HERMES_CONFIG_FILENAME
    pre_script = hook_dir / "harness_mem_pre_llm_call.py"
    post_script = hook_dir / "harness_mem_post_llm_call.py"

    script_results = install_hook_suite(
        specs=(
            HookSpec("hermes_pre_llm_call.py.template", pre_script),
            HookSpec("hermes_post_llm_call.py.template", post_script),
        ),
        project_root=project_root,
        force=force,
        harness_mem_version=harness_mem_version,
        generated_at=generated_at,
        doc_pointer=doc_pointer,
    )

    pre_command = f'python "{pre_script.resolve().as_posix()}"'
    post_command = f'python "{post_script.resolve().as_posix()}"'
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

    return script_results + [
        HookInstallResult(target_path=config_path.resolve(), status=status)
    ]
