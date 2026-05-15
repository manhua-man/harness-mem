param(
    [switch]$Wake,
    [string]$Search
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
$python = Get-Command python -ErrorAction Stop

Push-Location $repoRoot
try {
    & $python.Source -m harness_mem.cli doctor
    & $python.Source -m harness_mem.cli status

    if ($Wake) {
        & $python.Source -m harness_mem.cli wake
    }

    if ($Search) {
        & $python.Source -m harness_mem.cli search $Search --mode auto
    }
}
finally {
    Pop-Location
}

