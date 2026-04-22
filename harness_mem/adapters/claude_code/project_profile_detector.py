"""Project profile auto-detector from project files."""

import json
from pathlib import Path
from typing import Optional

from harness_mem.core.schemas.project_profile import ProjectProfile


# Stack detection patterns
_STACK_MAP = {
    "php": ["php", "laravel", "composer"],
    "typescript": ["typescript", "next.js", "react", "node"],
    "python": ["python", "fastapi", "django", "flask"],
    "go": ["go", "golang"],
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
}


def detect_stacks(root: Path) -> list[str]:
    """Detect stacks from project files."""
    stacks = []
    for file_name in root.rglob("composer.json"):
        if "node_modules" not in str(file_name):
            stacks.append("php")
            stacks.append("laravel")
            break
    for file_name in root.rglob("package.json"):
        if "node_modules" not in str(file_name) and str(file_name).endswith("package.json"):
            try:
                data = json.loads(file_name.read_text())
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                all_deps = {**deps, **dev_deps}
                if "next" in all_deps:
                    stacks.append("next.js")
                if "react" in all_deps:
                    stacks.append("react")
                if "express" in all_deps:
                    stacks.append("express")
                if "typescript" in all_deps or any("@types/" in d for d in all_deps):
                    stacks.append("typescript")
                if "axios" in all_deps:
                    stacks.append("axios")
                if "python" not in stacks and "go" not in stacks:
                    stacks.append("node")
            except (json.JSONDecodeError, OSError):
                pass
    for file_name in root.rglob("pyproject.toml"):
        if "node_modules" not in str(file_name):
            stacks.append("python")
            break
    for file_name in root.rglob("go.mod"):
        stacks.append("go")
        break
    return list(set(stacks))


def detect_key_files(root: Path, stacks: list[str]) -> list[str]:
    """Detect important files based on stack."""
    key_files = []
    for stack in stacks:
        for pattern in _KEY_FILES.get(stack, []):
            # Check if any file matches this pattern
            if "/" in pattern:
                dir_path = root / pattern.rsplit("/", 1)[0]
                file_name = pattern.rsplit("/", 1)[1]
                if dir_path.exists():
                    for f in dir_path.rglob(file_name):
                        if "node_modules" not in str(f):
                            rel = f.relative_to(root)
                            key_files.append(str(rel))
                            break
            else:
                for f in root.rglob(pattern):
                    if "node_modules" not in str(f):
                        rel = f.relative_to(root)
                        key_files.append(str(rel))
                        break
    return list(set(key_files))[:10]  # Limit to 10


def build_project_profile(root: Path, project_name: Optional[str] = None) -> ProjectProfile:
    """Auto-detect and build a project profile from project files."""
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
