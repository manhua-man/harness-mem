"""Exercise maintenance scripts with real PowerShell and an in-memory Python stub.

No fixture files, pip, host CLI, user configuration or memory stores are used.
Parser filenames provide detached-package scenarios without copying scripts.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "code/plugins/harness-mem/scripts"
SCRIPT_NAMES = ("install.ps1", "sync-commands.ps1", "doctor.ps1")
POWERSHELLS = [
    executable
    for name in ("pwsh", "powershell")
    if (executable := shutil.which(name))
]
pytestmark = pytest.mark.skipif(not POWERSHELLS, reason="PowerShell is unavailable")


def _ps_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_script(
    executable: str,
    name: str,
    cwd: Path,
    *,
    virtual_path: Path | None = None,
    arguments: dict[str, str | bool] | None = None,
) -> dict:
    source = SCRIPTS / name
    filename = virtual_path or source
    argv = ";".join(
        _ps_string(key) + " = " + (
            "$true" if value is True else "$false" if value is False else _ps_string(value)
        )
        for key, value in (arguments or {}).items()
    )
    program = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$global:hmMaintenanceCalls = @()
$global:hmMaintenanceLookups = 0
function Get-Command {{
    [CmdletBinding()]
    param([string]$Name)
    if ($Name -ne 'python') {{ throw "Unexpected executable lookup: $Name" }}
    $global:hmMaintenanceLookups++
    [pscustomobject]@{{ Source = 'Invoke-HmMaintenancePython' }}
}}
function Invoke-HmMaintenancePython {{
    $global:hmMaintenanceCalls += [pscustomobject]@{{
        arguments = @($args)
        cwd = (Get-Location).ProviderPath
    }}
    $global:LASTEXITCODE = 0
}}
$hmMaintenanceTokens = $null
$hmMaintenanceParseErrors = $null
$hmMaintenanceSource = [System.IO.File]::ReadAllText({_ps_string(source)})
$hmMaintenanceAst = [System.Management.Automation.Language.Parser]::ParseInput(
    $hmMaintenanceSource, {_ps_string(filename)},
    [ref]$hmMaintenanceTokens, [ref]$hmMaintenanceParseErrors
)
if ($hmMaintenanceParseErrors.Count) {{ throw 'Script parse failed' }}
$hmMaintenanceBlock = $hmMaintenanceAst.GetScriptBlock()
$hmMaintenanceArguments = @{{{argv}}}
$hmMaintenanceBefore = (Get-Location).ProviderPath
$hmMaintenanceError = $null
try {{
    & $hmMaintenanceBlock @hmMaintenanceArguments
}} catch {{
    $hmMaintenanceError = $_.Exception.Message
}}
$hmMaintenanceResult = [pscustomobject]@{{
    error = $hmMaintenanceError
    calls = @($global:hmMaintenanceCalls)
    lookups = $global:hmMaintenanceLookups
    before = $hmMaintenanceBefore
    after = (Get-Location).ProviderPath
}}
Write-Output ('HM_SCRIPT_PROBE=' + ($hmMaintenanceResult | ConvertTo-Json -Depth 6 -Compress))
"""
    encoded = base64.b64encode(program.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipts = [
        line.split("HM_SCRIPT_PROBE=", 1)[1]
        for line in completed.stdout.splitlines()
        if line.startswith("HM_SCRIPT_PROBE=")
    ]
    assert len(receipts) == 1, completed.stdout + completed.stderr
    return json.loads(receipts[0])


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


@pytest.mark.parametrize("executable", POWERSHELLS)
@pytest.mark.parametrize("name", SCRIPT_NAMES)
@pytest.mark.parametrize("cwd", (ROOT, ROOT / "code/tests", Path(tempfile.gettempdir())))
def test_maintenance_scripts_find_repo_independently_of_cwd(
    executable: str, name: str, cwd: Path,
) -> None:
    result = _run_script(executable, name, cwd)
    assert result["error"] is None
    assert result["lookups"] == 1
    assert len(result["calls"]) == 1
    assert _same_path(result["before"], cwd)
    assert _same_path(result["after"], cwd)
    call = result["calls"][0]
    if name == "install.ps1":
        assert call["arguments"][:4] == ["-m", "pip", "install", "-e"]
        assert _same_path(call["arguments"][4], ROOT)
    else:
        assert _same_path(call["cwd"], ROOT)
        expected = ["-m", "harness_mem.cli"]
        expected += ["doctor"] if name == "doctor.ps1" else [
            "integration", "commands", "sync", "--client", "all",
        ]
        assert call["arguments"] == expected


@pytest.mark.parametrize("executable", POWERSHELLS)
@pytest.mark.parametrize("name", SCRIPT_NAMES)
@pytest.mark.parametrize("detached", ("missing_manifest", "unrelated_plugin"))
def test_detached_scripts_fail_before_python_lookup(
    executable: str, name: str, detached: str,
) -> None:
    if detached == "missing_manifest":
        # Correct relative layout, but no repository or pyproject at this path.
        virtual = Path(tempfile.gettempdir()) / f"hm-detached-{uuid.uuid4().hex}"
        virtual /= f"code/plugins/harness-mem/scripts/{name}"
    else:
        # A real pyproject exists four levels up; it is not this plugin's tree.
        virtual = ROOT / f"code/plugins/unrelated-plugin/scripts/{name}"
    result = _run_script(executable, name, ROOT, virtual_path=virtual)
    assert "Cannot locate harness-mem repository root" in result["error"]
    assert "detached plugin packages" in result["error"]
    assert result["lookups"] == 0
    assert result["calls"] == []
    assert result["before"] == result["after"]


@pytest.mark.parametrize("executable", POWERSHELLS)
@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_existing_options_are_forwarded_to_stub(executable: str, name: str) -> None:
    arguments = {
        "install.ps1": {"WithHybrid": True},
        "sync-commands.ps1": {"Client": "hermes", "DryRun": True},
        "doctor.ps1": {"Wake": True},
    }[name]
    result = _run_script(executable, name, ROOT / "code/tests", arguments=arguments)
    assert result["error"] is None
    assert len(result["calls"]) == 1
    forwarded = result["calls"][0]["arguments"]
    if name == "install.ps1":
        assert _same_path(forwarded[-1], str(ROOT) + "[hybrid]")
    elif name == "sync-commands.ps1":
        assert forwarded == [
            "-m", "harness_mem.cli", "integration", "commands", "sync",
            "--client", "hermes", "--dry-run",
        ]
    else:
        assert forwarded == ["-m", "harness_mem.cli", "doctor"]
