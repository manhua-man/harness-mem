param(
    [switch]$WithHybrid,
    [switch]$RegisterClaude
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

if ($RegisterClaude) {
    $claude = Get-Command claude -ErrorAction Stop
    & $claude.Source mcp add harness-mem -- python -m harness_mem.mcp.server
}

& $python.Source -m harness_mem.cli doctor

