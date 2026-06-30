"""Generic IDE hook installer for the maintenance CLI.

A single :func:`install_hook` renders one of the packaged
``*.sh.template`` files (Cursor / Claude Code) and writes it to a target path.
The two ``integration install-*-hook`` subcommands compute the IDE-specific
``target_path`` + ``template_name`` and delegate here, so the rendering,
boundary self-check, and overwrite policy live in exactly one place.

Boundary self-check: after substitution the rendered body MUST contain
``python -m harness_mem.host_entry`` with an explicit hook action and MUST NOT
contain any non-comment line that invokes the ``harness-mem`` console script.
The check runs at install time, before the file is written, so a drifting
template can never produce a violating artifact on disk.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from string import Template

__all__ = ["HookInstallResult", "HookSpec", "install_hook", "install_hook_suite"]

# Default documentation pointer baked into generated hook headers.
DEFAULT_DOC_POINTER = "docs/quickstart.md"

_TEMPLATES_PACKAGE = "harness_mem.integration.templates"
_REQUIRED_HOST_ENTRY = "python -m harness_mem.host_entry"
# An executable invocation of the console script: a non-comment line where
# ``harness-mem`` is followed by whitespace and at least one more argument.
# ``^[^#]*`` cannot cross a ``#``, so any comment (leading or inline) is exempt.
_FORBIDDEN_INVOCATION = re.compile(r"^[^#]*\bharness-mem\s+\S")


def _render(body: str, *, project_root_abs: str, harness_mem_version: str,
            generated_at_iso: str, doc_pointer: str) -> str:
    """Substitute the four documented variables into the template body.

    Uses :meth:`string.Template.substitute` (not ``safe_substitute``) so a
    template referencing an undefined variable raises ``KeyError`` and surfaces
    template/installer drift loudly instead of silently emitting ``${FOO}``.
    """
    return Template(body).substitute(
        PROJECT_ROOT=project_root_abs,
        HARNESS_MEM_VERSION=harness_mem_version,
        GENERATED_AT=generated_at_iso,
        DOC_POINTER=doc_pointer,
    )


def _assert_boundary(rendered: str) -> None:
    """Enforce the hook boundary on a rendered body.

    Raises:
        RuntimeError: the body is missing the host-entry invocation or contains
            a non-comment ``harness-mem`` console-script invocation.
    """
    if _REQUIRED_HOST_ENTRY not in rendered:
        raise RuntimeError("rendered template contains forbidden pattern")
    if (
        "--action dream-end" not in rendered
        and "--action post-turn-maintenance" not in rendered
        and "--action wake-start" not in rendered
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

    body = (
        resources.files(_TEMPLATES_PACKAGE)
        .joinpath(template_name)
        .read_text(encoding="utf-8")
    )
    rendered = _render(
        body,
        project_root_abs=str(Path(project_root).resolve()),
        harness_mem_version=harness_mem_version,
        generated_at_iso=generated_at.isoformat(),
        doc_pointer=doc_pointer,
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
        )
        results.append(HookInstallResult(target_path=written, status="installed"))
    return results
