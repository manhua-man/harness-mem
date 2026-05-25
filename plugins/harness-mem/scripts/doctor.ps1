param()

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
$python = Get-Command python -ErrorAction Stop

Push-Location $repoRoot
try {
    & $python.Source -m harness_mem.cli doctor
    & $python.Source -m harness_mem.cli status
}
finally {
    Pop-Location
}

