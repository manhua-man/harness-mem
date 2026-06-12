"""Project profile auto-detector from project files."""

import json
import os
from pathlib import Path
from typing import Optional

from harness_mem.core.schemas.project_profile import ProjectProfile


_SKIP_DIR_NAMES = {
    ".git",
    ".agents",
    ".claude",
    ".codex",
    ".cursor",
    ".gstack",
    ".hypothesis",
    ".kiro",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".tmp-test-run",
    ".tox",
    ".venv",
    ".vs",
    ".uloop",
    "Library",
    "Temp",
    "__pycache__",
    "__tests__",
    "benchmark-suite",
    "benchmarks",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "obj",
    "release",
    "target",
    "test",
    "tests",
    "tmp",
    "tmp_pytest_codex",
    "vendor",
}


# Stack detection patterns
_STACK_MAP = {
    "php": ["php", "laravel", "composer"],
    "typescript": ["typescript", "next.js", "react", "node"],
    "python": ["python", "fastapi", "django", "flask"],
    "go": ["go", "golang"],
    "unity": ["unity", "csharp"],
}

# Key file patterns by stack
_KEY_FILES = {
    "php": [
        "composer.json",
        "backend/public/index.php",
        "backend/app/Services",
        "backend/config/database.php",
    ],
    "typescript": [
        "package.json",
        "frontend/src/app",
        "frontend/src/lib/api.ts",
        "next.config.js",
    ],
    "python": [
        "pyproject.toml",
        "requirements.txt",
        "app/main.py",
        "app/routes",
    ],
    "go": [
        "go.mod",
        "api/main.go",
        "cmd/server",
    ],
    "unity": [
        "ProjectSettings/ProjectVersion.txt",
        "Packages/manifest.json",
        "Assets",
    ],
    "csharp": [
        "Assembly-CSharp.csproj",
        "Assembly-CSharp-Editor.csproj",
    ],
}


def normalize_project_root(root: Path) -> Path:
    """Return the closest real project root for a scanned path.

    Claude sessions are often opened inside a subdirectory such as ``Assets``.
    For Unity projects that means the actual root is one level above the cwd.
    """
    try:
        root = root.expanduser().resolve()
    except OSError:
        root = root.expanduser()

    candidates = [root, *root.parents]
    for candidate in candidates:
        if _is_unity_project_root(candidate):
            return candidate
    return root


def _is_unity_project_root(root: Path) -> bool:
    return (
        (root / "Assets").is_dir()
        and (root / "ProjectSettings" / "ProjectVersion.txt").exists()
        and (root / "Packages" / "manifest.json").exists()
    )


def _iter_files_named(root: Path, file_name: str):
    for current_root, dir_names, file_names in os.walk(root):
        dir_names[:] = [name for name in dir_names if name not in _SKIP_DIR_NAMES]
        if file_name in file_names:
            yield Path(current_root) / file_name


def _add_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _relative_key(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def detect_stacks(root: Path) -> list[str]:
    """Detect stacks from project files."""
    stacks: list[str] = []
    root = normalize_project_root(root)

    if _is_unity_project_root(root):
        _add_once(stacks, "unity")
        _add_once(stacks, "csharp")

    for file_name in _iter_files_named(root, "composer.json"):
        _add_once(stacks, "php")
        _add_once(stacks, "laravel")
        break
    for file_name in _iter_files_named(root, "package.json"):
        try:
            data = json.loads(file_name.read_text())
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            all_deps = {**deps, **dev_deps}
            if "next" in all_deps:
                _add_once(stacks, "next.js")
            if "react" in all_deps:
                _add_once(stacks, "react")
            if "express" in all_deps:
                _add_once(stacks, "express")
            if "typescript" in all_deps or any("@types/" in d for d in all_deps):
                _add_once(stacks, "typescript")
            if "axios" in all_deps:
                _add_once(stacks, "axios")
            if "python" not in stacks and "go" not in stacks:
                _add_once(stacks, "node")
        except (json.JSONDecodeError, OSError):
            pass
    for file_name in _iter_files_named(root, "pyproject.toml"):
        _add_once(stacks, "python")
        break
    for file_name in _iter_files_named(root, "go.mod"):
        _add_once(stacks, "go")
        break
    return stacks


def detect_key_files(root: Path, stacks: list[str]) -> list[str]:
    """Detect important files based on stack."""
    key_files: list[str] = []
    root = normalize_project_root(root)
    for stack in stacks:
        for pattern in _KEY_FILES.get(stack, []):
            target = root / pattern
            if target.exists():
                key_files.append(_relative_key(root, target))
            elif "/" in pattern:
                dir_path = root / pattern.rsplit("/", 1)[0]
                file_name = pattern.rsplit("/", 1)[1]
                if dir_path.exists() and dir_path.is_dir():
                    for f in _iter_files_named(dir_path, file_name):
                        key_files.append(_relative_key(root, f))
                        break
            else:
                for f in _iter_files_named(root, pattern):
                    key_files.append(_relative_key(root, f))
                    break

    for sln_file in _iter_files_named(root, f"{root.name}.sln"):
        key_files.append(_relative_key(root, sln_file))
        break

    return list(dict.fromkeys(key_files))[:10]  # Limit to 10


def build_project_profile(root: Path, project_name: Optional[str] = None) -> ProjectProfile:
    """Auto-detect and build a project profile from project files."""
    root = normalize_project_root(root)
    if project_name is None:
        project_name = root.name

    stacks = detect_stacks(root)
    key_files = detect_key_files(root, stacks)

    description = f"{project_name}: {', '.join(stacks)}" if stacks else project_name

    return ProjectProfile(
        project_name=project_name,
        description=description,
        stacks=stacks,
        key_files=key_files,
    )
