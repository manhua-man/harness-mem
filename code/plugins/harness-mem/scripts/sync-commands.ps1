param(
    [ValidateSet("all", "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity")]
    [string]$Client = "all",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
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
