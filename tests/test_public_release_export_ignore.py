from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_source_excludes_manifest_lists_maintainer_only_material() -> None:
    manifest = (REPO_ROOT / "release" / "public-source-excludes.txt").read_text(
        encoding="utf-8"
    )
    assert "docs/v2-user-test-packet.md" in manifest
    assert "harness_mem/integration/artifacts/" in manifest
    assert "benchmark-suite/" in manifest
    assert "docs/roadmap*.md" in manifest
    assert "docs/roadmap/" in manifest
    assert "docs/reference-projects.md" in manifest
    assert "openspec/" in manifest
    assert "tests/" in manifest


def test_gitattributes_marks_maintainer_only_material_export_ignore() -> None:
    attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/v2-user-test-packet.md export-ignore" in attrs
    assert "harness_mem/integration/artifacts/** export-ignore" in attrs
    assert "benchmark-suite/** export-ignore" in attrs
    assert "docs/roadmap*.md export-ignore" in attrs
    assert "docs/roadmap/** export-ignore" in attrs
    assert "docs/reference-projects.md export-ignore" in attrs
    assert "openspec/** export-ignore" in attrs
    assert "tests/** export-ignore" in attrs


def test_filter_script_removes_test_packet_from_archive(tmp_path: Path) -> None:
    import tarfile

    archive = tmp_path / "sample.tar.gz"
    manifest = REPO_ROOT / "release" / "public-source-excludes.txt"
    buf = __import__("io").BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"x"
        for name in (
            "harness-mem-0/docs/v2-user-test-packet.md",
            "harness-mem-0/docs/roadmap-v40.md",
            "harness-mem-0/docs/reference-projects.md",
            "harness-mem-0/benchmark-suite/README.md",
            "harness-mem-0/openspec/specs/memory.md",
            "harness-mem-0/tests/test_roadmap.py",
            "harness-mem-0/README.md",
            "harness-mem-0/harness_mem/integration/artifacts/foo.md",
            "harness-mem-0/docs/error-codes.md",
        ):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, __import__("io").BytesIO(data))
    archive.write_bytes(buf.getvalue())

    filter_script = REPO_ROOT / "scripts" / "filter_public_archive.py"
    subprocess.run(
        [__import__("sys").executable, str(filter_script), str(archive), "--manifest", str(manifest)],
        check=True,
        cwd=REPO_ROOT,
    )
    with tarfile.open(archive, mode="r:gz") as tar:
        names = tar.getnames()
    assert not any("v2-user-test-packet.md" in n for n in names)
    assert not any("integration/artifacts/" in n for n in names)
    assert not any("docs/roadmap" in n for n in names)
    assert not any("reference-projects.md" in n for n in names)
    assert not any("benchmark-suite/" in n for n in names)
    assert not any("openspec/" in n for n in names)
    assert not any("/tests/" in n for n in names)
    assert any(n.endswith("README.md") for n in names)
    assert any(n.endswith("docs/error-codes.md") for n in names)


def test_git_check_attr_export_ignore_on_test_packet() -> None:
    if not (REPO_ROOT / ".git").is_dir():
        return
    proc = subprocess.run(
        [
            "git",
            "check-attr",
            "export-ignore",
            "--",
            "docs/v2-user-test-packet.md",
            "docs/roadmap-v40.md",
            "benchmark-suite/README.md",
            "openspec/specs/memory.md",
            "tests/test_roadmap.py",
            "harness_mem/integration/artifacts/README.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "docs/v2-user-test-packet.md: export-ignore: set" in proc.stdout
    assert "docs/roadmap-v40.md: export-ignore: set" in proc.stdout
    assert "benchmark-suite/README.md: export-ignore: set" in proc.stdout
    assert "openspec/specs/memory.md: export-ignore: set" in proc.stdout
    assert "tests/test_roadmap.py: export-ignore: set" in proc.stdout
    assert "harness_mem/integration/artifacts/README.md: export-ignore: set" in proc.stdout


def test_sdist_config_only_includes_product_docs_and_runtime_package() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for included in [
        '"README.md"',
        '"CHANGELOG.md"',
        '"docs/error-codes.md"',
        '"harness_mem"',
    ]:
        assert included in pyproject

    for excluded in [
        '"AGENTS.md"',
        '"benchmark-suite"',
        '"docs/roadmap*.md"',
        '"docs/reference-projects.md"',
        '"openspec"',
        '"tests"',
    ]:
        assert excluded in pyproject
