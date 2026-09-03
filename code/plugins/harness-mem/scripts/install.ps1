param(
    [switch]$WithHybrid
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
$pyproject = Join-Path $repoRoot "pyproject.toml"

if (-not (Test-Path $pyproject)) {
    throw "Could not find pyproject.toml at $pyproject"
}

$python = Get-Command python -ErrorAction Stop
$installTarget = $repoRoot.Path
if ($WithHybrid) {
    $installTarget = "$($repoRoot.Path)[hybrid]"
}

& $python.Source -m pip install -e $installTarget
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Installed harness-mem. Run harness-mem quickstart once in the Agent you use."
