from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_source_excludes_manifest_lists_test_packet() -> None:
    manifest = (REPO_ROOT / "release" / "public-source-excludes.txt").read_text(
        encoding="utf-8"
    )
    assert "docs/v2-user-test-packet.md" in manifest
    assert "harness_mem/integration/artifacts/" in manifest


def test_gitattributes_marks_test_packet_export_ignore() -> None:
    attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/v2-user-test-packet.md export-ignore" in attrs
    assert "harness_mem/integration/artifacts/** export-ignore" in attrs


def test_filter_script_removes_test_packet_from_archive(tmp_path: Path) -> None:
    import tarfile

    archive = tmp_path / "sample.tar.gz"
    manifest = REPO_ROOT / "release" / "public-source-excludes.txt"
    buf = __import__("io").BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"x"
        for name in (
            "harness-mem-0/docs/v2-user-test-packet.md",
            "harness-mem-0/README.md",
            "harness-mem-0/harness_mem/integration/artifacts/foo.md",
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
    assert any(n.endswith("README.md") for n in names)


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
            "harness_mem/integration/artifacts/README.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "docs/v2-user-test-packet.md: export-ignore: set" in proc.stdout
    assert "harness_mem/integration/artifacts/README.md: export-ignore: set" in proc.stdout
