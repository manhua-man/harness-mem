$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$Commands = @(
    @{ Label = "pytest full"; Command = @("python", "-m", "pytest", "-q") },
    @{ Label = "ruff"; Command = @("python", "-m", "ruff", "check", ".") },
    @{ Label = "mypy"; Command = @("python", "-m", "mypy", "harness_mem") }
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
