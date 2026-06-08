$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot
$RunStamp = Get-Date -Format "yyyyMMddHHmmss"
$PytestTempRoot = Join-Path $RepoRoot ".tmp\pytest-tmp"
$PytestBaseTemp = Join-Path $RepoRoot ".tmp\pytest-full-$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestTempRoot | Out-Null
$env:TMP = $PytestTempRoot
$env:TEMP = $PytestTempRoot

$Commands = @(
    @{ Label = "pytest full"; Command = @("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", $PytestBaseTemp) },
    @{ Label = "ruff"; Command = @("python", "-m", "ruff", "check", ".") },
    @{ Label = "mypy"; Command = @("python", "-m", "mypy", "harness_mem") },
    @{ Label = "benchmark release artifacts"; Command = @("python", "benchmark-suite/tools/check_release_artifacts.py") }
)

foreach ($Step in $Commands) {
    Write-Host "Running $($Step.Label)..."
    $Executable = $Step.Command[0]
    $Arguments = @()
    if ($Step.Command.Count -gt 1) {
        $Arguments = $Step.Command[1..($Step.Command.Count - 1)]
    }
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
