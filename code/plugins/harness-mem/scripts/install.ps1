param(
    [switch]$WithHybrid
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$expectedScripts = Join-Path $repoRoot "code/plugins/harness-mem/scripts"
$pyproject = Join-Path $repoRoot "pyproject.toml"

if ($PSScriptRoot -ne $expectedScripts -or -not (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
    throw "Cannot locate harness-mem repository root from '$PSScriptRoot'. Expected code/plugins/harness-mem/scripts beneath a root containing pyproject.toml; detached plugin packages are not supported."
}

$python = Get-Command python -ErrorAction Stop
$installTarget = $repoRoot
if ($WithHybrid) {
    $installTarget = "${repoRoot}[hybrid]"
}

& $python.Source -m pip install -e $installTarget
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Installed harness-mem. Run harness-mem quickstart once in the Agent you use."
