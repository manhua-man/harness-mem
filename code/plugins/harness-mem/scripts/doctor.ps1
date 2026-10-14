param(
    [switch]$Wake
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$expectedScripts = Join-Path $repoRoot "code/plugins/harness-mem/scripts"
$pyproject = Join-Path $repoRoot "pyproject.toml"

if ($PSScriptRoot -ne $expectedScripts -or -not (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
    throw "Cannot locate harness-mem repository root from '$PSScriptRoot'. Expected code/plugins/harness-mem/scripts beneath a root containing pyproject.toml; detached plugin packages are not supported."
}

$python = Get-Command python -ErrorAction Stop

Push-Location $repoRoot
try {
    & $python.Source -m harness_mem.cli doctor
    if ($Wake) {
        Write-Host ""
        Write-Host "Wake hint:"
        Write-Host "  In Claude Code: /hm"
        Write-Host "  In other AI IDEs: ask harness-mem to wake the active project."
    }
}
finally {
    Pop-Location
}
