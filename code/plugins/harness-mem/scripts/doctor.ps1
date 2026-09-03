param(
    [switch]$Wake
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
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
