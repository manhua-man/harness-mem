param(
    [ValidateSet("all", "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity")]
    [string]$Client = "all",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$expectedScripts = Join-Path $repoRoot "code/plugins/harness-mem/scripts"
$pyproject = Join-Path $repoRoot "pyproject.toml"

if ($PSScriptRoot -ne $expectedScripts -or -not (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
    throw "Cannot locate harness-mem repository root from '$PSScriptRoot'. Expected code/plugins/harness-mem/scripts beneath a root containing pyproject.toml; detached plugin packages are not supported."
}

$python = Get-Command python -ErrorAction Stop
$cliArgs = @(
    "-m", "harness_mem.cli",
    "integration", "commands", "sync",
    "--client", $Client
)

if ($DryRun) {
    $cliArgs += "--dry-run"
}

Push-Location $repoRoot
try {
    & $python.Source @cliArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
