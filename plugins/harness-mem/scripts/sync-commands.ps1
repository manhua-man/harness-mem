param(
    [ValidateSet("Daily", "Maintenance", "ProductDoc", "Labs", "Full")]
    [string]$Profile = "Daily",
    [switch]$IncludeMaintenanceCommands,
    [switch]$IncludeProductDocCommands,
    [switch]$IncludeLabsCommands,
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
    "Maintenance" { "maintenance" }
    "ProductDoc" { "product-doc" }
    "Labs" { "labs" }
    "Full" { "full" }
}

$cliArgs = @(
    "-m", "harness_mem.cli",
    "integration", "commands", "sync",
    "--profile", $profileArg,
    "--source-dir", $slashSrc
)

if ($IncludeMaintenanceCommands) {
    $cliArgs += @("--include", "maintenance")
}
if ($IncludeProductDocCommands) {
    $cliArgs += @("--include", "product-doc")
}
if ($IncludeLabsCommands) {
    $cliArgs += @("--include", "labs")
}
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
