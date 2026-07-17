param(
    [ValidateSet("Daily")]
    [string]$Profile = "Daily",
    [ValidateSet("all", "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity")]
    [string]$Client = "all",
    [ValidateSet("user", "project")]
    [string]$Scope = "user",
    [string]$TargetDir,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $pluginRoot "..\..")
$slashSrc = Join-Path $pluginRoot "commands\hm"

if (-not (Test-Path $slashSrc)) {
    throw "Slash command source not found at $slashSrc"
}

$python = Get-Command python -ErrorAction Stop

$profileArg = switch ($Profile) {
    "Daily" { "daily" }
}

if ($TargetDir -and $Client -eq "all") {
    $Client = "claude-code"
}
if ($TargetDir -and $Client -ne "claude-code") {
    throw "-TargetDir is only supported with -Client claude-code"
}

$cliArgs = @(
    "-m", "harness_mem.cli",
    "integration", "commands", "sync",
    "--profile", $profileArg,
    "--client", $Client,
    "--scope", $Scope,
    "--source-dir", $slashSrc
)

if ($TargetDir) {
    $cliArgs += @("--target-dir", $TargetDir)
}
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
